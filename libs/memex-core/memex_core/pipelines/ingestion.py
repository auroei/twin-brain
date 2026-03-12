"""
Ingestion pipeline for memex-core.
Orchestrates the "Watch" workflow: curate -> store -> classify -> update.
Enhanced to pass vector_store to classifier for RAG-based few-shot examples.
Enhanced with event-driven updates for automatic deprecation of superseded threads.
Enhanced with atomic memory extraction for fine-grained knowledge representation.
"""

import re
from typing import Optional, List, Dict, Any, TYPE_CHECKING

from ..models import SlackThread, RoleDefinition, LifecycleStatus, MemoryExtractionResult
from ..memory.curator import MemoryCurator
from ..ai.classifier import ThreadClassifier
from ..ai.client import GeminiClient
from ..storage.vector_store import ChromaVectorStore
from ..utils import format_thread
from ..prompts import render_prompt

if TYPE_CHECKING:
    from ..ai.memory_extractor import MemoryExtractor


class IngestionPipeline:
    """
    Pipeline for ingesting Slack threads into the knowledge base.
    Orchestrates the full workflow: curation, storage, classification, and metadata update.
    
    Enhanced to pass vector_store to classifier for RAG-based classification
    using similar already-classified threads as few-shot examples.
    
    Enhanced with event-driven updates:
    - When a thread is classified as a #decision, searches for conflicting
      old threads and marks them as deprecated.
    """
    
    # Topics/keywords that indicate a decision thread
    DECISION_INDICATORS = [
        "decision", "decided", "final", "approved", "confirmed",
        "moving forward", "we will", "going with", "strategy update",
        "#decision", "#final", "#approved"
    ]
    
    def __init__(
        self,
        curator: MemoryCurator,
        classifier: ThreadClassifier,
        vector_store: ChromaVectorStore,
        supersession_client: Optional[GeminiClient] = None,
        memory_extractor: "MemoryExtractor" = None,
    ):
        """
        Initialize IngestionPipeline.
        
        Args:
            curator: MemoryCurator instance for filtering low-quality threads
            classifier: ThreadClassifier instance for categorizing threads
            vector_store: ChromaVectorStore instance for persistent storage
            supersession_client: Optional GeminiClient for detecting supersession
            memory_extractor: MemoryExtractor for atomic memory extraction
        """
        self.curator = curator
        self.classifier = classifier
        self.vector_store = vector_store
        self.supersession_client = supersession_client
        self.memory_extractor = memory_extractor
        
        if not memory_extractor:
            print("⚠️ IngestionPipeline: memory_extractor not provided, atomic memories will not be extracted")
    
    def _is_decision_thread(self, thread: SlackThread, classification) -> bool:
        """
        Determine if a thread represents a decision.
        
        Args:
            thread: SlackThread instance
            classification: ThreadClassification result
            
        Returns:
            True if this thread appears to be a decision
        """
        # Check topic from classification
        if classification and classification.topic:
            topic_lower = classification.topic.lower()
            if any(ind in topic_lower for ind in ["decision", "strategy", "final"]):
                return True
        
        # Check thread content for decision indicators
        thread_text = " ".join(msg.text.lower() for msg in thread.messages)
        for indicator in self.DECISION_INDICATORS:
            if indicator.lower() in thread_text:
                return True
        
        return False
    
    def _detect_supersession(
        self,
        new_thread: Dict[str, Any],
        existing_thread: Dict[str, Any]
    ) -> str:
        """
        Use LLM to determine if new thread supersedes existing thread.
        
        Args:
            new_thread: Dict with thread_name, summary, project, theme, document
            existing_thread: Dict with thread_name, summary, project, theme, document
            
        Returns:
            "SUPERSEDES", "RELATED", or "UNRELATED"
        """
        if not self.supersession_client:
            # Without LLM, use simple heuristics
            # Same project = likely supersedes
            if (new_thread.get("project") and 
                new_thread["project"] == existing_thread.get("project") and
                new_thread["project"] != "Ad-hoc"):
                return "SUPERSEDES"
            return "RELATED"
        
        # Use LLM for more nuanced detection
        prompt = render_prompt(
            "detect_supersession",
            new_thread=new_thread,
            existing_thread=existing_thread
        )
        
        try:
            response = self.supersession_client.call_with_retry(prompt)
            response_upper = response.strip().upper()
            
            if response_upper.startswith("SUPERSEDES"):
                return "SUPERSEDES"
            elif response_upper.startswith("UNRELATED"):
                return "UNRELATED"
            else:
                return "RELATED"
                
        except Exception as e:
            print(f"⚠️  Supersession detection failed: {e}")
            return "RELATED"
    
    def _handle_decision_event(
        self,
        thread: SlackThread,
        classification,
        formatted_thread: str
    ) -> List[str]:
        """
        Handle a decision event by finding and deprecating superseded threads.
        
        Args:
            thread: The new decision thread
            classification: ThreadClassification for the decision
            formatted_thread: Formatted text of the decision thread
            
        Returns:
            List of thread_ts that were deprecated
        """
        print(f"🔔 Decision event detected - checking for superseded threads...")
        
        deprecated_threads = []
        
        # Find related threads (same project/theme)
        related = self.vector_store.find_related_threads(
            project=classification.project,
            theme=classification.theme,
            exclude_thread_ts=thread.thread_ts,
            lifecycle_status=LifecycleStatus.ACTIVE
        )
        
        if not related:
            print(f"   No related active threads found")
            return deprecated_threads
        
        print(f"   Found {len(related)} related threads to check")
        
        # Prepare new thread data for comparison
        new_thread_data = {
            "thread_name": classification.thread_name,
            "summary": classification.summary,
            "project": classification.project,
            "theme": classification.theme,
            "document": formatted_thread[:800]
        }
        
        for related_thread in related:
            meta = related_thread.get("metadata", {})
            existing_data = {
                "thread_name": meta.get("thread_name", ""),
                "summary": meta.get("summary", ""),
                "project": meta.get("project", ""),
                "theme": meta.get("theme", ""),
                "document": related_thread.get("document", "")[:800]
            }
            
            # Check if new thread supersedes existing
            result = self._detect_supersession(new_thread_data, existing_data)
            
            if result == "SUPERSEDES":
                related_ts = related_thread.get("thread_ts")
                print(f"   🔄 Deprecating superseded thread: {related_ts}")
                print(f"      Old: {meta.get('thread_name', 'Unknown')}")
                print(f"      New: {classification.thread_name}")
                
                # Update lifecycle status
                self.vector_store.update_lifecycle_status(
                    related_ts,
                    LifecycleStatus.DEPRECATED,
                    superseded_by=thread.thread_ts
                )
                
                deprecated_threads.append(related_ts)
        
        if deprecated_threads:
            print(f"   ✅ Deprecated {len(deprecated_threads)} superseded thread(s)")
        else:
            print(f"   No threads were superseded")
        
        return deprecated_threads
    
    def extract_and_store_memories(
        self,
        thread: SlackThread,
        role_def: RoleDefinition,
        force_reextract: bool = False,
    ) -> MemoryExtractionResult:
        """
        Extract atomic memories from a thread and store them.
        
        This should be called after thread classification for best results.
        Skips extraction if memories already exist for the thread (prevents
        duplicates during catchup).
        
        Args:
            thread: SlackThread to extract memories from
            role_def: RoleDefinition for domain context
            force_reextract: If True, re-extract even if memories exist
            
        Returns:
            MemoryExtractionResult with extracted memories
        """
        if not self.memory_extractor:
            return MemoryExtractionResult(thread_ts=thread.thread_ts, memories=[])
        
        # Check if memories already exist for this thread (skip during catchup)
        if not force_reextract:
            existing_thread_memories = self.vector_store.get_memories_for_thread(thread.thread_ts)
            if existing_thread_memories:
                print(f"ℹ️ Memories already exist for thread {thread.thread_ts}, skipping extraction ({len(existing_thread_memories)} memories)")
                return MemoryExtractionResult(
                    thread_ts=thread.thread_ts, 
                    memories=existing_thread_memories,
                    extraction_metadata={"skipped": True, "existing_count": len(existing_thread_memories)}
                )
        
        # Format thread for extraction
        messages_dict = [{"user": msg.user, "text": msg.text} for msg in thread.messages]
        formatted_thread = format_thread(messages_dict)
        
        # Get existing memories for relationship detection
        existing_memories = self.vector_store.get_recent_memories(n=50)
        
        # Extract memories
        result = self.memory_extractor.extract_memories(
            thread_text=formatted_thread,
            thread_ts=thread.thread_ts,
            channel_id=thread.channel_id,
            role_def=role_def,
            existing_memories=existing_memories,
        )
        
        if result.memories:
            # Store memories in batch
            self.vector_store.upsert_memories_batch(result.memories)
            print(f"🧠 Stored {len(result.memories)} atomic memories for thread {thread.thread_ts}")
        
        return result
    
    def process_thread(
        self,
        thread: SlackThread,
        role_def: RoleDefinition,
        behavior_config: Optional[dict] = None,
        skip_classification: bool = False,
        generate_context: bool = True,
    ) -> bool:
        """
        Process a thread through the full ingestion pipeline.
        
        Steps:
        1. Run curator.should_ingest() to filter low-quality threads
        2. Run vector_store.upsert_thread() to save immediately (with "Pending" classification)
        3. Run classifier.classify_thread() to categorize the thread (with RAG examples)
        4. Extract atomic memories from thread
        5. Run vector_store.update_thread_classification() to update metadata
        
        Args:
            thread: SlackThread instance to process
            role_def: RoleDefinition for classification context
            behavior_config: Optional behavior configuration for classifier
            skip_classification: If True, skip classification step (useful for async classification)
            generate_context: If True, generate contextual embeddings (default True)
            
        Returns:
            True if thread was ingested successfully, False if filtered out or error
        """
        # Step 1: Curation - check if thread should be ingested
        should_ingest, reason = self.curator.should_ingest(thread)
        if not should_ingest:
            print(f"🚫 Skipped (Low Quality): {reason}")
            return False
        
        # Step 2: Immediate storage (with "Pending" classification)
        try:
            self.vector_store.upsert_thread(thread, generate_context=generate_context)
            print(f"📝 Stored thread {thread.thread_ts} (pending classification)")
        except Exception as e:
            print(f"❌ Error storing thread {thread.thread_ts}: {e}")
            return False
        
        # Step 3 & 4: Classification and metadata update (if not skipped)
        if not skip_classification:
            try:
                # Format thread for classification
                messages_dict = [{"user": msg.user, "text": msg.text} for msg in thread.messages]
                formatted_thread = format_thread(messages_dict)
                
                # Classify the thread with RAG (pass vector_store for similar examples)
                classification = self.classifier.classify_thread(
                    formatted_thread,
                    role_def,
                    behavior_config=behavior_config,
                    vector_store=self.vector_store
                )
                
                print(f"🏷️  Classified thread {thread.thread_ts}: "
                      f"theme={classification.theme}, product={classification.product}, "
                      f"project={classification.project}, topic={classification.topic}")
                
                # Update thread with classification
                thread.classification = classification
                
                # Update classification in vector store
                self.vector_store.update_thread_classification(thread.thread_ts, classification)
                print(f"✅ Classification updated for thread {thread.thread_ts}")
                
                # Extract atomic memories
                if self.memory_extractor:
                    try:
                        memory_result = self.extract_and_store_memories(thread, role_def)
                        if memory_result.memories:
                            print(f"🧠 Extracted {len(memory_result.memories)} atomic memories")
                    except Exception as mem_error:
                        print(f"⚠️  Memory extraction failed: {mem_error}")
                
                # EVENT-DRIVEN UPDATE: Check if this is a decision thread
                if self._is_decision_thread(thread, classification):
                    self._handle_decision_event(thread, classification, formatted_thread)
                
            except Exception as e:
                print(f"⚠️  Error classifying thread {thread.thread_ts}: {e}")
                # Thread is still stored, just without classification
                # Return True since storage succeeded
        
        return True
    
    def process_thread_async(
        self,
        thread: SlackThread,
        role_def: RoleDefinition,
        behavior_config: Optional[dict] = None,
        generate_context: bool = True
    ) -> bool:
        """
        Process a thread with immediate storage, returning quickly.
        Classification is skipped - caller should handle classification separately.
        
        This is useful for responsive UX where you want to acknowledge receipt
        immediately and classify in the background.
        
        Args:
            thread: SlackThread instance to process
            role_def: RoleDefinition for classification context (not used, kept for API consistency)
            behavior_config: Optional behavior configuration (not used, kept for API consistency)
            generate_context: If True, generate contextual embeddings (default True)
            
        Returns:
            True if thread was stored successfully, False if filtered out or error
        """
        return self.process_thread(
            thread,
            role_def,
            behavior_config=behavior_config,
            skip_classification=True,
            generate_context=generate_context
        )
    
    def classify_thread(
        self,
        thread: SlackThread,
        role_def: RoleDefinition,
        behavior_config: Optional[dict] = None
    ) -> bool:
        """
        Classify an already-stored thread and update its metadata.
        Use this after process_thread_async() for background classification.
        
        Enhanced with RAG: passes vector_store to classifier so it can
        retrieve similar already-classified threads as few-shot examples.
        
        Args:
            thread: SlackThread instance to classify
            role_def: RoleDefinition for classification context
            behavior_config: Optional behavior configuration for classifier
            
        Returns:
            True if classification succeeded, False otherwise
        """
        try:
            # Format thread for classification
            messages_dict = [{"user": msg.user, "text": msg.text} for msg in thread.messages]
            formatted_thread = format_thread(messages_dict)
            
            # Classify the thread with RAG (pass vector_store for similar examples)
            classification = self.classifier.classify_thread(
                formatted_thread,
                role_def,
                behavior_config=behavior_config,
                vector_store=self.vector_store
            )
            
            print(f"🏷️  Classified thread {thread.thread_ts}: "
                  f"theme={classification.theme}, product={classification.product}, "
                  f"project={classification.project}, topic={classification.topic}")
            print(f"   Thread Name: {classification.thread_name}")
            print(f"   Summary: {classification.summary}")
            
            # Update thread with classification
            thread.classification = classification
            
            # Update classification in vector store
            self.vector_store.update_thread_classification(thread.thread_ts, classification)
            print(f"✅ Classification updated for thread {thread.thread_ts}")
            
            return True
            
        except Exception as e:
            print(f"❌ Error classifying thread {thread.thread_ts}: {e}")
            return False
