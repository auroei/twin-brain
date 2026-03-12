"""Pydantic models for application configuration.

Provides type-safe configuration loading with validation and defaults.
"""
from typing import Dict, List, Optional, Literal
from pydantic import BaseModel, Field


# =============================================================================
# Behavior Configuration
# =============================================================================

class PersonalityConfig(BaseModel):
    """Personality settings for the bot."""
    tone: str = "Be concise and professional"
    emoji_usage: Literal["minimal", "moderate", "frequent"] = "minimal"


class RateLimitsConfig(BaseModel):
    """Rate limiting settings."""
    qa_calls_per_minute: int = 12
    classify_calls_per_minute: int = 8


class BehaviorConfig(BaseModel):
    """Bot behavior configuration."""
    personality: PersonalityConfig = Field(default_factory=PersonalityConfig)
    rate_limits: RateLimitsConfig = Field(default_factory=RateLimitsConfig)


# =============================================================================
# Retrieval Configuration
# =============================================================================

class RetrievalWeightsConfig(BaseModel):
    """Scoring weights for retrieval."""
    semantic: float = Field(default=0.7, ge=0.0, le=1.0)
    recency: float = Field(default=0.3, ge=0.0, le=1.0)


class RecencyConfig(BaseModel):
    """Recency decay configuration."""
    full_weight_days: int = 30
    half_life_days: int = 60
    min_weight: float = Field(default=0.3, ge=0.0, le=1.0)


class RerankerConfig(BaseModel):
    """LLM reranker configuration."""
    enabled: bool = True
    candidates: int = 30
    top_k: int = 5


class ContextConfig(BaseModel):
    """Context window limits."""
    max_chars: int = 8000
    max_docs: int = 10
    truncate_doc_at: int = 1500


class RetrievalSettingsConfig(BaseModel):
    """Initial retrieval settings."""
    default_n_results: int = 10
    over_retrieval_factor: int = 3


class CurationConfig(BaseModel):
    """Content curation rules."""
    min_length: int = 20
    skip_bot_messages: bool = True
    skip_reactions_only: bool = True


class LifecycleConfig(BaseModel):
    """Lifecycle filtering settings."""
    include_deprecated: bool = False
    include_draft: bool = True
    deprecated_penalty: float = 0.3
    draft_penalty: float = 0.7


class DeduplicationConfig(BaseModel):
    """Duplicate handling configuration."""
    enabled: bool = True
    similarity_threshold: float = 0.95
    prefer_newer: bool = True


