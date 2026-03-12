"""Bot context container for dependency injection.

This module defines the BotContext dataclass which consolidates all
dependencies needed by handlers, eliminating argument explosion.
"""
from dataclasses import dataclass
from typing import Optional

from memex_core import (
    GeminiClient,
    ChromaVectorStore,
    MemoryCurator,
    ThreadClassifier,
    AnswerGenerator,
    GapChecker,
    FeedbackTracker,
    IngestionPipeline,
    RetrievalPipeline,
    RoleDefinition,
)

from .config_models import (
    UXConfig,
    BehaviorConfig,
    RetrievalConfig,
    OutputConfig,
    GapsConfig,
    FeedbackConfig,
    PriorityConfig,
)


@dataclass
class BotContext:
    """
    Container for all bot dependencies and configuration.
    
    This dataclass consolidates the dependencies that were previously
    passed as individual arguments to handler factory functions.
    
    Attributes:
        role_definition: The bot's role definition (persona, context, etc.)
        
        # Pipeline components
        ingest_pipe: Pipeline for ingesting threads into the knowledge base
        retrieval_pipe: Pipeline for answering questions via RAG
        
        # AI services
        client: Gemini AI client for LLM operations
        gap_checker: Checker for known gaps and out-of-scope queries
        feedback_tracker: Tracker for user feedback and reactions
        
        # Storage
        store: ChromaDB vector store for knowledge base
        curator: Memory curator for thread curation
        classifier: Thread classifier for categorization
        generator: Answer generator for Q&A
        
        # Configuration (typed Pydantic models)
        ux_config: UX messages and behavior configuration
        behavior_config: Classification behavior configuration
        retrieval_config: Retrieval weights and settings
        output_config: Output formatting configuration
        gaps_config: Gap checking configuration
        feedback_config: Feedback tracking configuration
        priority_config: Priority weighting configuration
        
        # RBAC
        curator_ids: Set of curator user IDs (full permissions)
        teacher_ids: Set of teacher user IDs (elevated feedback weight)
    """
    # Role definition
    role_definition: RoleDefinition
    
    # Pipeline components
    ingest_pipe: IngestionPipeline
    retrieval_pipe: Optional[RetrievalPipeline] = None
    
    # AI services
    client: Optional[GeminiClient] = None
    gap_checker: Optional[GapChecker] = None
    feedback_tracker: Optional[FeedbackTracker] = None
    
    # Storage components
    store: Optional[ChromaVectorStore] = None
    curator: Optional[MemoryCurator] = None
    classifier: Optional[ThreadClassifier] = None
    generator: Optional[AnswerGenerator] = None
    
    # Configuration (typed Pydantic models)
    ux_config: Optional[UXConfig] = None
    behavior_config: Optional[BehaviorConfig] = None
    retrieval_config: Optional[RetrievalConfig] = None
    output_config: Optional[OutputConfig] = None
    gaps_config: Optional[GapsConfig] = None
    feedback_config: Optional[FeedbackConfig] = None
    priority_config: Optional[PriorityConfig] = None
    
    # RBAC
    curator_ids: Optional[set] = None
    teacher_ids: Optional[set] = None

