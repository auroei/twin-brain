"""
Vector store module for memex-core.
Handles vector database operations using ChromaDB.
Enhanced with contextual embeddings for improved retrieval quality.
Enhanced with lifecycle management for memory abstractions (lineage & status).
Enhanced with atomic memory storage and hybrid retrieval.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any

import chromadb
from chromadb.utils.embedding_functions import GoogleGenerativeAiEmbeddingFunction

from ..models import (
    SlackThread, 
    ThreadClassification, 
    LifecycleStatus, 
    DailyInsight,
    AtomicMemory,
    MemoryRelation,
    TemporalMetadata,
)
from ..utils import format_thread, clean_query, parse_datetime_robust, parse_datetime_list_robust


def _limit_retrieved_docs(docs: List[str], max_docs: int = 10, max_total_length: int = 6000) -> List[str]:
    """
    Limit retrieved documents to prevent context overflow.
    
    Args:
        docs: List of document strings
        max_docs: Maximum number of documents to return
        max_total_length: Maximum total character length
        
    Returns:
        Limited list of documents
    """
    limited_docs = []
    total_length = 0
    
    for doc in docs[:max_docs]:
        doc_length = len(doc)
        if total_length + doc_length > max_total_length:
            # Truncate this doc to fit
            remaining = max_total_length - total_length
            if remaining > 100:  # Only add if meaningful space remains
                limited_docs.append(doc[:remaining] + "... (truncated)")
            break
        limited_docs.append(doc)
        total_length += doc_length
    
    return limited_docs


def _truncate_context(text: str, max_length: int = 8000) -> str:
    """
    Truncate context text to avoid overflow.
    
    Args:
        text: Context text to truncate
        max_length: Maximum length in characters
        
    Returns:
        Truncated text
    """
    if len(text) <= max_length:
        return text
    return text[:max_length] + "\n... (truncated)"


class ChromaVectorStore:
    """
    Vector database client for storing and querying Slack threads.
    Uses ChromaDB with Google Generative AI embeddings.
    
    Enhanced with contextual embeddings to improve retrieval quality
    by prepending document-level context to threads before embedding.
    """
    
    def __init__(
        self,
        persist_directory: str = "./my_knowledge_base",
        collection_name: str = "slack_knowledge",
        api_key: Optional[str] = None,
        context_client=None
    ):
        """
        Initialize ChromaVectorStore with ChromaDB client and embedding function.
        
        Args:
            persist_directory: Directory path for persistent ChromaDB storage
            collection_name: Name of the ChromaDB collection
            api_key: Google Gemini API key for embeddings (if None, must be configured separately)
            context_client: Optional GeminiClient for generating contextual descriptions
        """
        # Initialize ChromaDB client
        self.client = chromadb.PersistentClient(path=persist_directory)
        
        # Configure embedding function
        # Note: api_key is required for GoogleGenerativeAiEmbeddingFunction
        if not api_key:
            raise ValueError("api_key is required for GoogleGenerativeAiEmbeddingFunction")
        
        self.embedding_function = GoogleGenerativeAiEmbeddingFunction(
            api_key=api_key,
            task_type="RETRIEVAL_DOCUMENT"
        )
        
        # Get or create collection
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            embedding_function=self.embedding_function
        )
        
        # Create separate collection for atomic memories
        self.memory_collection = self.client.get_or_create_collection(
            name=f"{collection_name}_memories",
            embedding_function=self.embedding_function
        )
        
        # Store context client for contextual embeddings
        self.context_client = context_client
    
    def _generate_thread_context(self, thread_text: str, metadata: dict) -> str:
        """
        Generate contextual description to prepend to thread before embedding.
        
        This improves retrieval by adding semantic context that helps
        the embedding model understand what the thread is about.
        
        Args:
            thread_text: The formatted thread text
            metadata: Thread metadata (channel, classification, etc.)
            
        Returns:
            Contextual description string, or empty string if generation fails
        """
        if not self.context_client:
            return ""
        
        # Build context hints from metadata
        context_hints = []
        if metadata.get("channel"):
            context_hints.append(f"Channel: {metadata['channel']}")
        if metadata.get("classification"):
            cls = metadata["classification"]
            if hasattr(cls, 'theme') and cls.theme and cls.theme != "Pending":
                context_hints.append(f"Theme: {cls.theme}")
            if hasattr(cls, 'product') and cls.product and cls.product != "Pending":
                context_hints.append(f"Product: {cls.product}")
        
        hints_str = ", ".join(context_hints) if context_hints else ""
        
        prompt = f"""<thread>
{thread_text[:2000]}
</thread>

