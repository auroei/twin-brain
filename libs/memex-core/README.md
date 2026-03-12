# memex-core

Core library for memex functionality - Pipelines, AI components, Storage adapters, Evaluation tools, and Feedback tracking.

## Installation

Install in editable mode:

```bash
pip install -e libs/memex-core
```

## Architecture

```
memex_core/
├── pipelines/              # High-level workflows
│   ├── ingestion.py        # IngestionPipeline (watch → index)
│   ├── retrieval.py        # RetrievalPipeline (question → answer)
│   ├── consolidation.py    # ConsolidationPipeline (nightly synthesis)
│   └── maintenance.py      # MaintenancePipeline (KB health tasks)
├── ai/                     # LLM operations
│   ├── client.py           # GeminiClient (API wrapper + rate limiting)
│   ├── classifier.py       # ThreadClassifier (categorization)
│   ├── generator.py        # AnswerGenerator (RAG responses)
│   ├── gap_checker.py      # GapChecker (out-of-scope detection)
│   └── memory_extractor.py # MemoryExtractor (atomic memory extraction)
├── storage/                # Vector database
│   └── vector_store.py     # ChromaVectorStore (ChromaDB wrapper)
├── memory/                 # Quality control
│   └── curator.py          # MemoryCurator (filtering)
├── feedback/               # User feedback loop
│   └── tracker.py          # FeedbackTracker (reactions, L2 reinforcement)
├── eval/                   # Evaluation metrics
│   ├── judge.py            # LLM-as-judge evaluator
│   └── metrics.py          # Retrieval metrics (MRR, Precision, Recall)
├── prompts/                # Externalized templates
│   ├── answer.jinja2       # Answer generation prompt
│   ├── classify.jinja2     # Thread classification prompt
│   ├── consolidate.jinja2  # Daily consolidation prompt
│   ├── extract_memories.jinja2  # Atomic memory extraction
│   └── detect_supersession.jinja2  # Supersession detection
├── core.py                 # Factory functions (create_memex_system)
├── models.py               # Pydantic models
└── utils.py                # Formatting & validation helpers
```

## Usage

### Pipeline API

The pipeline-based API provides clean separation of concerns and orchestrates complex workflows.

```python
from memex_core import (
    GeminiClient,
    ThreadClassifier,
    AnswerGenerator,
    GapChecker,
    MemoryExtractor,
    ChromaVectorStore,
    MemoryCurator,
    IngestionPipeline,
    RetrievalPipeline,
    ConsolidationPipeline,
    MaintenancePipeline,
    load_role_definition,
)
from memex_core.models import SlackThread, SlackMessage

# Initialize components
client = GeminiClient(api_key="your-api-key")
store = ChromaVectorStore(
    persist_directory="./my_knowledge_base",
    collection_name="slack_knowledge",
    api_key="your-api-key",
    context_client=client,  # For contextual embeddings
)
curator = MemoryCurator(config_dict={"curation": {"min_length": 20}})
classifier = ThreadClassifier(client)
generator = AnswerGenerator(client)
memory_extractor = MemoryExtractor(client)

# Create pipelines
ingest_pipe = IngestionPipeline(
    curator, 
    classifier, 
    store,
    supersession_client=client,
    memory_extractor=memory_extractor,
)
retrieval_pipe = RetrievalPipeline(
    store, 
    generator,
    reranker_client=client,
)

# Load role definition
role_def = load_role_definition(role_file="role.yaml")

# Ingest a thread (full pipeline: curate → store → classify → extract memories)
thread = SlackThread(
    thread_ts="1234567890.123456",
    channel_id="C1234567890",
    messages=[
        SlackMessage(user="U123", text="Hello", ts="1234567890.123456"),
        SlackMessage(user="U456", text="Hi there!", ts="1234567890.123457")
    ]
)
success = ingest_pipe.process_thread(thread, role_def)

# Answer a question (full pipeline: query → retrieve → rerank → generate)
answer = retrieval_pipe.answer_question(
    query="What's the status?",
    role_def=role_def,
    behavior_config={"personality": {"tone": "Be concise"}},
    retrieval_config={"weights": {"recency": 0.3, "semantic": 0.7}}
)
```

### Pipeline Methods

#### IngestionPipeline

| Method | Description |
|--------|-------------|
| `process_thread(thread, role_def, ...)` | Full pipeline: curate → store → classify → extract memories |
| `process_thread_async(thread, ...)` | Quick storage only (skip classification) |
| `classify_thread(thread, role_def, ...)` | Classify an already-stored thread |

#### RetrievalPipeline

| Method | Description |
|--------|-------------|
| `answer_question(query, role_def, ...)` | Full RAG: retrieve → rerank → generate |
| `retrieve_context(query, ...)` | Retrieve only (for debugging) |

