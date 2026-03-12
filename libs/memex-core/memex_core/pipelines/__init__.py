"""
Pipelines module for memex-core.
Contains pipeline definitions for processing Slack threads.

Includes:
- IngestionPipeline: Watch workflow with event-driven updates
- RetrievalPipeline: Answer workflow with lifecycle filtering
- ConsolidationPipeline: Nightly synthesis of threads into insights
- MaintenancePipeline: Background tasks for knowledge base health
"""

from .ingestion import IngestionPipeline
from .retrieval import RetrievalPipeline
from .consolidation import ConsolidationPipeline
from .maintenance import MaintenancePipeline

__all__ = [
    "IngestionPipeline",
    "RetrievalPipeline",
    "ConsolidationPipeline",
    "MaintenancePipeline",
]