class RetrievalConfig(BaseModel):
    """Full retrieval configuration."""
    weights: RetrievalWeightsConfig = Field(default_factory=RetrievalWeightsConfig)
    recency: RecencyConfig = Field(default_factory=RecencyConfig)
    reranker: RerankerConfig = Field(default_factory=RerankerConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    retrieval: RetrievalSettingsConfig = Field(default_factory=RetrievalSettingsConfig)
    curation: CurationConfig = Field(default_factory=CurationConfig)
    lifecycle: LifecycleConfig = Field(default_factory=LifecycleConfig)
    deduplication: DeduplicationConfig = Field(default_factory=DeduplicationConfig)


# =============================================================================
# Output Configuration
# =============================================================================

class LengthConfig(BaseModel):
    """Response length control."""
    default: Literal["concise", "detailed", "auto"] = "concise"
    max_chars: int = 800
    concise_target: int = 200
    detailed_target: int = 600


class StructureConfig(BaseModel):
    """Response structure settings."""
    default: Literal["bullets", "prose", "auto"] = "auto"
    bullet_threshold: int = 3


class CitationsConfig(BaseModel):
    """Citation settings."""
    enabled: bool = True
    format: Literal["inline", "footer", "none"] = "inline"
    max_citations: int = 3


class ConfidenceConfig(BaseModel):
    """Confidence handling settings."""
    threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    low_confidence_behavior: Literal["qualify", "refuse", "proceed"] = "qualify"


class FormattingConfig(BaseModel):
    """Formatting preferences."""
    use_markdown: bool = True
    use_emoji: bool = False
    section_headers: bool = False


class OutputConfig(BaseModel):
    """Full output configuration."""
    length: LengthConfig = Field(default_factory=LengthConfig)
    structure: StructureConfig = Field(default_factory=StructureConfig)
    citations: CitationsConfig = Field(default_factory=CitationsConfig)
    confidence: ConfidenceConfig = Field(default_factory=ConfidenceConfig)
    formatting: FormattingConfig = Field(default_factory=FormattingConfig)


# =============================================================================
# Gaps Configuration
# =============================================================================

class KnownGap(BaseModel):
    """A known gap in knowledge."""
    topic: str
    keywords: List[str]
    response: str


class OutOfScope(BaseModel):
    """An out-of-scope topic."""
    topic: str
    keywords: List[str]
    response: str


class AmbiguityConfig(BaseModel):
    """Ambiguity handling settings."""
    min_query_length: int = 5
    clarification_prompt: str = "Could you be more specific?"


class StalenessConfig(BaseModel):
    """Staleness warning settings."""
    warn_after_days: int = 30
    warning_template: str = "Note: The most relevant information I found is from {age} ago."


class GapsConfig(BaseModel):
    """Full gaps configuration."""
    known_gaps: List[KnownGap] = Field(default_factory=list)
    out_of_scope: List[OutOfScope] = Field(default_factory=list)
    ambiguity: AmbiguityConfig = Field(default_factory=AmbiguityConfig)
    staleness: StalenessConfig = Field(default_factory=StalenessConfig)


# =============================================================================
# UX Configuration
# =============================================================================

class ThinkingConfig(BaseModel):
    """Thinking/loading state messages."""
    default: str = "🔍 Searching my memory..."
    variants: List[str] = Field(default_factory=lambda: ["🔍 Searching my memory..."])


class SuccessConfig(BaseModel):
    """Success state messages."""
    found_context: str = ""
    low_confidence_prefix: str = "I'm not entirely certain, but based on what I've seen: "
    partial_match_prefix: str = "I found some related information: "


class EmptyStatesConfig(BaseModel):
    """Empty state messages."""
    no_results: str = "I couldn't find anything relevant in my memory."
    no_context: str = "I don't have any context on this topic yet."


class ErrorStatesConfig(BaseModel):
    """Error state messages."""
    generic: str = "Something went wrong while processing your question."
    rate_limited: str = "I'm getting a lot of questions right now. Please wait a moment."
    api_error: str = "I'm having trouble connecting. Please try again shortly."


class GreetingConfig(BaseModel):
    """Greeting configuration."""
    enabled: bool = True
    first_dm: str = ""


class ReactionsConfig(BaseModel):
    """Reaction emoji configuration."""
    watching: str = "eyes"
    processing: str = "hourglass"
    error: str = "x"


class AdminConfig(BaseModel):
    """Admin messages configuration."""
    unauthorized: str = "🔒 You're not authorized to use this bot."
    curator_only: str = "📚 Only curators can add threads to the knowledge base."


class UXConfig(BaseModel):
    """Full UX configuration."""
    thinking: ThinkingConfig = Field(default_factory=ThinkingConfig)
    success: SuccessConfig = Field(default_factory=SuccessConfig)
    empty_states: EmptyStatesConfig = Field(default_factory=EmptyStatesConfig)
    error_states: ErrorStatesConfig = Field(default_factory=ErrorStatesConfig)
    greeting: GreetingConfig = Field(default_factory=GreetingConfig)
    reactions: ReactionsConfig = Field(default_factory=ReactionsConfig)
    admin: AdminConfig = Field(default_factory=AdminConfig)


# =============================================================================
# Priority Configuration
# =============================================================================

class ContentPattern(BaseModel):
    """A content pattern for priority weighting."""
    pattern: str
    weight: float = 1.0
    reason: str = ""


class PriorityConfig(BaseModel):
    """Full priority configuration."""
    default_weight: float = 1.0
    topic_weights: Dict[str, float] = Field(default_factory=dict)
    theme_weights: Dict[str, float] = Field(default_factory=dict)
    product_weights: Dict[str, float] = Field(default_factory=dict)
    channel_weights: Dict[str, float] = Field(default_factory=dict)
    project_weights: Dict[str, float] = Field(default_factory=dict)
    content_patterns: List[ContentPattern] = Field(default_factory=list)
    combination_method: Literal["multiply", "max", "average"] = "multiply"
    min_weight: float = 0.5
    max_weight: float = 3.0


# =============================================================================
# Feedback Configuration
# =============================================================================

class FeedbackStorageConfig(BaseModel):
    """Feedback storage settings."""
    file: str = "feedback_log.jsonl"
    review_queue: str = "review_queue.json"


class FeedbackWeightsConfig(BaseModel):
    """Feedback weight settings."""
    curator: float = 5.0
    teacher: float = 5.0
    user: float = 1.0


class ReinforcementConfig(BaseModel):
    """L2 reinforcement settings."""
    positive_delta: float = 0.1
    negative_delta: float = -0.05
    score_min: float = -1.0
    score_max: float = 2.0


class FeedbackReactionsConfig(BaseModel):
    """Reaction-based feedback settings."""
    enabled: bool = True
    positive: List[str] = Field(default_factory=lambda: ["thumbsup", "+1"])
    negative: List[str] = Field(default_factory=lambda: ["thumbsdown", "-1"])
    use_for_training: bool = False


class ImplicitSignalsConfig(BaseModel):
    """Implicit signal tracking settings."""
    enabled: bool = True
    track_followup_questions: bool = True
    track_rephrases: bool = True
    track_repeated_questions: bool = True
    followup_window_seconds: int = 120
    rephrase_similarity_threshold: float = 0.7


class SamplingConfig(BaseModel):
    """Review sampling configuration."""
    review_negative_reactions: bool = True
    random_sample_rate: float = 0.1
    review_low_confidence: bool = True
    confidence_threshold: float = 0.5


class CuratedReviewConfig(BaseModel):
    """Curated review system settings."""
    enabled: bool = True
    reviewers: str = "curators"
    sampling: SamplingConfig = Field(default_factory=SamplingConfig)


class FeedbackConfig(BaseModel):
    """Full feedback configuration."""
    storage: FeedbackStorageConfig = Field(default_factory=FeedbackStorageConfig)
    weights: FeedbackWeightsConfig = Field(default_factory=FeedbackWeightsConfig)
    reinforcement: ReinforcementConfig = Field(default_factory=ReinforcementConfig)
    reactions: FeedbackReactionsConfig = Field(default_factory=FeedbackReactionsConfig)
    implicit_signals: ImplicitSignalsConfig = Field(default_factory=ImplicitSignalsConfig)
    curated_review: CuratedReviewConfig = Field(default_factory=CuratedReviewConfig)


# =============================================================================
# Combined App Configuration
# =============================================================================

class AppConfig(BaseModel):
    """Container for all application configuration."""
    behavior: BehaviorConfig = Field(default_factory=BehaviorConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    gaps: GapsConfig = Field(default_factory=GapsConfig)
    ux: UXConfig = Field(default_factory=UXConfig)
    priority: PriorityConfig = Field(default_factory=PriorityConfig)
    feedback: FeedbackConfig = Field(default_factory=FeedbackConfig)

