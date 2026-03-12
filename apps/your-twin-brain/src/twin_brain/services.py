"""Service initialization for the twin-brain bot.

This module centralizes the initialization of all pipeline components
and services, eliminating duplication between main.py and catchup.py.
"""
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
    MemoryExtractor,
)

from .config_loader import AppConfig
from .context import BotContext


def initialize_services(
    configs: AppConfig,
    role_definition: RoleDefinition,
    gemini_api_key: str,
    knowledge_base_dir: str,
    data_dir: str,
    curator_ids: Optional[set] = None,
    teacher_ids: Optional[set] = None,
    include_retrieval: bool = True,
) -> BotContext:
    """
    Initialize all pipeline components and services.
    
    This function consolidates the initialization logic previously duplicated
    in main.py and catchup.py.
    
    Args:
        configs: ConfigBundle containing all configuration dictionaries
        role_definition: The bot's role definition (persona, context, etc.)
        gemini_api_key: API key for Gemini AI
        knowledge_base_dir: Path to ChromaDB persistence directory
        data_dir: Path to data directory for feedback storage
        curator_ids: Optional set of curator user IDs (for feedback weighting)
        teacher_ids: Optional set of teacher user IDs (for feedback weighting)
        include_retrieval: Whether to initialize retrieval components (False for catchup)
        
    Returns:
        BotContext: Fully initialized context with all services
    """
    curator_ids = curator_ids or set()
    teacher_ids = teacher_ids or set()
    
    # Initialize AI client
    client = GeminiClient(api_key=gemini_api_key)
    
    # Initialize vector store with context_client for contextual embeddings
    store = ChromaVectorStore(
        persist_directory=knowledge_base_dir,
        collection_name="slack_knowledge",
        api_key=gemini_api_key,
        context_client=client,
    )
    
    # Initialize memory components (pass config as dict for library compatibility)
    curator = MemoryCurator(config_dict=configs.retrieval.model_dump())
    classifier = ThreadClassifier(client)
    
    # Initialize memory extractor with error handling
    memory_extractor = None
    memory_extraction_enabled = False
    try:
        memory_extractor = MemoryExtractor(client)
        memory_extraction_enabled = True
    except Exception as e:
        print(f"⚠️ Failed to initialize MemoryExtractor: {e}")
    
    # Create ingestion pipeline (always needed)
    ingest_pipe = IngestionPipeline(
        curator, 
        classifier, 
        store,
        supersession_client=client,
        memory_extractor=memory_extractor,
    )
    
    # Initialize optional retrieval components
    retrieval_pipe = None
    generator = None
    gap_checker = None
    feedback_tracker = None
    
    if include_retrieval:
        generator = AnswerGenerator(client)
        
        # Gap checker (keyword-based by default, pass config as dict)
        gap_checker = GapChecker(configs.gaps.model_dump(), client=client, use_llm=False)
        
        # Feedback tracker with role-based weighting (pass config as dict)
        feedback_tracker = FeedbackTracker(
            feedback_config=configs.feedback.model_dump(),
            storage_dir=data_dir,
            curator_ids=curator_ids,
            teacher_ids=teacher_ids,
        )
        
        # Retrieval pipeline with re-ranking and priority weights (pass config as dict)
        retrieval_pipe = RetrievalPipeline(
            store,
            generator,
            reranker_client=client,
            priority_config=configs.priority.model_dump(),
        )
    
    print("✅ Initialized Pipeline Components")
    print("   • Contextual embeddings: Enabled")
    print("   • RAG classification: Enabled")
    if memory_extraction_enabled:
        print("   • Atomic memory extraction: Enabled")
        print("   • Hybrid retrieval: Enabled")
    else:
        print("   • Atomic memory extraction: Disabled")
        print("   • Hybrid retrieval: Disabled (falling back to thread search)")
    if include_retrieval:
        print("   • LLM re-ranking: Enabled")
        print("   • Gap checking: Enabled (keyword-based)")
        print("   • Priority weights: Enabled")
        print("   • Feedback tracking: Enabled")
    
    return BotContext(
        role_definition=role_definition,
        # Pipelines
        ingest_pipe=ingest_pipe,
        retrieval_pipe=retrieval_pipe,
        # AI services
        client=client,
        gap_checker=gap_checker,
        feedback_tracker=feedback_tracker,
        # Storage
        store=store,
        curator=curator,
        classifier=classifier,
        generator=generator,
        # Configs
        ux_config=configs.ux,
        behavior_config=configs.behavior,
        retrieval_config=configs.retrieval,
        output_config=configs.output,
        gaps_config=configs.gaps,
        feedback_config=configs.feedback,
        priority_config=configs.priority,
        # RBAC
        curator_ids=curator_ids,
        teacher_ids=teacher_ids,
    )