#### ConsolidationPipeline

| Method | Description |
|--------|-------------|
| `run_daily_consolidation(...)` | Synthesize threads into DailyInsights |

#### MaintenancePipeline

| Method | Description |
|--------|-------------|
| `run_maintenance(...)` | Background tasks for KB health |

### Feedback Tracking

Track user reactions and apply L2 reinforcement learning:

```python
from memex_core import FeedbackTracker

tracker = FeedbackTracker(
    feedback_config={"weights": {"curator": 5.0, "teacher": 5.0, "user": 1.0}},
    storage_dir="./data",
    curator_ids={"U123", "U456"},
    teacher_ids={"U789"},
)

# Record feedback and apply L2 reinforcement
tracker.record_and_reinforce(
    message_ts="1234567890.123456",
    user_id="U123",
    reaction="thumbsup",
    source_thread_ids=["thread1", "thread2"],
    vector_store=store,
)
```

### Gap Checking

Detect out-of-scope queries before retrieval:

```python
from memex_core import GapChecker

gap_checker = GapChecker(
    gaps_config={"keywords": ["competitor", "pricing"]},
    client=client,
    use_llm=False,  # Use keyword-based (fast) or LLM-based (accurate)
)

is_gap, reason = gap_checker.check(query="What is competitor pricing?")
```

### Evaluation

Evaluate retrieval and end-to-end performance:

```python
from memex_core import evaluate_retrieval, evaluate_end_to_end, calculate_mrr

# Retrieval metrics
metrics = evaluate_retrieval(
    queries=["What is X?"],
    expected_ids=[["doc1", "doc2"]],
    retrieved_ids=[["doc1", "doc3"]],
    k=5,
)
print(f"Precision: {metrics['precision']}, Recall: {metrics['recall']}")

# End-to-end with LLM judge
accuracy = evaluate_end_to_end(
    questions=["What is X?"],
    expected_answers=["X is a feature"],
    generated_answers=["X is our new feature"],
    client=client,
)
```

### Prompts

Load and render externalized Jinja2 templates:

```python
from memex_core import load_prompt, render_prompt, set_app_prompts_dir

# Use app-specific prompts (with fallback to library defaults)
set_app_prompts_dir("apps/your-twin-brain/config/prompts")

# Render a prompt
prompt = render_prompt("answer", query="What is X?", context="X is a feature")
```

### Direct Component Access

You can also use components directly for fine-grained control:

```python
from memex_core import GeminiClient, ThreadClassifier, ChromaVectorStore

# Classification
client = GeminiClient(api_key="your-api-key")
classifier = ThreadClassifier(client)
classification = classifier.classify_thread(thread_text, role_def)

# Storage
store = ChromaVectorStore(persist_directory="./kb", api_key="your-api-key")
store.upsert_thread(thread)
context = store.query_threads("search query", n_results=10)
```

## Models

The library uses Pydantic models for type safety:

| Model | Description |
|-------|-------------|
| `RoleDefinition` | Role, products, themes, and topics |
| `ThreadClassification` | Classification dimensions (theme, product, project, topic) |
| `SlackMessage` | Individual Slack message |
| `SlackThread` | Complete thread with messages and optional classification |
| `Theme` | Theme with name and description |
| `LifecycleStatus` | Memory lifecycle state (active, deprecated, superseded) |
| `DailyInsight` | Consolidated daily summary |
| `AtomicMemory` | Single discrete fact extracted from threads |
| `MemoryRelation` | Relationship between atomic memories |
| `TemporalMetadata` | Temporal validity for time-sensitive facts |
| `MemoryExtractionResult` | Result of atomic memory extraction |

## Exports

All classes are exported from the main `memex_core` module:

```python
from memex_core import (
    # Pipelines
    IngestionPipeline,
    RetrievalPipeline,
    ConsolidationPipeline,
    MaintenancePipeline,
    # AI Components
    GeminiClient,
    ThreadClassifier,
    AnswerGenerator,
    GapChecker,
    MemoryExtractor,
    rate_limit_gemini_qa,
    rate_limit_gemini_classify,
    # Storage & Memory
    ChromaVectorStore,
    MemoryCurator,
    # Evaluation
    calculate_mrr,
    evaluate_retrieval,
    evaluate_end_to_end,
    judge_answer,
    # Data Models
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
    # Utilities
    clean_query,
    format_thread,
    truncate_thread_for_classification,
    validate_slack_response,
    load_role_definition,
    parse_datetime_robust,
    parse_datetime_list_robust,
    # Prompts
    load_prompt,
    render_prompt,
    list_available_prompts,
    set_app_prompts_dir,
    get_prompt_source,
    # Feedback
    FeedbackTracker,
    FeedbackEntry,
    ReviewItem,
    # Factory Functions
    create_memex_system,
)
```
