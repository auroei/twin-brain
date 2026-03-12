"""Ranking module for memex-core.

Single owner of "which information wins" during retrieval.

ITERATION GUIDE:
- To change how recency affects ranking: edit `freshness.py`
- To change how supersession affects ranking: edit `freshness.py`  
- To change priority weights: edit config, not code
- To change feedback boost: edit `freshness.py`

All ranking adjustments flow through this module. If old decisions
are appearing instead of new ones, THIS is where you fix it.
"""

from .freshness import FreshnessRanker, RankingResult

__all__ = [
    "FreshnessRanker",
    "RankingResult",
]

