"""
Gap checker module for memex-core.
Detects known knowledge gaps and out-of-scope queries before retrieval.
This saves API costs and provides better user experience with targeted responses.
"""

import re
from typing import Optional, Dict, Any, List, Tuple

from .client import GeminiClient
from ..prompts import render_prompt


class GapChecker:
    """
    Checks user queries against known gaps and out-of-scope topics.
    
    Can operate in two modes:
    1. Keyword-based (fast, no API call)
    2. LLM-based (more accurate, uses API call)
    """
    
    def __init__(
        self,
        gaps_config: Dict[str, Any],
        client: Optional[GeminiClient] = None,
        use_llm: bool = False
    ):
        """
        Initialize GapChecker.
        
        Args:
            gaps_config: Gaps configuration dict from gaps.yaml
            client: Optional GeminiClient for LLM-based checking
            use_llm: Whether to use LLM for more accurate gap detection
        """
        self.gaps_config = gaps_config
        self.client = client
        self.use_llm = use_llm and client is not None
        
        # Pre-compile keyword patterns for efficiency
        self._known_gaps = gaps_config.get("known_gaps", [])
        self._out_of_scope = gaps_config.get("out_of_scope", [])
        self._ambiguity_config = gaps_config.get("ambiguity", {})
        self._staleness_config = gaps_config.get("staleness", {})
    
    def _keyword_match(self, query: str, keywords: List[str]) -> bool:
        """
        Check if query contains any of the keywords.
        
        Args:
            query: User query (lowercased)
            keywords: List of keywords to check
            
        Returns:
            True if any keyword matches
        """
        query_lower = query.lower()
        for keyword in keywords:
            # Use word boundary matching for short keywords
            if len(keyword) <= 3:
                pattern = rf'\b{re.escape(keyword)}\b'
                if re.search(pattern, query_lower):
                    return True
            else:
                if keyword.lower() in query_lower:
                    return True
        return False
    
    def check_known_gaps(self, query: str) -> Optional[Dict[str, str]]:
        """
        Check if query matches a known knowledge gap.
        
        Args:
            query: User query
            
        Returns:
            Dict with 'topic' and 'response' if matched, None otherwise
        """
        for gap in self._known_gaps:
            keywords = gap.get("keywords", [])
            if self._keyword_match(query, keywords):
                return {
                    "topic": gap.get("topic", "Unknown"),
                    "response": gap.get("response", "I don't have information on this topic.")
                }
        return None
    
    def check_out_of_scope(self, query: str) -> Optional[Dict[str, str]]:
        """
        Check if query is out of scope for this bot.
        
        Args:
            query: User query
            
        Returns:
            Dict with 'topic' and 'response' if matched, None otherwise
        """
        for scope in self._out_of_scope:
            keywords = scope.get("keywords", [])
            if self._keyword_match(query, keywords):
                return {
                    "topic": scope.get("topic", "Unknown"),
                    "response": scope.get("response", "This topic is outside my area of expertise.")
                }
        return None
    
    def check_ambiguity(self, query: str) -> Optional[str]:
        """
        Check if query is too short or vague to answer well.
        
        Args:
            query: User query
            
        Returns:
            Clarification prompt if query is ambiguous, None otherwise
        """
        min_length = self._ambiguity_config.get("min_query_length", 5)
        if len(query.strip()) < min_length:
            return self._ambiguity_config.get(
                "clarification_prompt",
                "Could you be more specific about what you're looking for?"
            )
        return None
    
    def check_query(self, query: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Perform all gap checks on a query.
        
        Args:
            query: User query
            
        Returns:
            Tuple of (should_proceed, response_if_blocked, block_reason)
            - should_proceed: True if query should go to retrieval
            - response_if_blocked: Pre-defined response if blocked
            - block_reason: Type of block (known_gap, out_of_scope, ambiguous, or None)
        """
        # Check ambiguity first (cheapest check)
        ambiguity_response = self.check_ambiguity(query)
        if ambiguity_response:
            return (False, ambiguity_response, "ambiguous")
        
        # Check known gaps
        gap_match = self.check_known_gaps(query)
        if gap_match:
            return (False, gap_match["response"], f"known_gap:{gap_match['topic']}")
        
        # Check out of scope
        scope_match = self.check_out_of_scope(query)
        if scope_match:
            return (False, scope_match["response"], f"out_of_scope:{scope_match['topic']}")
        
        # No blocks found
        return (True, None, None)
    
    def check_query_with_llm(self, query: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Use LLM to check if query falls into gaps (more accurate but slower).
        
        Falls back to keyword-based checking if LLM is not available.
        
        Args:
            query: User query
            
        Returns:
            Same as check_query()
        """
        if not self.use_llm or not self.client:
            return self.check_query(query)
        
        # First do quick ambiguity check
        ambiguity_response = self.check_ambiguity(query)
        if ambiguity_response:
            return (False, ambiguity_response, "ambiguous")
        
        try:
            # Use LLM for more accurate gap detection
            prompt = render_prompt(
                "gap_check",
                query=query,
                known_gaps=self._known_gaps,
                out_of_scope=self._out_of_scope
            )
            
            response = self.client.call_with_retry(prompt)
            
            # Parse response
            import json
            match = re.search(r'<result>\s*({.*?})\s*</result>', response, re.DOTALL)
            if match:
                result = json.loads(match.group(1))
                if result.get("matched"):
                    gap_type = result.get("type", "unknown")
                    topic = result.get("topic", "Unknown")
                    
                    # Find the matching response
                    if gap_type == "known_gap":
                        for gap in self._known_gaps:
                            if gap.get("topic") == topic:
                                return (False, gap.get("response"), f"known_gap:{topic}")
                    elif gap_type == "out_of_scope":
                        for scope in self._out_of_scope:
                            if scope.get("topic") == topic:
                                return (False, scope.get("response"), f"out_of_scope:{topic}")
            
            # LLM said no match
            return (True, None, None)
            
        except Exception as e:
            print(f"⚠️ LLM gap check failed, falling back to keyword check: {e}")
            return self.check_query(query)
    
    def get_staleness_warning(self, age_days: int) -> Optional[str]:
        """
        Get staleness warning if results are too old.
        
        Args:
            age_days: Age of the best matching result in days
            
        Returns:
            Warning message if stale, None otherwise
        """
        warn_after = self._staleness_config.get("warn_after_days", 30)
        if age_days > warn_after:
            template = self._staleness_config.get(
                "warning_template",
                "Note: The most relevant information I found is from {age} ago. Things may have changed since then."
            )
            # Format age nicely
            if age_days >= 365:
                age_str = f"{age_days // 365} year(s)"
            elif age_days >= 30:
                age_str = f"{age_days // 30} month(s)"
            else:
                age_str = f"{age_days} days"
            
            return template.format(age=age_str)
        
        return None

