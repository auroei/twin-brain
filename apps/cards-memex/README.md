# Cards Memex Bot

A Slack bot that indexes threads and answers questions via RAG (Retrieval-Augmented Generation).

## Directory Structure

```
apps/cards-memex/
├── main.py                    # Bot entry point (thin orchestrator)
├── catchup.py                 # Refresh memory on startup
├── run.sh                     # Startup script with backups
├── config/                    # Configuration files
│   ├── role.yaml              # Role definition (themes, topics, products)
│   ├── behavior.yaml          # Personality and rate limits
│   ├── retrieval.yaml         # Retrieval weights and ranking
│   ├── output.yaml            # Output formatting
│   ├── gaps.yaml              # Known gaps and out-of-scope topics
│   ├── ux.yaml                # User-facing messages
│   ├── priority.yaml          # Thread priority weights
│   ├── feedback.yaml          # Feedback and reinforcement settings
│   └── prompts/               # Custom prompt templates
│       └── *.jinja2
├── src/                       # Python package
│   └── cards_memex/
│       ├── __init__.py
│       ├── paths.py           # Centralized path definitions
│       ├── rbac.py            # Role-based access control
│       ├── config_loader.py   # Configuration loading
│       ├── ux.py              # UX helper functions
│       ├── services.py        # Service initialization
│       ├── context.py         # BotContext for dependency injection
│       └── handlers/          # Slack event handlers
│           ├── __init__.py
│           ├── mentions.py    # @mention handler
│           ├── messages.py    # Message handler (DM Q&A, monitoring)
│           └── reactions.py   # Reaction handler (feedback)
├── data/                      # Runtime data (gitignored)
│   ├── knowledge_base/        # ChromaDB vector store
│   ├── watched_threads.json   # Watched thread list
│   ├── feedback_log.jsonl     # Feedback entries
│   └── review_queue.json      # Expert review queue
├── evals/                     # Evaluation datasets
│   └── golden_dataset.jsonl
├── scripts/                   # Utility scripts
│   ├── reindex_watched.py     # Rebuild watch list from ChromaDB
│   ├── run_evals.py           # Run evaluation suite
│   └── ...
└── backups/                   # Automatic backups
```

## Features

- **Thread Indexing**: Tag the bot in Slack threads to add them to the knowledge base
- **Q&A via DM**: Ask questions in direct messages and get answers from indexed threads
- **Feedback Collection**: React to answers with 👍/👎 for feedback
- **L2 Reinforcement Learning**: Good answers boost their source threads in future rankings

## Role-Based Access Control (RBAC)

The bot uses a three-role system for access control:

| Role | Tag Threads | Q&A | Feedback Weight | L2 Reinforcement |
|------|-------------|-----|-----------------|------------------|
| **Curator** | ✅ | ✅ | 5x | ✅ |
| **Teacher** | ❌ | ✅ | 5x | ✅ |
| **User** | ❌ | ✅ | 1x (logged) | ❌ |

### Environment Variables

```bash
# Role-based Access Control (add to .env)
CURATOR_IDS=U000EXAMPLE1,U000EXAMPLE2  # Required: Admins who can tag threads
TEACHER_IDS=U111,U222,U333           # Optional: Can give weighted feedback
```

### Role Behaviors

**Curators (`CURATOR_IDS` - required):**
- Can tag threads by mentioning the bot (👀 reaction)
- Can ask questions via DM
- Feedback has 5x weight + L2 reinforcement
- Positive reactions boost source threads immediately
- Negative reactions penalize source threads immediately

**Teachers (`TEACHER_IDS` - optional):**
- Can ask questions via DM
- Cannot tag threads (receives guidance message)
- Feedback has 5x weight + L2 reinforcement (same as curators)
- Positive/negative reactions trigger L2 reinforcement

**Users (everyone else - open access):**
- Can ask questions via DM
- Cannot tag threads (receives guidance message)
- Feedback is logged but does NOT trigger L2 reinforcement
- Useful for collecting data without affecting rankings

> **Note:** Q&A is open to everyone on Slack. You only need to declare `CURATOR_IDS` (and optionally `TEACHER_IDS`).

## Feedback & Reinforcement Learning

### L1: Weighted Feedback

Reactions on answers are weighted by user role:
- Curator 👍 = +0.5 (0.1 × 5x weight) → L2 reinforcement
- Curator 👎 = -0.25 (-0.05 × 5x weight) → L2 reinforcement
- Teacher 👍 = +0.5 (0.1 × 5x weight) → L2 reinforcement
- Teacher 👎 = -0.25 (-0.05 × 5x weight) → L2 reinforcement
- User 👍/👎 = logged only, no L2 reinforcement

### L2: Retrieval Boosting

Source threads that produce well-received answers get boosted in future rankings:

