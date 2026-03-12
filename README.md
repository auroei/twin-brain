# twin-brain

**A RAG-powered Slack bot that acts as a "second brain" for your team.** It watches important threads, indexes them into a vector database with AI-powered classification, and answers natural-language questions with cited sources — learning from human feedback to improve over time.

**Tech stack:** Python · Google Gemini · ChromaDB · Slack Bolt · Pydantic · Jinja2

### Highlights

- **Retrieval-Augmented Generation** — semantic search + LLM reranking over a ChromaDB vector store
- **Two-level reinforcement learning** — weighted feedback (L1) drives retrieval boosting (L2) so high-quality threads surface naturally
- **Three-role RBAC** — Curators, Teachers, Users with differentiated permissions and feedback weights
- **Eval framework** — golden dataset, LLM-as-judge, precision/recall/MRR metrics
- **Config-driven architecture** — YAML configs + Jinja2 prompt templates, no code changes needed for tuning
- **Monorepo** — reusable core library (`memex-core`) separated from the application layer (`cards-memex`)

---

## Features

- 🧠 **Memory System** — Indexes watched Slack threads into a vector database
- 🏷️ **Smart Classification** — AI-powered categorization by theme, product, project, topic
- 💬 **Q&A Interface** — Ask questions in DMs, get context-aware answers
- 👀 **Silent Mode** — Tag bot in threads to watch (no spam, just 👀 reaction)
- 🔐 **Three-Role RBAC** — Curators, Teachers, and open User access
- 📊 **Reinforcement Learning** — Feedback boosts/penalizes thread rankings (L1+L2)
- 🔄 **Daily Catch-Up** — Auto-refreshes memory on startup

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt
pip install -e libs/memex-core

# 2. Configure environment (see Setup section)
cp apps/cards-memex/.env.example apps/cards-memex/.env
# Edit .env with your tokens

# 3. Run
bash run.sh
```

---

## Architecture

```
twin-brain/
├── apps/cards-memex/           # Application Layer
│   ├── main.py                 # Slack bot entry point
│   ├── catchup.py              # Memory refresh script
│   ├── config/                 # Configuration files
│   │   ├── role.yaml           # Domain knowledge & taxonomy
│   │   ├── behavior.yaml       # Personality & rate limits
│   │   ├── retrieval.yaml      # Search weights & ranking
│   │   ├── output.yaml         # Response formatting
│   │   ├── feedback.yaml       # RBAC weights & reinforcement
│   │   ├── priority.yaml       # Thread importance weights
│   │   ├── gaps.yaml           # Known gaps & out-of-scope
│   │   ├── ux.yaml             # User-facing messages
│   │   └── prompts/            # Jinja2 prompt templates
│   ├── src/cards_memex/        # Python package
│   └── data/                   # Runtime data (gitignored)
│       ├── knowledge_base/     # ChromaDB vector store
│       └── watched_threads.json
│
└── libs/memex-core/            # Reusable Core Library
    └── memex_core/
        ├── pipelines/          # Workflows (Ingestion, Retrieval, Consolidation)
        ├── ai/                 # LLM adapters (Gemini)
        ├── storage/            # Vector DB (ChromaDB)
        ├── memory/             # Memory curation
        ├── feedback/           # Feedback tracking & L2 reinforcement
        ├── eval/               # Evaluation metrics
        └── prompts/            # Default prompt templates
```

---

## Role-Based Access Control (RBAC)

Three-role system with weighted feedback for reinforcement learning:

| Role | Tag Threads | Q&A | Feedback Weight | L2 Reinforcement |
|------|:-----------:|:---:|:---------------:|:----------------:|
| **Curator** | ✅ | ✅ | 5× | ✅ |
| **Teacher** | ❌ | ✅ | 5× | ✅ |
| **User** | ❌ | ✅ | 1× (logged) | ❌ |

### Environment Variables

```bash
# Required: Curators can tag threads + weighted feedback
CURATOR_IDS=U000EXAMPLE1,U000EXAMPLE2,U000EXAMPLE3

# Optional: Teachers get weighted feedback (no tagging)
TEACHER_IDS=U000EXAMPLE4,U000EXAMPLE5,U000EXAMPLE6

# Everyone else can Q&A with logged (non-weighted) feedback
```

### How It Works

1. **Curators** tag threads by @mentioning the bot → thread gets indexed
2. **Anyone** can DM the bot to ask questions
3. **Curators & Teachers** reactions (👍/👎) adjust thread rankings
4. Higher-ranked threads surface more often in future answers

---

## Reinforcement Learning

### L1: Weighted Feedback

Reactions are weighted by role:
- **Curator/Teacher** 👍 → `+0.5` boost to source threads
- **Curator/Teacher** 👎 → `-0.25` penalty to source threads
- **User** 👍/👎 → logged only (no ranking impact)

### L2: Retrieval Boosting

Thread rankings incorporate feedback:

```
score = semantic_score × recency × priority × (1 + feedback_score)
```

- `feedback_score` ranges from `-1.0` to `+2.0`
- Persists in ChromaDB metadata across restarts
- High-quality threads naturally rise; poor ones sink

---

## Setup

### 1. Prerequisites

- Python 3.9+ (3.10+ recommended)
- Slack workspace with bot creation permissions
- Google Gemini API key

### 2. Create Slack App

1. Go to [Slack API Apps](https://api.slack.com/apps)
2. **Create New App** → **From scratch**
3. Name it and select your workspace

### 3. Configure Slack Scopes

**Bot Token Scopes** (OAuth & Permissions):

| Scope | Purpose |
|-------|---------|
| `app_mentions:read` | Detect @mentions |
| `channels:history` | Read channel messages |
| `channels:join` | Join public channels |
| `chat:write` | Send messages |
| `groups:history` | Read private channels |
| `im:history` | Read DM history |
| `im:write` | Send DMs (**required for Q&A**) |
| `reactions:read` | Receive reaction events |
| `reactions:write` | Add 👀 reactions |

After adding scopes → **Reinstall App**.

### 4. Enable Socket Mode

1. **Socket Mode** → Enable
2. Create **App-Level Token** with `connections:write`
3. Save token (starts with `xapp-`)

### 5. Configure Environment

Create `apps/cards-memex/.env`:

```bash
# Slack Credentials
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-token

