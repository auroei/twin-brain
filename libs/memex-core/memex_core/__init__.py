"""
memex-core: Core library for memex functionality.
Exposes Pipelines, AI components, Storage adapters, and Evaluation tools.

Enhanced with:
- Memory Abstractions: Lifecycle status and lineage tracking
- First-Class Prompts: Externalized Jinja2 templates
- Consolidation Pipeline: Nightly synthesis into DailyInsights
- Maintenance Pipeline: Background tasks for KB health
- Event-Driven Updates: Auto-deprecation of superseded threads
"""

# 1. Pipelines (The Workflows)
from .pipelines import (
    IngestionPipeline,
    RetrievalPipeline,
    ConsolidationPipeline,
    MaintenancePipeline,
)

# 2. AI Components (The Brain)
from .ai import (
    GeminiClient,
    ThreadClassifier,
    AnswerGenerator,
    GapChecker,
    MemoryExtractor,
    rate_limit_gemini_qa,
    rate_limit_gemini_classify,
)

# 3. Storage & Memory (The Knowledge)
from .storage import ChromaVectorStore
from .memory import MemoryCurator

# 4. Evaluation (The Metrics)
from .eval import (
    calculate_mrr,
    evaluate_retrieval,
    evaluate_end_to_end,
    judge_answer,
)

# 5. Data Models & Utils
from .models import (
    RoleDefinition,
    ThreadClassification,
    SlackMessage,
    SlackThread,
    Theme,
    LifecycleStatus,
    DailyInsight,
    # Atomic Memory Models
    AtomicMemory,
    MemoryRelation,
    TemporalMetadata,
    MemoryExtractionResult,
)
from .utils import (
    clean_query,
    format_thread,
    truncate_thread_for_classification,
    validate_slack_response,
    load_role_definition,
    parse_datetime_robust,
    parse_datetime_list_robust,
)

# 6. Prompts (Externalized Templates)
from .prompts import (
    load_prompt,
    render_prompt,
    list_available_prompts,
    set_app_prompts_dir,
    get_prompt_source,
)

# 7. Feedback (User Feedback Loop)
from .feedback import (
    FeedbackTracker,
    FeedbackEntry,
    ReviewItem,
)

# 8. Formatters (Response Formatting)
from .formatters import (
    ResponseFormatter,
    FormattedResponse,
    CitationFormatter,
)

# 9. Ranking (Single owner of "which information wins")
from .ranking import (
    FreshnessRanker,
    RankingResult,
)

# 10. Factory Functions (Simplified Entry Points)
from .core import create_memex_system

__all__ = [
    # Pipelines
    "IngestionPipeline",
    "RetrievalPipeline",
    "ConsolidationPipeline",
    "MaintenancePipeline",
    # AI Components
    "GeminiClient",
    "ThreadClassifier",
    "AnswerGenerator",
    "GapChecker",
    "MemoryExtractor",
    "rate_limit_gemini_qa",
    "rate_limit_gemini_classify",
    # Storage & Memory
    "ChromaVectorStore",
    "MemoryCurator",
    # Evaluation
    "calculate_mrr",
    "evaluate_retrieval",
    "evaluate_end_to_end",
    "judge_answer",
    # Data Models
    "RoleDefinition",
    "ThreadClassification",
    "SlackMessage",
    "SlackThread",
    "Theme",
    "LifecycleStatus",
    "DailyInsight",
    # Atomic Memory Models
    "AtomicMemory",
    "MemoryRelation",
    "TemporalMetadata",
    "MemoryExtractionResult",
    # Utils
    "clean_query",
    "format_thread",
    "truncate_thread_for_classification",
    "validate_slack_response",
    "load_role_definition",
    "parse_datetime_robust",
    "parse_datetime_list_robust",
    # Prompts
    "load_prompt",
    "render_prompt",
    "list_available_prompts",
    "set_app_prompts_dir",
    "get_prompt_source",
    # Feedback
    "FeedbackTracker",
    "FeedbackEntry",
    "ReviewItem",
    # Formatters
    "ResponseFormatter",
    "FormattedResponse",
    "CitationFormatter",
    # Ranking
    "FreshnessRanker",
    "RankingResult",
    # Factory Functions
    "create_memex_system",
]
