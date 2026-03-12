# twin-brain

**A RAG-powered Slack bot that acts as a "second brain" for your team.** It watches important threads, indexes them into a vector database with AI-powered classification, and answers natural-language questions with cited sources — learning from human feedback to improve over time.

**Tech stack:** Python · Google Gemini · ChromaDB · Slack Bolt · Pydantic · Jinja2

### Highlights

- **Retrieval-Augmented Generation** — semantic search + LLM reranking over a ChromaDB vector store
- **Two-level reinforcement learning** — weighted feedback (L1) drives retrieval boosting (L2) so high-quality threads surface naturally
- **Three-role RBAC** — Curators, Teachers, Users with differentiated permissions and feedback weights
- **Eval framework** — golden dataset, LLM-as-judge, precision/recall/MRR metrics
- **Config-driven architecture** — YAML configs + Jinja2 prompt templates, no code changes needed for tuning
- **Monorepo** — reusable core library (`memex-core`) separated from the application layer (`your-twin-brain`)

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
# 1. Create a Slack app from the manifest (see Setup section below)
# 2. Get a Gemini API key from https://aistudio.google.com/app/apikey
# 3. Run interactive setup (installs deps, validates tokens, writes .env)
python setup.py
# 4. Start the bot
bash apps/your-twin-brain/run.sh
```

---

## Architecture

```
twin-brain/
├── apps/your-twin-brain/       # Application Layer
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
│   ├── src/twin_brain/         # Python package
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

### 2. Create Slack App (one-click with manifest)

1. Go to [Slack API Apps](https://api.slack.com/apps)
2. **Create New App** → **From a manifest**
3. Select your workspace
4. Paste the contents of [`apps/your-twin-brain/slack-app-manifest.yaml`](apps/your-twin-brain/slack-app-manifest.yaml)
5. Click **Create** → **Install to Workspace**

This pre-configures all scopes, Socket Mode, and event subscriptions automatically.

After install, grab these two tokens:
- **Bot Token** (`xoxb-...`): OAuth & Permissions page
- **App-Level Token** (`xapp-...`): Basic Information → App-Level Tokens (create one with `connections:write` scope)

### 3. Get a Gemini API Key

Go to [Google AI Studio](https://aistudio.google.com/app/apikey) and create a key.

### 4. Run Interactive Setup

```bash
python setup.py
```

The setup wizard will:
1. Install Python dependencies
2. Prompt for your Slack tokens and Gemini key (with live validation)
3. Prompt for Curator and Teacher Slack user IDs
4. Write the `.env` file

**Get User IDs:** Slack profile → `...` → Copy member ID

<details>
<summary>Manual .env setup (alternative)</summary>

Copy the example and fill in your values:

```bash
cp apps/your-twin-brain/.env.example apps/your-twin-brain/.env
```

</details>

---

## Running the Bot

### Start

```bash
bash run.sh
```

Expected output:

```
⚡️ twin-brain Bot - Startup Sequence
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

All config in `apps/your-twin-brain/config/`:

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
python apps/your-twin-brain/catchup.py
```

### Scripts

Located in `apps/your-twin-brain/scripts/`:

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
python apps/your-twin-brain/scripts/test_api.py

# Run evals
python apps/your-twin-brain/scripts/run_evals.py

# Lint
pip install ruff && ruff check .
```

### Architecture Notes

- `memex-core` is a reusable library (multi-bot capable)
- `apps/your-twin-brain` is the default application implementation
- Embeddings: Google `text-embedding-004`
- LLM: Gemini 2.0 Flash

---

## License

This project is licensed under the [MIT License](LICENSE).