```
combined_score = base_score × priority_weight × (1.0 + feedback_score)
```

Where `feedback_score`:
- Starts at 0.0 (neutral)
- Ranges from -1.0 (heavily penalized) to 2.0 (heavily boosted)
- Persists across bot restarts (stored in ChromaDB metadata)

## Configuration

Configuration files are in `config/`:

- `role.yaml` - Role definition (themes, topics, products)
- `behavior.yaml` - Personality and rate limits
- `retrieval.yaml` - Retrieval weights and ranking
- `output.yaml` - Output formatting
- `gaps.yaml` - Known gaps and out-of-scope topics
- `ux.yaml` - User-facing messages including `curator_only` message
- `priority.yaml` - Thread priority weights by topic/theme/product
- `feedback.yaml` - Feedback weights and reinforcement settings

### Key Feedback Config

```yaml
# config/feedback.yaml
weights:
  curator: 5.0   # Curators get 5x weight + L2 reinforcement
  teacher: 5.0   # Teachers get 5x weight + L2 reinforcement
  user: 1.0      # Users get 1x weight (logged only)

reinforcement:
  positive_delta: 0.1   # Boost per positive reaction
  negative_delta: -0.05 # Penalty per negative reaction
  score_min: -1.0       # Floor for feedback_score
  score_max: 2.0        # Ceiling for feedback_score
```

## Setup

1. Copy `.env.example` to `.env` and fill in:
   - `SLACK_BOT_TOKEN` - Bot User OAuth Token
   - `SLACK_APP_TOKEN` - App-Level Token
   - `GEMINI_API_KEY` - Google Gemini API key
   - `CURATOR_IDS` - Comma-separated curator Slack user IDs (required)
   - `TEACHER_IDS` - Comma-separated teacher Slack user IDs (optional)
   
   > Q&A is open to everyone. Only curators and teachers can give weighted feedback.

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   pip install -e libs/memex-core
   ```

3. Run the bot:
   ```bash
   cd apps/cards-memex
   ./run.sh
   ```
   
   Or run just the bot (without catchup):
   ```bash
   cd apps/cards-memex
   python main.py
   ```

## Module Structure

The `src/cards_memex/` package contains the core application logic:

- **`paths.py`** - Centralized path definitions (APP_DIR, CONFIG_DIR, DATA_DIR, etc.)
- **`rbac.py`** - Role-based access control functions
- **`config_loader.py`** - YAML configuration loading with defaults
- **`ux.py`** - User experience helpers (messages, greetings)
- **`services.py`** - Service initialization (consolidates pipeline setup for main.py and catchup.py)
- **`context.py`** - BotContext dataclass for dependency injection across handlers
- **`handlers/`** - Slack event handlers
  - `mentions.py` - Handles @mention events for thread tagging
  - `messages.py` - Handles DM Q&A and channel monitoring
  - `reactions.py` - Handles feedback reactions

## Background Pipelines (Not Yet Scheduled)

The `memex-core` library includes additional pipelines that require a scheduler:

- **ConsolidationPipeline**: Nightly synthesis of threads into DailyInsights (group by theme, summarize)
- **MaintenancePipeline**: Re-classification, schema migration, stale thread detection

To use these, create a scheduled job (e.g., cron, AWS Lambda) that calls:

```python
from memex_core import ConsolidationPipeline, MaintenancePipeline, GeminiClient, ChromaVectorStore

# Consolidation: Run nightly
consolidation = ConsolidationPipeline(vector_store, gemini_client, hours_lookback=24)
consolidation.run(min_threads_per_theme=2)

# Maintenance: Run weekly
maintenance = MaintenancePipeline(vector_store, classifier)
maintenance.reclassify_unclassified(role_def)
maintenance.mark_stale_threads(days_threshold=180)
```

## Scripts

Utility scripts are in `scripts/`:

- **`reindex_watched.py`** - Rebuild `watched_threads.json` from ChromaDB
- **`run_evals.py`** - Run retrieval and E2E evaluation suite
- **`query_channel_ids.py`** - Query channel IDs from Slack
- **`verify_api_key.py`** - Verify API key configuration

## Testing Checklist

- [ ] Curator can tag threads (👀 reaction)
- [ ] Teacher cannot tag threads (gets ephemeral message)
- [ ] User cannot tag threads (gets ephemeral message)
- [ ] All three roles can DM for Q&A
- [ ] Curator 👍 boosts source threads' feedback_score (5x)
- [ ] Teacher 👍 boosts source threads' feedback_score (5x)
- [ ] Curator/Teacher 👎 decrements feedback_score
- [ ] User 👍/👎 logs but doesn't trigger L2 reinforcement
- [ ] Boosted threads rank higher in subsequent queries
- [ ] feedback_score persists across bot restarts
