"""
Retrieval pipeline for memex-core.
Orchestrates the "Answer" workflow: query -> retrieve -> rerank -> generate.
Enhanced with LLM-based re-ranking for improved precision.
Enhanced with configurable retrieval parameters and confidence scoring.
Enhanced with priority weights for thread importance ranking.
Enhanced with hybrid retrieval: search memories for precision, inject chunks for detail.

ITERATION GUIDE:
- Ranking logic is now centralized in `ranking/freshness.py`
- To change how recency/priority/feedback/supersession affect ranking, edit FreshnessRanker
- This file focuses on retrieval orchestration, not scoring logic
"""

import re
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

from ..models import RoleDefinition, AtomicMemory
from ..ai.generator import AnswerGenerator
from ..ai.client import GeminiClient
from ..storage.vector_store import ChromaVectorStore
from ..prompts import render_prompt
from ..ranking import FreshnessRanker


class RetrievalPipeline:
    """
    Pipeline for answering questions using RAG (Retrieval-Augmented Generation).
    Orchestrates the workflow: query vector store -> rerank -> generate answer.
    
    Enhanced with:
    - Configurable retrieval parameters (weights, limits, decay curves)
    - LLM-based re-ranking for improved precision
    - Confidence scoring for retrieved results
    - Output configuration passthrough
    """
    
    def __init__(
        self,
        vector_store: ChromaVectorStore,
        generator: AnswerGenerator,
        reranker_client: Optional[GeminiClient] = None,
        priority_config: Optional[Dict[str, Any]] = None,
        retrieval_config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize RetrievalPipeline.
        
        Args:
            vector_store: ChromaVectorStore instance for querying threads
            generator: AnswerGenerator instance for generating answers
            reranker_client: Optional GeminiClient for LLM-based re-ranking
            priority_config: Optional priority configuration for thread weighting
            retrieval_config: Optional retrieval configuration (weights, recency, etc.)
        """
        self.vector_store = vector_store
        self.generator = generator
        self.reranker_client = reranker_client
        self.priority_config = priority_config or {}
        self.retrieval_config = retrieval_config or {}
        
        # Initialize the FreshnessRanker - single owner of ranking logic
        self.ranker = FreshnessRanker({
            "retrieval": self.retrieval_config,
            "priority": self.priority_config,
        })
    
    def _get_config_value(
        self,
        retrieval_config: Optional[Dict[str, Any]],
        *keys,
        default: Any = None
    ) -> Any:
        """
        Get a nested config value with fallback to default.
        
        Args:
            retrieval_config: Config dict
            *keys: Nested keys to traverse
            default: Default value if not found
            
        Returns:
            Config value or default
        """
        if not retrieval_config:
            return default
        
        value = retrieval_config
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return default
            if value is None:
                return default
        return value
    
    def _rerank_results(
        self,
        query: str,
        results: List[Dict[str, Any]],
        retrieval_config: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Use LLM to rerank retrieved documents for better precision.
        
        Args:
            query: The user's original query
            results: List of retrieved results with 'document' and 'metadata' keys
            retrieval_config: Optional retrieval configuration
            
        Returns:
            Reranked list of results
        """
        # Get config values
        top_k = self._get_config_value(
            retrieval_config, "reranker", "top_k", default=5
        )
        reranker_enabled = self._get_config_value(
            retrieval_config, "reranker", "enabled", default=True
        )
        
        if not reranker_enabled or not self.reranker_client or len(results) <= top_k:
            return results[:top_k]
        
        # Build document summaries for reranking
        documents = []
        for i, result in enumerate(results):
            summary = result.get("metadata", {}).get("summary", "")
            if not summary or summary == "Pending":
                summary = result.get("document", "")[:200]
            
            thread_name = result.get("metadata", {}).get("thread_name", "")
            documents.append({
                "thread_name": thread_name if thread_name != "Pending" else "",
                "summary": summary
            })
        
        try:
            # Use externalized prompt template
            prompt = render_prompt(
                "rerank",
                query=query,
                documents=documents,
                top_k=top_k
            )
            
            response = self.reranker_client.call_with_retry(prompt)
            
            # Extract indices from response
            match = re.search(r'<indices>([\d,\s]+)</indices>', response)
            if match:
                indices_str = match.group(1)
                indices = [
                    int(i.strip()) 
                    for i in indices_str.split(',') 
                    if i.strip().isdigit()
                ]
                # Filter valid indices and limit to top_k
                indices = [i for i in indices if i < len(results)][:top_k]
                
                if indices:
                    return [results[i] for i in indices]
            
            # If parsing fails, fall back to simple numeric extraction
            numbers = re.findall(r'\d+', response)
            if numbers:
                indices = [int(n) for n in numbers if int(n) < len(results)][:top_k]
                if indices:
                    return [results[i] for i in indices]
                    
        except Exception as e:
            print(f"⚠️ Reranking failed, using original order: {e}")
        
        return results[:top_k]
    
    def _query_threads_structured(
        self,
        query: str,
        n_results: int = 10,
        retrieval_config: Optional[Dict[str, Any]] = None
    ) -> Tuple[List[Dict[str, Any]], float]:
        """
        Query threads and return structured results with confidence score.
        
        Args:
            query: Search query string
            n_results: Number of results to retrieve
            retrieval_config: Optional dict with retrieval config
            
        Returns:
            Tuple of (list of result dicts, confidence score)
        """
        from ..utils import clean_query
        
        # Clean the query
        cleaned_query = clean_query(query)
        
        # Get over-retrieval factor
        over_retrieval = self._get_config_value(
            retrieval_config, "retrieval", "over_retrieval_factor", default=3
        )
        
        # Query ChromaDB
        query_results = self.vector_store.collection.query(
            query_texts=[cleaned_query],
            n_results=n_results * over_retrieval
        )
        
        # Extract and structure results
        documents = query_results.get("documents", [[]])[0] if query_results.get("documents") else []
        metadatas = query_results.get("metadatas", [[]])[0] if query_results.get("metadatas") else []
        distances = query_results.get("distances", [[]])[0] if query_results.get("distances") else []
        
        results = []
        best_similarity = 0.0
        now = datetime.now()
        
        for doc, meta, dist in zip(documents, metadatas, distances):
            # Calculate normalized similarity from distance
            normalized_similarity = max(0.0, min(1.0, 1.0 - (dist / 2.0)))
            
            # Use FreshnessRanker for all ranking logic (recency, priority, feedback, supersession)
            ranking = self.ranker.compute_ranking_score(
                semantic_similarity=normalized_similarity,
                metadata=meta,
                document=doc,
                now=now,
            )
            
            # Track best similarity for confidence
            if normalized_similarity > best_similarity:
                best_similarity = normalized_similarity
            
            results.append({
                "document": doc,
                "metadata": meta,
                "distance": dist,
                "similarity": normalized_similarity,
                "recency_score": ranking.recency_score,
                "priority_weight": ranking.priority_score,
                "feedback_score": ranking.feedback_score,
                "combined_score": ranking.final_score,
                "ranking": ranking,  # Include full ranking for debugging
            })
        
        # Sort by combined score (already computed by ranker)
        results.sort(key=lambda x: x["combined_score"], reverse=True)
        
        # Confidence is the best similarity score
        confidence = best_similarity
        
        return results[:n_results], confidence
    
    def _get_result_age_days(self, results: List[Dict[str, Any]]) -> int:
        """
        Get the age in days of the best (first) result.
        
        Args:
            results: List of result dicts
            
        Returns:
            Age in days, or 0 if unknown
        """
        if not results:
            return 0
        
        thread_ts = results[0].get("metadata", {}).get("thread_ts", "")
        if not thread_ts:
            return 0
        
        try:
            ts_float = float(thread_ts)
            thread_date = datetime.fromtimestamp(ts_float)
            return (datetime.now() - thread_date).days
        except (ValueError, OSError):
            return 0
    
    def answer_question(
        self,
        query: str,
        role_def: RoleDefinition,
        behavior_config: Optional[Dict[str, Any]] = None,
        retrieval_config: Optional[Dict[str, Any]] = None,
        output_config: Optional[Dict[str, Any]] = None,
        n_results: int = 10
    ) -> str:
        """
        Answer a question using hybrid RAG (memories + threads).
        
        Uses atomic memories for precision, falls back to thread search if
        no memories exist yet.
        
        Args:
            query: User's question
            role_def: RoleDefinition for answer generation context
            behavior_config: Optional behavior configuration for generator
            retrieval_config: Optional retrieval configuration (weights, etc.)
            output_config: Optional output configuration (length, format, etc.)
            n_results: Number of results to use for answer generation
            
        Returns:
            Generated answer string
        """
        result = self.answer_question_with_sources(
            query=query,
            role_def=role_def,
            behavior_config=behavior_config,
            retrieval_config=retrieval_config,
            output_config=output_config,
            n_results=n_results,
        )
        return result["answer"]
    
    def answer_question_with_sources(
        self,
        query: str,
        role_def: RoleDefinition,
        behavior_config: Optional[Dict[str, Any]] = None,
        retrieval_config: Optional[Dict[str, Any]] = None,
        output_config: Optional[Dict[str, Any]] = None,
        n_results: int = 10
    ) -> Dict[str, Any]:
        """
        Answer a question using hybrid retrieval and return source metadata.
        
        Uses atomic memories for precision when available, with automatic
        fallback to thread search. Returns structured response for feedback tracking.
        
        Args:
            query: User's question
            role_def: RoleDefinition for answer generation context
            behavior_config: Optional behavior configuration for generator
            retrieval_config: Optional retrieval configuration (weights, etc.)
            output_config: Optional output configuration (length, format, etc.)
            n_results: Number of results to use for answer generation
            
        Returns:
            Dict with answer, source_thread_ids, confidence, source_count, memories_used
        """
        # Override n_results from config if provided
        n_results = self._get_config_value(
            retrieval_config, "retrieval", "default_n_results", default=n_results
        )
        
        # Use hybrid retrieval (memories + fallback to threads)
        results = self.hybrid_retrieve(
            query=query,
            n_results=n_results,
            retrieval_config=retrieval_config,
        )
        
        if not results:
            return {
                "answer": "I couldn't find any relevant information.",
                "source_thread_ids": [],
                "confidence": 0.0,
                "source_count": 0,
                "memories_used": 0,
            }
        
        # Build context combining memories and chunks
        context_parts = []
        source_thread_ids = []
        
        for result in results:
            memory_fact = result.get("memory_fact", "")
            source_chunk = result.get("source_chunk", "")
            thread_name = result.get("thread_metadata", {}).get("thread_name", "")
            
            # Format: Memory fact first (high signal), then context (detail)
            if memory_fact:
                if thread_name and thread_name != "Pending":
                    context_parts.append(f"**{thread_name}**\nKey fact: {memory_fact}")
                else:
                    context_parts.append(f"Key fact: {memory_fact}")
                
                # Add truncated source context if available
                if source_chunk and len(source_chunk) > 100:
                    truncated = source_chunk[:500] + "..." if len(source_chunk) > 500 else source_chunk
                    context_parts.append(f"Context: {truncated}")
            else:
                # Fallback: just use source chunk
                if thread_name and thread_name != "Pending":
                    context_parts.append(f"### {thread_name}\n{source_chunk[:800]}")
                else:
                    context_parts.append(source_chunk[:800] if source_chunk else "")
            
            if result.get("source_thread_ts"):
                source_thread_ids.append(result["source_thread_ts"])
        
        context = "\n\n---\n\n".join(context_parts) if context_parts else "No relevant context found."
        
        # Calculate confidence from best result
        confidence = results[0]["similarity"] if results else 0.0
        
        # Generate answer
        answer = self.generator.generate_answer(
            context=context,
            question=query,
            role_def=role_def,
            behavior_config=behavior_config,
            output_config=output_config,
            confidence_score=confidence,
        )
        
        return {
            "answer": answer,
            "source_thread_ids": list(set(source_thread_ids)),
            "confidence": confidence,
            "source_count": len(results),
            "memories_used": sum(1 for r in results if r.get("memory_fact")),
        }
    
    def retrieve_context(
        self,
        query: str,
        retrieval_config: Optional[Dict[str, Any]] = None,
        n_results: int = 10
    ) -> str:
        """
        Retrieve context without generating an answer.
        Useful for debugging or when you want to inspect retrieved documents.
        
        Args:
            query: Search query
            retrieval_config: Optional retrieval configuration (weights, etc.)
            n_results: Number of results to retrieve
            
        Returns:
            Retrieved context string
        """
        return self.vector_store.query_threads(
            query,
            n_results=n_results,
            retrieval_config=retrieval_config
        )
    
    def retrieve_structured(
        self,
        query: str,
        retrieval_config: Optional[Dict[str, Any]] = None,
        n_results: int = 10,
        rerank: bool = True
    ) -> Tuple[List[Dict[str, Any]], float]:
        """
        Retrieve structured results with optional reranking and confidence score.
        Useful for debugging, evaluation, or custom processing.
        
        Args:
            query: Search query
            retrieval_config: Optional retrieval configuration
            n_results: Number of results to retrieve
            rerank: Whether to apply LLM reranking (if reranker available)
            
        Returns:
            Tuple of (list of result dicts, confidence score)
        """
        reranker_enabled = self._get_config_value(
            retrieval_config, "reranker", "enabled", default=True
        )
        reranker_candidates = self._get_config_value(
            retrieval_config, "reranker", "candidates", default=30
        )
        
        # Over-retrieve if reranking
        should_rerank = rerank and reranker_enabled and self.reranker_client
        candidate_count = reranker_candidates if should_rerank else n_results
        
        candidates, confidence = self._query_threads_structured(
            query,
            n_results=candidate_count,
            retrieval_config=retrieval_config
        )
        
        if should_rerank and len(candidates) > n_results:
            return self._rerank_results(query, candidates, retrieval_config), confidence
        
        return candidates[:n_results], confidence
    
    # =========================================================================
    # Hybrid Retrieval Methods (Phase 2 Enhancement)
    # =========================================================================
    
    def hybrid_retrieve(
        self,
        query: str,
        n_results: int = 10,
        retrieval_config: Optional[Dict[str, Any]] = None,
        only_latest: bool = True,
        rerank: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Hybrid retrieval: Search memories for precision, inject chunks for detail.
        
        Strategy:
        1. Query atomic memories (high signal, low noise)
        2. For each memory hit, fetch the source thread chunk
        3. Optionally rerank using LLM for higher quality
        4. Return both memory fact and source context
        
        This addresses the core RAG failure: "chunks lack context when isolated"
        
        Args:
            query: Search query
            n_results: Number of results
            retrieval_config: Optional config for weights, etc.
            only_latest: Filter out superseded memories
            rerank: If True and reranker_client available, apply LLM reranking
            
        Returns:
            List of results with both memory and source_chunk
        """
        # Check if memory collection has content
        try:
            memory_count = self.vector_store.get_memory_count()
            if memory_count == 0:
                # No memories yet, fall back to thread search
                return self._fallback_thread_search(query, n_results, retrieval_config)
            
            memory_results = self.vector_store.query_memories(
                query=query,
                n_results=n_results,
                only_latest=only_latest,
                include_source_chunks=True,
            )
        except Exception as e:
            print(f"⚠️ Memory query failed, falling back to thread search: {e}")
            return self._fallback_thread_search(query, n_results, retrieval_config)
        
        if not memory_results:
            # Fallback if no memories found
            return self._fallback_thread_search(query, n_results, retrieval_config)
        
        # Enhance results with ranking using FreshnessRanker
        enhanced_results = []
        now = datetime.now()
        
        for mem_result in memory_results:
            # Get thread metadata for ranking
            thread_meta = mem_result.get("thread_metadata", {})
            source_ts = mem_result.get("metadata", {}).get("source_thread_ts", "")
            
            # Build metadata for ranker (combine thread metadata with source_thread_ts)
            ranking_meta = dict(thread_meta)
            ranking_meta["thread_ts"] = source_ts
            
            # Use FreshnessRanker for all ranking logic
            ranking = self.ranker.compute_ranking_score(
                semantic_similarity=mem_result["similarity"],
                metadata=ranking_meta,
                document=mem_result.get("source_chunk", ""),
                now=now,
            )
            
            enhanced_results.append({
                "memory_fact": mem_result["fact"],
                "source_chunk": mem_result.get("source_chunk", ""),
                "thread_metadata": thread_meta,
                "memory_metadata": mem_result["metadata"],
                "similarity": mem_result["similarity"],
                "recency_score": ranking.recency_score,
                "priority_weight": ranking.priority_score,
                "combined_score": ranking.final_score,
                "source_thread_ts": source_ts,
                "ranking": ranking,  # Include full ranking for debugging
            })
        
        # Sort by combined score
        enhanced_results.sort(key=lambda x: x["combined_score"], reverse=True)
        
        # Apply optional LLM reranking for higher quality results
        if rerank and self.reranker_client and len(enhanced_results) > n_results:
            reranker_enabled = self._get_config_value(
                retrieval_config, "reranker", "enabled", default=True
            )
            if reranker_enabled:
                # Convert to format expected by _rerank_results
                rerank_input = [
                    {
                        "document": r.get("source_chunk", r.get("memory_fact", "")),
                        "metadata": {
                            "summary": r.get("memory_fact", ""),
                            "thread_name": r.get("thread_metadata", {}).get("thread_name", ""),
                        }
                    }
                    for r in enhanced_results
                ]
                
                reranked = self._rerank_results(query, rerank_input, retrieval_config)
                
                # Map reranked indices back to enhanced_results
                if reranked:
                    reranked_results = []
                    for rerank_result in reranked:
                        # Find matching enhanced result
                        for enhanced in enhanced_results:
                            if enhanced.get("memory_fact", "") == rerank_result.get("metadata", {}).get("summary", ""):
                                reranked_results.append(enhanced)
                                break
                    
                    if reranked_results:
                        return reranked_results[:n_results]
        
        return enhanced_results[:n_results]
    
    def _build_hybrid_context(
        self,
        results: List[Dict[str, Any]],
    ) -> Tuple[str, List[str]]:
        """
        Build context string from hybrid retrieval results.
        
        Args:
            results: List of hybrid retrieval results
            
        Returns:
            Tuple of (context string, list of source thread IDs)
        """
        context_parts = []
        source_thread_ids = []
        
        for result in results:
            memory_fact = result.get("memory_fact", "")
            source_chunk = result.get("source_chunk", "")
            thread_name = result.get("thread_metadata", {}).get("thread_name", "")
            
            if memory_fact:
                if thread_name and thread_name != "Pending":
                    context_parts.append(f"**{thread_name}**\nKey fact: {memory_fact}")
                else:
                    context_parts.append(f"Key fact: {memory_fact}")
                
                if source_chunk and len(source_chunk) > 100:
                    truncated = source_chunk[:500] + "..." if len(source_chunk) > 500 else source_chunk
                    context_parts.append(f"Context: {truncated}")
            else:
                if thread_name and thread_name != "Pending":
                    context_parts.append(f"### {thread_name}\n{source_chunk[:800]}")
                else:
                    context_parts.append(source_chunk[:800] if source_chunk else "")
            
            if result.get("source_thread_ts"):
                source_thread_ids.append(result["source_thread_ts"])
        
        context = "\n\n---\n\n".join(context_parts) if context_parts else "No relevant context found."
        return context, source_thread_ids
    
    def _fallback_thread_search(
        self,
        query: str,
        n_results: int,
        retrieval_config: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Fallback to traditional thread-based search."""
        candidates, confidence = self._query_threads_structured(
            query, n_results, retrieval_config
        )
        
        # Convert to hybrid format
        return [
            {
                "memory_fact": "",  # No atomic memory available
                "source_chunk": c.get("document", ""),
                "thread_metadata": c.get("metadata", {}),
                "memory_metadata": {},
                "similarity": c.get("similarity", 0),
                "recency_score": c.get("recency_score", 0.5),
                "priority_weight": c.get("priority_weight", 1.0),
                "combined_score": c.get("combined_score", 0),
                "source_thread_ts": c.get("metadata", {}).get("thread_ts", ""),
            }
            for c in candidates
        ]
