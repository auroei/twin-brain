"""
Evaluation module for memex-core.
Provides reusable metrics and evaluation functions for RAG systems.
"""

from .metrics import (
    calculate_mrr,
    evaluate_retrieval,
)
from .judge import (
    evaluate_end_to_end,
    judge_answer,
)

__all__ = [
    "calculate_mrr",
    "evaluate_retrieval",
    "evaluate_end_to_end",
    "judge_answer",
]