# Google Gemini API Key
GEMINI_API_KEY=AIza...your-key

# Role-Based Access Control
CURATOR_IDS=U000EXAMPLE1,U000EXAMPLE2
TEACHER_IDS=U000EXAMPLE4,U000EXAMPLE5
```

**Get User IDs:** Slack profile → `...` → Copy member ID

**Get Gemini Key:** [Google AI Studio](https://aistudio.google.com/app/apikey)

---

## Running the Bot

### Start

```bash
bash run.sh
```

Expected output:

```
⚡️ Cards-Strategy Bot - Startup Sequence
============================================================
✅ Slack Authentication Successful
✅ ChromaDB Connected
✅ Role-Based Access Control Configured
   Curators (tag + Q&A + 5x feedback + L2): 5
   Teachers (Q&A + 5x feedback + L2): 11
   Users (Q&A + logged feedback): Open access

✅ BOT IS READY!
============================================================
📋 Mode: Three-Role Access Control
   • Curators (5): Tag + Q&A + 5x feedback + L2
   • Teachers (11): Q&A + 5x feedback + L2
   • Users (open): Q&A + logged feedback
============================================================
```

### Stop

```bash
Ctrl+C
# or
pkill -f "main.py"
```

---

## Usage

### Watch a Thread (Curators Only)

Tag the bot in any thread:

```
@memex
```

Bot will:
- React with 👀
- Index the thread
- Monitor for updates
- Classify in background

### Ask Questions (Everyone)

DM the bot:

```
What's the status of Project X?
```

Bot will:
1. Show thinking message
2. Search indexed threads
3. Generate answer with citations
4. Track for feedback

### Give Feedback

React to any bot answer:
- 👍 → Boosts source thread rankings (Curators/Teachers)
- 👎 → Penalizes source thread rankings (Curators/Teachers)

---

## Configuration

All config in `apps/cards-memex/config/`:

| File | Purpose |
|------|---------|
| `feedback.yaml` | RBAC weights, L2 reinforcement settings |
| `retrieval.yaml` | Semantic/recency weights, re-ranking |
| `priority.yaml` | Thread importance by topic/channel |
| `output.yaml` | Response length, citations, confidence |
| `gaps.yaml` | Known gaps, out-of-scope topics |
| `ux.yaml` | User-facing messages |
| `behavior.yaml` | Tone, rate limits |
| `prompts/` | Jinja2 template overrides |

### Key Configurations

**Feedback Weights** (`feedback.yaml`):
```yaml
weights:
  curator: 5.0
  teacher: 5.0
  user: 1.0

reinforcement:
  positive_delta: 0.1
  negative_delta: -0.05
  score_min: -1.0
  score_max: 2.0
```

**Retrieval Tuning** (`retrieval.yaml`):
```yaml
weights:
  semantic: 0.7
  recency: 0.3

reranker:
  enabled: true
  top_k: 5
```

**Thread Priority** (`priority.yaml`):
```yaml
topic_weights:
  "Decision": 1.5
  "Status Update": 0.8

content_patterns:
  - pattern: "(?i)\\b(decided|approved)\\b"
    weight: 1.6
```

---

## Maintenance

### Manual Catch-Up

Refresh all watched threads:

```bash
python apps/cards-memex/catchup.py
```

### Scripts

Located in `apps/cards-memex/scripts/`:

| Script | Purpose |
|--------|---------|
| `test_api.py` | Full API test suite |
| `verify_api_key.py` | Quick Gemini key check |
| `run_evals.py` | Run evaluation metrics |
| `reindex_watched.py` | Rebuild watched_threads.json |

---

## Troubleshooting

### Bot doesn't respond in DMs

1. Check `im:write` scope is added
2. Reinstall app after adding scopes
3. Verify tokens in `.env`

### Reactions not working

1. Check `reactions:read` scope
2. Ensure user is Curator or Teacher for L2

### Classification failing

1. Check `role.yaml` format
2. Verify Gemini API key

---

## Security

- ✅ `.env` files gitignored
- ✅ ChromaDB data gitignored
- ✅ Role-based access control
- ✅ Feedback weights prevent gaming

---

## Development

```bash
# Run tests
python apps/cards-memex/scripts/test_api.py

# Run evals
python apps/cards-memex/scripts/run_evals.py

# Lint
pip install ruff && ruff check .
```

### Architecture Notes

- `memex-core` is a reusable library (multi-bot capable)
- `apps/cards-memex` is the Cards Strategy implementation
- Embeddings: Google `text-embedding-004`
- LLM: Gemini 2.0 Flash

---

## License

This project is licensed under the [MIT License](LICENSE).