{f"Context hints: {hints_str}" if hints_str else ""}

Generate a brief context (2-3 sentences) to situate this Slack thread for search retrieval. Include:
- What this thread is primarily about
- Key entities mentioned (people, products, projects)
- The type of discussion (decision, question, update, brainstorm, issue)

Answer ONLY with the context description, no preamble or explanation."""

        try:
            context = self.context_client.call_with_retry(prompt)
            # Clean up the response
            context = context.strip()
            # Remove any potential preamble patterns
            if context.lower().startswith("this thread"):
                pass  # Keep as-is, good format
            elif context.lower().startswith("context:"):
                context = context[8:].strip()
            return context
        except Exception as e:
            print(f"⚠️ Context generation failed: {e}")
            return ""
    
    def upsert_thread(self, thread: SlackThread, generate_context: bool = True) -> None:
        """
        Upsert a Slack thread into the vector database.
        
        When context_client is available and generate_context is True,
        generates a contextual description to prepend to the thread
        before embedding for improved retrieval.
        
        Args:
            thread: SlackThread model instance to store
            generate_context: Whether to generate contextual embeddings (default True)
        """
        # Format thread messages into a single string
        messages_dict = [{"user": msg.user, "text": msg.text} for msg in thread.messages]
        formatted_thread = format_thread(messages_dict)
        
        if not formatted_thread.strip():
            print(f"⚠️  Skipping empty thread {thread.thread_ts}")
            return
        
        # Generate thread ID
        thread_id = f"thread_{thread.thread_ts}"
        
        # Build metadata
        metadata = {
            "thread_ts": thread.thread_ts,
            "channel": thread.channel_id,
            "last_updated": datetime.now().isoformat(),
            "message_count": len(thread.messages),
        }
        
        # Add classification metadata if available
        if thread.classification:
            metadata.update({
                "theme": thread.classification.theme,
                "product": thread.classification.product,
                "project": thread.classification.project,
                "topic": thread.classification.topic,
                "thread_name": thread.classification.thread_name,
                "summary": thread.classification.summary,
                # Lifecycle management fields
                "lifecycle_status": thread.classification.lifecycle_status.value if thread.classification.lifecycle_status else LifecycleStatus.ACTIVE.value,
                "supersedes_thread_id": thread.classification.supersedes_thread_id or ""
            })
        else:
            # Use "Pending" values if classification not available
            metadata.update({
                "theme": "Pending",
                "product": "Pending",
                "project": "Pending",
                "topic": "Pending",
                "thread_name": "Pending",
                "summary": "Pending",
                # Default lifecycle for new threads
                "lifecycle_status": LifecycleStatus.ACTIVE.value,
                "supersedes_thread_id": ""
            })
        
        # Generate contextual description if client is available
        context_description = ""
        if generate_context and self.context_client:
            context_description = self._generate_thread_context(
                formatted_thread,
                {"channel": thread.channel_id, "classification": thread.classification}
            )
            if context_description:
                metadata["contextual_description"] = context_description
        
        # Combine context + original thread for embedding
        if context_description:
            text_to_embed = f"{context_description}\n\n---\n\n{formatted_thread}"
        else:
            text_to_embed = formatted_thread
        
        # Upsert into ChromaDB
        self.collection.upsert(
            ids=[thread_id],
            documents=[text_to_embed],
            metadatas=[metadata]
        )
    
    def update_thread_classification(
        self,
        thread_ts: str,
        classification: ThreadClassification
    ) -> None:
        """
        Update the classification metadata for an existing thread.
        
        Args:
            thread_ts: Thread timestamp identifier
            classification: ThreadClassification model instance
        """
        thread_id = f"thread_{thread_ts}"
        
        # Get existing document (we need to keep the document text)
        results = self.collection.get(ids=[thread_id])
        
        if not results["ids"]:
            print(f"⚠️  Thread {thread_ts} not found for classification update")
            return
        
        # Get the existing document and metadata
        existing_doc = results["documents"][0] if results["documents"] else ""
        existing_meta = results["metadatas"][0] if results["metadatas"] else {}
        
        # Update metadata including lifecycle fields
        metadata = {
            "thread_ts": thread_ts,
            "last_updated": datetime.now().isoformat(),
            "last_classified_at": datetime.now().isoformat(),
            "message_count": existing_meta.get("message_count", 0),
            "theme": classification.theme,
            "product": classification.product,
            "project": classification.project,
            "topic": classification.topic,
            "thread_name": classification.thread_name,
            "summary": classification.summary,
            # Lifecycle management fields
            "lifecycle_status": classification.lifecycle_status.value if classification.lifecycle_status else LifecycleStatus.ACTIVE.value,
            "supersedes_thread_id": classification.supersedes_thread_id or ""
        }
        
        # Preserve channel if it exists in existing metadata
        if existing_meta.get("channel"):
            metadata["channel"] = existing_meta["channel"]
        
        # Preserve contextual_description if it exists
        if existing_meta.get("contextual_description"):
            metadata["contextual_description"] = existing_meta["contextual_description"]
        
        # Upsert with updated metadata
        self.collection.upsert(
            ids=[thread_id],
            documents=[existing_doc],
            metadatas=[metadata]
        )
    
    def update_lifecycle_status(
        self,
        thread_ts: str,
        lifecycle_status: LifecycleStatus,
        superseded_by: Optional[str] = None
    ) -> bool:
        """
        Update the lifecycle status of a thread.
        
        Args:
            thread_ts: Thread timestamp identifier
            lifecycle_status: New lifecycle status (Draft, Active, Deprecated)
            superseded_by: Optional thread ID that supersedes this one
            
        Returns:
            True if update succeeded, False otherwise
        """
        thread_id = f"thread_{thread_ts}"
        
        # Get existing document and metadata
        results = self.collection.get(ids=[thread_id])
        
        if not results["ids"]:
            print(f"⚠️  Thread {thread_ts} not found for lifecycle update")
            return False
        
        existing_doc = results["documents"][0] if results["documents"] else ""
        existing_meta = results["metadatas"][0] if results["metadatas"] else {}
        
        # Update metadata with new lifecycle status
        existing_meta["lifecycle_status"] = lifecycle_status.value
        existing_meta["last_updated"] = datetime.now().isoformat()
        
        if superseded_by:
            existing_meta["superseded_by"] = superseded_by
        
        # Upsert with updated metadata
        self.collection.upsert(
            ids=[thread_id],
            documents=[existing_doc],
            metadatas=[existing_meta]
        )
        
        print(f"🔄 Updated lifecycle for {thread_ts}: {lifecycle_status.value}")
        return True
    
    def update_feedback_score(
        self,
        thread_ts: str,
        delta: float,
        score_min: float = -1.0,
        score_max: float = 2.0
    ) -> bool:
        """
        Increment or decrement the feedback_score in thread metadata.
        
        This is part of L2 reinforcement learning: threads that are sources
        of well-received answers get boosted, while sources of poorly-received
        answers get penalized. The score affects future retrieval ranking.
        
        Args:
            thread_ts: Thread timestamp identifier
            delta: Amount to add to feedback_score (positive or negative)
            score_min: Minimum allowed score (floor)
            score_max: Maximum allowed score (ceiling)
            
        Returns:
            True if update succeeded, False if thread not found
        """
        thread_id = f"thread_{thread_ts}"
        
        # Get existing document and metadata
        results = self.collection.get(ids=[thread_id])
        
        if not results["ids"]:
            print(f"⚠️  Thread {thread_ts} not found for feedback score update")
            return False
        
        existing_doc = results["documents"][0] if results["documents"] else ""
        existing_meta = results["metadatas"][0] if results["metadatas"] else {}
        
        # Get current score and apply delta with clamping
        current_score = float(existing_meta.get("feedback_score", 0.0))
        new_score = max(score_min, min(score_max, current_score + delta))
        
        # Update metadata
        existing_meta["feedback_score"] = new_score
        existing_meta["last_feedback"] = datetime.now().isoformat()
        
        # Upsert with updated metadata
        self.collection.upsert(
            ids=[thread_id],
            documents=[existing_doc],
            metadatas=[existing_meta]
        )
        
        sign = "+" if delta > 0 else ""
        print(f"📊 Updated feedback_score for {thread_ts}: {current_score:.2f} → {new_score:.2f} ({sign}{delta:.3f})")
        return True
    
    def find_related_threads(
        self,
        project: Optional[str] = None,
        theme: Optional[str] = None,
        product: Optional[str] = None,
        exclude_thread_ts: Optional[str] = None,
        lifecycle_status: Optional[LifecycleStatus] = None,
        n_results: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Find threads related by project, theme, or product.
        Useful for finding threads that might be superseded by a new decision.
        
        Args:
            project: Filter by project name
            theme: Filter by theme
            product: Filter by product
            exclude_thread_ts: Thread to exclude from results
            lifecycle_status: Filter by lifecycle status
            n_results: Maximum number of results
            
        Returns:
            List of dicts with thread_ts, metadata, and document
        """
        # Build where clause
        where_conditions = []
        
        if project and project != "Ad-hoc":
            where_conditions.append({"project": project})
        if theme and theme != "Unclassified":
            where_conditions.append({"theme": theme})
        if product and product != "Unclassified":
            where_conditions.append({"product": product})
        if lifecycle_status:
            where_conditions.append({"lifecycle_status": lifecycle_status.value})
        
        # ChromaDB requires specific format for compound conditions
        where_clause = None
        if len(where_conditions) == 1:
            where_clause = where_conditions[0]
        elif len(where_conditions) > 1:
            where_clause = {"$and": where_conditions}
        
        try:
            if where_clause:
                results = self.collection.get(
                    where=where_clause,
                    limit=n_results
                )
            else:
                results = self.collection.get(limit=n_results)
            
            # Format results
            related = []
            for i, thread_id in enumerate(results.get("ids", [])):
                thread_ts = thread_id.replace("thread_", "")
                
                # Skip excluded thread
                if exclude_thread_ts and thread_ts == exclude_thread_ts:
                    continue
                
                related.append({
                    "thread_ts": thread_ts,
                    "metadata": results["metadatas"][i] if results.get("metadatas") else {},
                    "document": results["documents"][i] if results.get("documents") else ""
                })
            
            return related
            
        except Exception as e:
            print(f"⚠️  Error finding related threads: {e}")
            return []
    
    def get_threads_by_timerange(
        self,
        start_ts: Optional[float] = None,
        end_ts: Optional[float] = None,
        lifecycle_status: Optional[LifecycleStatus] = None
    ) -> List[Dict[str, Any]]:
        """
        Get threads within a time range.
        Useful for consolidation pipeline to get recent threads.
        
        Args:
            start_ts: Start timestamp (Unix timestamp)
            end_ts: End timestamp (Unix timestamp)
            lifecycle_status: Optional filter by lifecycle status
            
        Returns:
            List of threads with metadata
        """
        # Get all threads (ChromaDB doesn't support range queries on numeric fields well)
        where_clause = None
        if lifecycle_status:
            where_clause = {"lifecycle_status": lifecycle_status.value}
        
        try:
            if where_clause:
                results = self.collection.get(where=where_clause)
            else:
                results = self.collection.get()
            
            # Filter by time range in Python
            threads = []
            for i, thread_id in enumerate(results.get("ids", [])):
                meta = results["metadatas"][i] if results.get("metadatas") else {}
                thread_ts = meta.get("thread_ts", "")
                
                if thread_ts:
                    try:
                        ts_float = float(thread_ts)
                        # Apply time range filter
                        if start_ts and ts_float < start_ts:
                            continue
                        if end_ts and ts_float > end_ts:
                            continue
                        
                        threads.append({
                            "thread_ts": thread_ts,
                            "metadata": meta,
                            "document": results["documents"][i] if results.get("documents") else ""
                        })
                    except (ValueError, TypeError):
                        continue
            
            # Sort by timestamp descending (most recent first)
            threads.sort(key=lambda x: float(x["thread_ts"]), reverse=True)
            return threads
            
        except Exception as e:
            print(f"⚠️  Error getting threads by timerange: {e}")
            return []
    
    def query_threads(
        self,
        query: str,
        n_results: int = 10,
        retrieval_config: Optional[dict] = None,
        include_deprecated: bool = False
    ) -> str:
        """
        Query threads and return formatted context string with recency weighting.
        
        Enhanced with lifecycle filtering:
        - By default, filters out Deprecated threads
        - Down-ranks threads that are older when superseding threads exist
        - Set include_deprecated=True to include historical/deprecated threads
        
        Args:
            query: Search query string
            n_results: Number of results to retrieve
            retrieval_config: Optional dict with retrieval config (weights, curation)
            include_deprecated: If True, include deprecated threads (for history queries)
            
        Returns:
            Formatted context string from retrieved threads
        """
        # Clean the query
        cleaned_query = clean_query(query)
        
        # Check if query is asking for history (include deprecated)
        history_keywords = ["previous", "old", "historical", "before", "was", "used to", "originally"]
        if any(kw in query.lower() for kw in history_keywords):
            include_deprecated = True
        
        # Query ChromaDB (request extra results to allow for filtering)
        query_multiplier = 3 if not include_deprecated else 2
        query_results = self.collection.query(
            query_texts=[cleaned_query],
            n_results=n_results * query_multiplier
        )
        
        # Extract documents and metadatas
        retrieved_docs = query_results.get("documents", [[]])[0] if query_results.get("documents") else []
        metadatas = query_results.get("metadatas", [[]])[0] if query_results.get("metadatas") else []
        
        # Filter deprecated threads unless explicitly requested
        # NOTE: Complex ranking (recency, priority, feedback, lifecycle penalties) is now
        # handled by FreshnessRanker in the main retrieval pipeline. This method is a
        # simple convenience method for debugging/inspection.
        if metadatas and len(retrieved_docs) > 0:
            filtered_docs = []
            for doc, meta in zip(retrieved_docs, metadatas):
                lifecycle_status = meta.get("lifecycle_status", LifecycleStatus.ACTIVE.value)
                if not include_deprecated and lifecycle_status == LifecycleStatus.DEPRECATED.value:
                    continue
                filtered_docs.append(doc)
            retrieved_docs = filtered_docs[:n_results]
        else:
            retrieved_docs = retrieved_docs[:n_results]
        
        # Limit documents to prevent context overflow
        limited_docs = _limit_retrieved_docs(retrieved_docs, max_docs=n_results, max_total_length=6000)
        
        # Build context from retrieved documents
        context = "\n\n".join(limited_docs) if limited_docs else "No relevant context found."
        
        # Truncate context if needed
        context = _truncate_context(context, max_length=8000)
        
        return context
    
    def upsert_daily_insight(self, insight: DailyInsight) -> None:
        """
        Upsert a DailyInsight document into the vector database.
        Used by the consolidation pipeline to store synthesized insights.
        
        Args:
            insight: DailyInsight model instance to store
        """
        # Generate unique ID for the insight
        insight_id = f"insight_{insight.date}_{insight.theme.replace(' ', '_').lower()}"
        
        # Build document text for embedding
        document_text = f"""Daily Insight: {insight.title}
Date: {insight.date}
Theme: {insight.theme}
{f"Product: {insight.product}" if insight.product else ""}

Summary:
{insight.summary}

{f"Key Decisions: {'; '.join(insight.key_decisions)}" if insight.key_decisions else ""}
{f"Open Questions: {'; '.join(insight.open_questions)}" if insight.open_questions else ""}
"""
        
        # Build metadata
        metadata = {
            "type": "daily_insight",
            "date": insight.date,
            "theme": insight.theme,
            "product": insight.product or "",
            "title": insight.title,
            "source_thread_count": len(insight.source_thread_ids),
            "source_thread_ids": ",".join(insight.source_thread_ids),
            "lifecycle_status": LifecycleStatus.ACTIVE.value,
            "last_updated": datetime.now().isoformat()
        }
        
        # Upsert into ChromaDB
        self.collection.upsert(
            ids=[insight_id],
            documents=[document_text],
            metadatas=[metadata]
        )
        
        print(f"📊 Stored daily insight: {insight.title} ({insight.date})")
    
    # =========================================================================
    # Atomic Memory Methods (Phase 1 & 2 Enhancement)
    # =========================================================================
    
    def upsert_memory(self, memory: AtomicMemory) -> None:
        """
        Store an atomic memory in the memory collection.
        
        Args:
            memory: AtomicMemory instance to store
        """
        metadata = {
            "source_thread_ts": memory.source_thread_ts,
            "chunk_index": memory.chunk_index,
            "entities": ",".join(memory.entities),
            "relation_type": memory.relation_type.value,
            "related_memory_ids": ",".join(memory.related_memory_ids),
            "is_latest": memory.is_latest,
            "confidence": memory.confidence,
            "created_at": memory.created_at.isoformat(),
        }
        
        # Add temporal metadata if present
        if memory.temporal:
            metadata["document_date"] = memory.temporal.document_date.isoformat()
            metadata["event_dates"] = ",".join(
                d.isoformat() for d in memory.temporal.event_dates
            )
            metadata["is_future_event"] = memory.temporal.is_future_event
            metadata["temporal_refs"] = ",".join(memory.temporal.temporal_references)
        
        self.memory_collection.upsert(
            ids=[memory.id],
            documents=[memory.fact],
            metadatas=[metadata]
        )
    
    def upsert_memories_batch(self, memories: List[AtomicMemory]) -> None:
        """Batch upsert multiple memories."""
        if not memories:
            return
        
        ids = []
        documents = []
        metadatas = []
        
        for memory in memories:
            ids.append(memory.id)
            documents.append(memory.fact)
            
            meta = {
                "source_thread_ts": memory.source_thread_ts,
                "chunk_index": memory.chunk_index,
                "entities": ",".join(memory.entities),
                "relation_type": memory.relation_type.value,
                "related_memory_ids": ",".join(memory.related_memory_ids),
                "is_latest": memory.is_latest,
                "confidence": memory.confidence,
                "created_at": memory.created_at.isoformat(),
            }
            
            if memory.temporal:
                meta["document_date"] = memory.temporal.document_date.isoformat()
                meta["event_dates"] = ",".join(
                    d.isoformat() for d in memory.temporal.event_dates
                )
                meta["is_future_event"] = memory.temporal.is_future_event
                meta["temporal_refs"] = ",".join(memory.temporal.temporal_references)
            
            metadatas.append(meta)
        
        self.memory_collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas
        )
    
    def query_memories(
        self,
        query: str,
        n_results: int = 10,
        only_latest: bool = True,
        include_source_chunks: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Query atomic memories with optional source chunk injection.
        
        This implements hybrid search:
        1. Search memories (atomic facts) for precision
        2. Inject source chunks for detail
        
        Args:
            query: Search query
            n_results: Number of memories to return
            only_latest: Filter to only latest versions (ignore superseded)
            include_source_chunks: Whether to fetch source thread chunks
            
        Returns:
            List of dicts with memory and optional source_chunk
        """
        cleaned_query = clean_query(query)
        
        # Build where clause
        where_clause = None
        if only_latest:
            where_clause = {"is_latest": True}
        
        # Query memory collection
        try:
            results = self.memory_collection.query(
                query_texts=[cleaned_query],
                n_results=n_results * 2,  # Over-fetch to allow filtering
                where=where_clause
            )
        except Exception as e:
            print(f"⚠️ Memory query failed: {e}")
            return []
        
        memories = []
        seen_facts = set()
        
        docs = results.get("documents", [[]])[0] if results.get("documents") else []
        metas = results.get("metadatas", [[]])[0] if results.get("metadatas") else []
        dists = results.get("distances", [[]])[0] if results.get("distances") else []
        ids = results.get("ids", [[]])[0] if results.get("ids") else []
        
        # Handle empty results gracefully
        if not docs or not metas or not dists or not ids:
            print(f"ℹ️ No memories found for query: {cleaned_query[:50]}...")
            return []
        
        for i, (doc, meta, dist, mem_id) in enumerate(zip(docs, metas, dists, ids)):
            # Dedupe similar facts
            if doc in seen_facts:
                continue
            seen_facts.add(doc)
            
            memory_data = {
                "id": mem_id,
                "fact": doc,
                "metadata": meta,
                "distance": dist,
                "similarity": max(0.0, 1.0 - dist / 2.0),
            }
            
            # Optionally fetch source chunk from main collection
            if include_source_chunks:
                source_ts = meta.get("source_thread_ts")
                if source_ts:
                    thread_id = f"thread_{source_ts}"
                    try:
                        thread_results = self.collection.get(ids=[thread_id])
                        if thread_results["documents"]:
                            memory_data["source_chunk"] = thread_results["documents"][0]
                            memory_data["thread_metadata"] = thread_results["metadatas"][0] if thread_results["metadatas"] else {}
                    except Exception:
                        pass  # Source chunk not found, continue without it
            
            memories.append(memory_data)
            
            if len(memories) >= n_results:
                break
        
        return memories
    
    def get_memories_for_thread(self, thread_ts: str) -> List[AtomicMemory]:
        """Get all memories extracted from a specific thread."""
        results = self.memory_collection.get(
            where={"source_thread_ts": thread_ts}
        )
        
        memories = []
        docs = results.get("documents", [])
        metas = results.get("metadatas", [])
        ids = results.get("ids", [])
        
        for i, doc in enumerate(docs):
            meta = metas[i] if i < len(metas) else {}
            mem_id = ids[i] if i < len(ids) else f"mem_{thread_ts}_{i}"
            
            # Parse temporal metadata if present using robust helper
            temporal = None
            if meta.get("document_date"):
                doc_date = parse_datetime_robust(meta["document_date"])
                if doc_date:
                    # Parse event dates using robust helper
                    event_dates = parse_datetime_list_robust(meta.get("event_dates", ""))
                    
                    temporal = TemporalMetadata(
                        document_date=doc_date,
                        event_dates=event_dates,
                        is_future_event=meta.get("is_future_event", False),
                        temporal_references=meta.get("temporal_refs", "").split(",") if meta.get("temporal_refs") else [],
                    )
            
            # Reconstruct AtomicMemory from stored data
            memory = AtomicMemory(
                id=mem_id,
                fact=doc,
                source_thread_ts=meta.get("source_thread_ts", thread_ts),
                source_chunk_content="",
                chunk_index=meta.get("chunk_index", i),
                entities=meta.get("entities", "").split(",") if meta.get("entities") else [],
                temporal=temporal,
                relation_type=MemoryRelation(meta.get("relation_type", "none")),
                related_memory_ids=meta.get("related_memory_ids", "").split(",") if meta.get("related_memory_ids") else [],
                is_latest=meta.get("is_latest", True),
                confidence=float(meta.get("confidence", 1.0)),
            )
            memories.append(memory)
        
        return memories
    
    def get_recent_memories(self, n: int = 50) -> List[AtomicMemory]:
        """Get recent memories for relationship detection context."""
        # ChromaDB doesn't support ORDER BY, so get all and sort in Python
        try:
            results = self.memory_collection.get(limit=n * 3)
        except Exception:
            return []
        
        memories = []
        docs = results.get("documents", [])
        metas = results.get("metadatas", [])
        ids = results.get("ids", [])
        
        for i, doc in enumerate(docs):
            meta = metas[i] if i < len(metas) else {}
            mem_id = ids[i] if i < len(ids) else f"mem_unknown_{i}"
            
            # Parse created_at for sorting using robust helper
            created_at = parse_datetime_robust(meta.get("created_at", ""))
            if not created_at:
                created_at = datetime.now()
            
            memory = AtomicMemory(
                id=mem_id,
                fact=doc,
                source_thread_ts=meta.get("source_thread_ts", ""),
                source_chunk_content="",
                chunk_index=meta.get("chunk_index", 0),
                entities=meta.get("entities", "").split(",") if meta.get("entities") else [],
                relation_type=MemoryRelation(meta.get("relation_type", "none")),
                is_latest=meta.get("is_latest", True),
                created_at=created_at,
            )
            memories.append(memory)
        
        # Sort by created_at descending
        memories.sort(key=lambda m: m.created_at, reverse=True)
        
        return memories[:n]
    
    def get_memory_count(self) -> int:
        """Get the total count of atomic memories."""
        try:
            return self.memory_collection.count()
        except Exception:
            return 0
    
    def regenerate_contexts(self, batch_size: int = 10) -> int:
        """
        Regenerate contextual descriptions for all threads.
        Useful for backfilling existing threads with contextual embeddings.
        
        Args:
            batch_size: Number of threads to process at a time
            
        Returns:
            Number of threads updated
        """
        if not self.context_client:
            print("⚠️ No context_client available for context regeneration")
            return 0
        
        # Get all thread IDs
        all_results = self.collection.get()
        if not all_results["ids"]:
            print("No threads found to regenerate")
            return 0
        
        updated_count = 0
        total = len(all_results["ids"])
        
        print(f"🔄 Regenerating contexts for {total} threads...")
        
        for i, (thread_id, doc, meta) in enumerate(zip(
            all_results["ids"],
            all_results["documents"],
            all_results["metadatas"]
        )):
            # Generate new context
            context = self._generate_thread_context(doc, meta)
            
            if context:
                # Update document with context prepended
                # First, remove old context if present (split on separator)
                if "\n\n---\n\n" in doc:
                    original_doc = doc.split("\n\n---\n\n", 1)[1]
                else:
                    original_doc = doc
                
                new_doc = f"{context}\n\n---\n\n{original_doc}"
                
                # Update metadata
                meta["contextual_description"] = context
                meta["last_updated"] = datetime.now().isoformat()
                
                # Upsert
                self.collection.upsert(
                    ids=[thread_id],
                    documents=[new_doc],
                    metadatas=[meta]
                )
                updated_count += 1
            
            if (i + 1) % batch_size == 0:
                print(f"   Processed {i + 1}/{total} threads...")
        
        print(f"✅ Regenerated contexts for {updated_count} threads")
        return updated_count
