"""Freshness Ranker: Single owner of "which information wins."

ITERATION GUIDE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PROBLEM: Old decision showing instead of new one?
→ Check `_apply_supersession_penalty()` - does lifecycle_status check work?
→ Check `_apply_recency_boost()` - is decay curve too flat?

PROBLEM: Wrong thread winning?
→ Check `compute_ranking_score()` - print the component scores
→ Weights might be off in config

PROBLEM: Feedback not affecting ranking?
→ Check `_apply_feedback_boost()` - is feedback_score being read?

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

This module consolidates ALL ranking logic previously scattered across:
- retrieval.py (_calculate_recency_score, _query_threads_structured)
- vector_store.py (query_threads lifecycle filtering)
- ingestion.py (_is_decision_thread, _detect_supersession)

Now there's ONE place to fix ranking bugs.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, List, Optional


@dataclass
class RankingResult:
    """
    Result of ranking a single document/memory.
    
    Includes component scores for debugging.
    """
    final_score: float
    
    # Component scores (for debugging)
    semantic_score: float = 0.0
    recency_score: float = 0.0
    priority_score: float = 0.0
    feedback_score: float = 0.0
    supersession_penalty: float = 1.0  # 1.0 = no penalty, 0.0 = fully suppressed
    
    # Debug info
    debug_info: Dict[str, Any] = field(default_factory=dict)
    
    def __repr__(self):
        return (
            f"RankingResult(final={self.final_score:.3f}, "
            f"semantic={self.semantic_score:.3f}, recency={self.recency_score:.3f}, "
            f"priority={self.priority_score:.3f}, feedback={self.feedback_score:.3f}, "
            f"supersession_penalty={self.supersession_penalty:.2f})"
        )


class FreshnessRanker:
    """
    Single owner of all ranking logic.
    
    Consolidates:
    - Recency scoring (how old is this?)
    - Supersession handling (is this outdated by a newer version?)
    - Priority weighting (how important is this topic/theme?)
    - Feedback boosting (did users like answers from this source?)
    
    Usage:
        ranker = FreshnessRanker(config)
        score = ranker.compute_ranking_score(
            semantic_similarity=0.85,
            metadata={"thread_ts": "1234...", "lifecycle_status": "Active"},
            document="thread content..."
        )
    """
    
    # =========================================================================
    # CONFIGURATION DEFAULTS
    # These can be overridden via config dict
    # =========================================================================
    
    # Recency settings
    DEFAULT_FULL_WEIGHT_DAYS = 30      # Threads newer than this get full score
    DEFAULT_HALF_LIFE_DAYS = 60        # Score halves every N days after full_weight
    DEFAULT_RECENCY_MIN = 0.3          # Floor for very old threads
    
    # Weight balance
    DEFAULT_SEMANTIC_WEIGHT = 0.7
    DEFAULT_RECENCY_WEIGHT = 0.3
    
    # Supersession penalties
    DEPRECATED_PENALTY = 0.1           # Heavily suppress deprecated threads
    DRAFT_PENALTY = 0.7                # Slightly suppress drafts
    SUPERSEDED_PENALTY = 0.2           # Heavily suppress superseded threads
    
    # Feedback boost settings
    FEEDBACK_NEUTRAL = 0.0             # No feedback = no boost
    FEEDBACK_MAX_BOOST = 2.0           # Maximum feedback_score value
    FEEDBACK_MIN_PENALTY = -1.0        # Maximum negative feedback_score
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize ranker with configuration.
        
        Args:
            config: Combined config dict with 'retrieval', 'priority' sections
        """
        self.config = config or {}
        
        # Parse retrieval config
        retrieval = self.config.get("retrieval", {})
        recency = retrieval.get("recency", {})
        weights = retrieval.get("weights", {})
        
        self.full_weight_days = recency.get("full_weight_days", self.DEFAULT_FULL_WEIGHT_DAYS)
        self.half_life_days = recency.get("half_life_days", self.DEFAULT_HALF_LIFE_DAYS)
        self.recency_min = recency.get("min_weight", self.DEFAULT_RECENCY_MIN)
        
        self.semantic_weight = weights.get("semantic", self.DEFAULT_SEMANTIC_WEIGHT)
        self.recency_weight = weights.get("recency", self.DEFAULT_RECENCY_WEIGHT)
        
        # Parse priority config
        self.priority_config = self.config.get("priority", {})
    
    # =========================================================================
    # MAIN ENTRY POINT
    # =========================================================================
    
    def compute_ranking_score(
        self,
        semantic_similarity: float,
        metadata: Dict[str, Any],
        document: str = "",
        now: Optional[datetime] = None,
    ) -> RankingResult:
        """
        Compute final ranking score for a document.
        
        This is the SINGLE PLACE where all ranking factors are combined.
        
        Args:
            semantic_similarity: Raw similarity from vector search (0-1)
            metadata: Document metadata (thread_ts, lifecycle_status, feedback_score, etc.)
            document: Document text (for content-based priority patterns)
            now: Current time (for testing, defaults to datetime.now())
            
        Returns:
            RankingResult with final score and component breakdown
        """
        now = now or datetime.now()
        
        # 1. Normalize semantic score
        semantic_score = max(0.0, min(1.0, semantic_similarity))
        
        # 2. Calculate recency score
        recency_score = self._apply_recency_boost(metadata, now)
        
        # 3. Calculate priority score
        priority_score = self._apply_priority_weight(metadata, document)
        
        # 4. Calculate feedback score
        feedback_boost = self._apply_feedback_boost(metadata)
        
        # 5. Calculate supersession penalty
        supersession_penalty = self._apply_supersession_penalty(metadata)
        
        # 6. Combine scores
        # Base score: weighted combination of semantic + recency
        base_score = (semantic_score * self.semantic_weight) + (recency_score * self.recency_weight)
        
        # Apply priority multiplier
        prioritized_score = base_score * priority_score
        
        # Apply feedback boost: score * (1 + feedback_score)
        # feedback_score=0 → 1x, feedback_score=1 → 2x, feedback_score=-0.5 → 0.5x
        boosted_score = prioritized_score * (1.0 + feedback_boost)
        
        # Apply supersession penalty (0.0 to 1.0 multiplier)
        final_score = boosted_score * supersession_penalty
        
        return RankingResult(
            final_score=final_score,
            semantic_score=semantic_score,
            recency_score=recency_score,
            priority_score=priority_score,
            feedback_score=feedback_boost,
            supersession_penalty=supersession_penalty,
            debug_info={
                "base_score": base_score,
                "prioritized_score": prioritized_score,
                "boosted_score": boosted_score,
                "thread_ts": metadata.get("thread_ts", ""),
                "lifecycle_status": metadata.get("lifecycle_status", "Active"),
            }
        )
    
    def rank_results(
        self,
        results: List[Dict[str, Any]],
        now: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """
        Rank a list of search results by freshness.
        
        Args:
            results: List of dicts with 'similarity', 'metadata', 'document'
            now: Current time (for testing)
            
        Returns:
            Same list, sorted by ranking score (descending), with 'ranking' added
        """
        now = now or datetime.now()
        
        for result in results:
            ranking = self.compute_ranking_score(
                semantic_similarity=result.get("similarity", 0.0),
                metadata=result.get("metadata", {}),
                document=result.get("document", ""),
                now=now,
            )
            result["ranking"] = ranking
            result["combined_score"] = ranking.final_score
        
        # Sort by final score descending
        results.sort(key=lambda x: x["combined_score"], reverse=True)
        
        return results
    
    # =========================================================================
    # COMPONENT SCORE FUNCTIONS
    # Edit these to change ranking behavior
    # =========================================================================
    
    def _apply_recency_boost(
        self,
        metadata: Dict[str, Any],
        now: datetime,
    ) -> float:
        """
        Calculate recency score based on thread age.
        
        EDIT HERE to change how age affects ranking.
        
        Current logic:
        - Threads < full_weight_days old → 1.0
        - Older threads decay exponentially with half_life_days
        - Floor at recency_min
        """
        thread_ts = metadata.get("thread_ts", "")
        
        if not thread_ts:
            return self.recency_min
        
        try:
            ts_float = float(thread_ts)
            thread_date = datetime.fromtimestamp(ts_float)
            age_days = (now - thread_date).days
            
            if age_days <= self.full_weight_days:
                return 1.0
            
            # Exponential decay after full_weight_days
            decay_days = age_days - self.full_weight_days
            decay_factor = math.pow(0.5, decay_days / self.half_life_days)
            
            return max(self.recency_min, self.recency_min + (1.0 - self.recency_min) * decay_factor)
            
        except (ValueError, OSError, TypeError):
            return self.recency_min
    
    def _apply_supersession_penalty(
        self,
        metadata: Dict[str, Any],
    ) -> float:
        """
        Apply penalty for deprecated/superseded threads.
        
        EDIT HERE to change how supersession affects ranking.
        
        Returns a multiplier (0.0 to 1.0):
        - 1.0 = no penalty (Active threads)
        - 0.1 = heavy penalty (Deprecated threads)
        - 0.2 = heavy penalty (Superseded threads)
        - 0.7 = light penalty (Draft threads)
        """
        lifecycle_status = metadata.get("lifecycle_status", "Active")
        
        if lifecycle_status == "Deprecated":
            return self.DEPRECATED_PENALTY
        
        if lifecycle_status == "Draft":
            return self.DRAFT_PENALTY
        
        # Check if explicitly superseded
        superseded_by = metadata.get("superseded_by", "")
        if superseded_by:
            return self.SUPERSEDED_PENALTY
        
        # Active thread, no penalty
        return 1.0
    
    def _apply_feedback_boost(
        self,
        metadata: Dict[str, Any],
    ) -> float:
        """
        Get feedback boost/penalty from metadata.
        
        EDIT HERE to change how feedback affects ranking.
        
        Returns a value that will be used as: score * (1 + feedback_boost)
        - 0.0 = no change
        - 1.0 = 2x boost
        - -0.5 = 0.5x penalty
        """
        feedback_score = metadata.get("feedback_score", 0.0)
        
        # Ensure it's a float
        try:
            feedback_score = float(feedback_score)
        except (ValueError, TypeError):
            return 0.0
        
        # Clamp to valid range
        return max(self.FEEDBACK_MIN_PENALTY, min(self.FEEDBACK_MAX_BOOST, feedback_score))
    
    def _apply_priority_weight(
        self,
        metadata: Dict[str, Any],
        document: str,
    ) -> float:
        """
        Calculate priority weight based on topic/theme/content.
        
        EDIT HERE to change how priority affects ranking.
        
        Uses priority_config to look up weights for:
        - topic_weights
        - theme_weights
        - product_weights
        - channel_weights
        - content_patterns
        """
        if not self.priority_config:
            return 1.0
        
        weights = []
        default_weight = self.priority_config.get("default_weight", 1.0)
        
        # Topic weight
        topic = metadata.get("topic", "")
        topic_weights = self.priority_config.get("topic_weights", {})
        if topic and topic in topic_weights:
            weights.append(topic_weights[topic])
        
        # Theme weight
        theme = metadata.get("theme", "")
        theme_weights = self.priority_config.get("theme_weights", {})
        if theme and theme in theme_weights:
            weights.append(theme_weights[theme])
        
        # Product weight
        product = metadata.get("product", "")
        product_weights = self.priority_config.get("product_weights", {})
        if product and product in product_weights:
            weights.append(product_weights[product])
        
        # Combine weights
        combination = self.priority_config.get("combination_method", "multiply")
        
        if not weights:
            return default_weight
        
        if combination == "multiply":
            result = default_weight
            for w in weights:
                result *= w
        elif combination == "max":
            result = max(weights)
        elif combination == "average":
            result = sum(weights) / len(weights)
        else:
            result = default_weight
            for w in weights:
                result *= w
        
        # Apply caps
        min_weight = self.priority_config.get("min_weight", 0.5)
        max_weight = self.priority_config.get("max_weight", 3.0)
        
        return max(min_weight, min(max_weight, result))
    
    # =========================================================================
    # DEBUG HELPERS
    # =========================================================================
    
    def explain_ranking(
        self,
        semantic_similarity: float,
        metadata: Dict[str, Any],
        document: str = "",
    ) -> str:
        """
        Generate human-readable explanation of why a result ranked as it did.
        
        Useful for debugging ranking issues.
        """
        result = self.compute_ranking_score(semantic_similarity, metadata, document)
        
        lines = [
            f"=== Ranking Explanation ===",
            f"Thread: {metadata.get('thread_ts', 'unknown')}",
            f"Name: {metadata.get('thread_name', 'unknown')}",
            f"",
            f"Component Scores:",
            f"  Semantic: {result.semantic_score:.3f} (weight: {self.semantic_weight})",
            f"  Recency:  {result.recency_score:.3f} (weight: {self.recency_weight})",
            f"  Priority: {result.priority_score:.3f}",
            f"  Feedback: {result.feedback_score:+.3f}",
            f"  Supersession Penalty: {result.supersession_penalty:.2f}",
            f"",
            f"Calculation:",
            f"  base = ({result.semantic_score:.3f} × {self.semantic_weight}) + ({result.recency_score:.3f} × {self.recency_weight}) = {result.debug_info['base_score']:.3f}",
            f"  prioritized = {result.debug_info['base_score']:.3f} × {result.priority_score:.3f} = {result.debug_info['prioritized_score']:.3f}",
            f"  boosted = {result.debug_info['prioritized_score']:.3f} × (1 + {result.feedback_score:.3f}) = {result.debug_info['boosted_score']:.3f}",
            f"  final = {result.debug_info['boosted_score']:.3f} × {result.supersession_penalty:.2f} = {result.final_score:.3f}",
            f"",
            f"FINAL SCORE: {result.final_score:.3f}",
        ]
        
        return "\n".join(lines)

