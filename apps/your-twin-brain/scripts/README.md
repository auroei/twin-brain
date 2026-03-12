# twin-brain Scripts

App-specific maintenance, testing, and utility scripts for the twin-brain bot.

## Scripts

### `run_evals.py`

**Purpose:** Evaluate RAG system performance using metrics and LLM-as-judge.

**What it measures:**
- **Retrieval metrics:** Precision, Recall, MRR, F1 Score
- **End-to-end accuracy:** LLM judges if generated answers match expected answers

**Usage:**
```bash
cd apps/your-twin-brain
python scripts/run_evals.py                    # Run all evaluations
python scripts/run_evals.py --retrieval-only   # Only retrieval metrics
python scripts/run_evals.py --e2e-only         # Only end-to-end accuracy
python scripts/run_evals.py --k 5              # Retrieve top 5 results
python scripts/run_evals.py --output results.json
```

**Configuration:**
- Test data: `evals/golden_dataset.jsonl`
- Override with: `--eval-file path/to/custom.jsonl`

---

### `test_api.py`

**Purpose:** Comprehensive test suite for API keys and core functionality.

**What it tests:**
- ✅ Gemini API key (generative AI)
- ✅ Embeddings API
- ✅ ChromaDB connection
- ✅ ChromaDB + Embeddings integration
- ✅ Thread classification

**Usage:**
```bash
cd apps/your-twin-brain
python scripts/test_api.py
```

**When to use:**
- After initial setup
- When debugging API issues
- After changing API keys
- Before committing major changes

---

### `verify_api_key.py`

**Purpose:** Quick verification that Gemini API key is valid and working.

**What it does:**
- Checks if API key exists in `.env`
- Validates key format
- Lists available models
- Tests generation with multiple model versions

**Usage:**
```bash
cd apps/your-twin-brain
python scripts/verify_api_key.py
```

**When to use:**
- Quick API key troubleshooting
- After creating/rotating API keys
- When getting API errors

---

### `query_channel_ids.py`

**Purpose:** Populate missing `channel_id` values in `watched_threads.json` from ChromaDB.

**What it does:**
- Loads watched threads from `data/watched_threads.json`
- Queries ChromaDB for each thread's metadata
- Extracts `channel_id` from metadata
- Updates `watched_threads.json` (creates backup first)

**Usage:**
```bash
cd apps/your-twin-brain
python scripts/query_channel_ids.py
```

**When to use:**
- After migrating from old format (list → dict)
- When `channel_id` values are `null`
- After restoring from backup

**Note:** Requires threads to already exist in ChromaDB with channel metadata.

---

### `reindex_watched.py`

**Purpose:** Rebuild `watched_threads.json` entirely from ChromaDB.

**What it does:**
- Scans all documents in ChromaDB
- Extracts thread IDs and channel IDs
- Rebuilds `data/watched_threads.json` from scratch
- Creates backup of existing file

**Usage:**
```bash
cd apps/your-twin-brain
python scripts/reindex_watched.py
```

**When to use:**
- When `watched_threads.json` is lost or corrupted
- After restoring ChromaDB from backup
- To verify sync between ChromaDB and watched list
- Migration/recovery scenarios

**Warning:** This overwrites `watched_threads.json`. A backup is created automatically.

---

## Common Workflows

### Initial Setup Testing
```bash
cd apps/your-twin-brain
python scripts/verify_api_key.py
python scripts/test_api.py
```

### Recovery from Lost watched_threads.json
```bash
cd apps/your-twin-brain
python scripts/reindex_watched.py
```

### Populate Missing Channel IDs
```bash
cd apps/your-twin-brain
python scripts/query_channel_ids.py
```

### Run Evaluations Before Deployment
```bash
cd apps/your-twin-brain
python scripts/run_evals.py --output eval_results.json
```

---

## Notes

- All scripts should be run from the `apps/your-twin-brain/` directory
- Scripts load `.env` from the app directory (`apps/your-twin-brain/.env`)
- ChromaDB is expected at `data/knowledge_base/`
- Watched threads are at `data/watched_threads.json`
- Evaluation data is at `evals/golden_dataset.jsonl`
- Backups are created automatically when modifying `watched_threads.json`

## Library Functions

The evaluation scripts use generic functions from `memex_core.eval`:
- `evaluate_retrieval()` - Precision, Recall, MRR, F1
- `evaluate_end_to_end()` - LLM-as-judge accuracy
- `calculate_mrr()` - Mean Reciprocal Rank calculation
- `judge_answer()` - Single answer judgment

These can be imported for custom evaluation workflows:
```python
from memex_core import evaluate_retrieval, evaluate_end_to_end
```
