# Rapid Iteration Guide

## Quick Reference: Where to Edit

### 🎨 Response Format Changes

| Change | File to Edit | Function/Section |
|--------|--------------|------------------|
| Answer length limits | `libs/memex-core/memex_core/formatters/response_formatter.py` | `_truncate_answer()` |
| Confidence messages | `libs/memex-core/memex_core/formatters/response_formatter.py` | `_apply_confidence_prefix()` |
| Staleness warnings | `libs/memex-core/memex_core/formatters/response_formatter.py` | `_apply_staleness_warning()` |
| Empty state message | `libs/memex-core/memex_core/formatters/response_formatter.py` | `get_empty_message()` |
| Error messages | `libs/memex-core/memex_core/formatters/response_formatter.py` | `get_error_message()` |
| Thinking messages | `libs/memex-core/memex_core/formatters/response_formatter.py` | `get_thinking_message()` |
| Citation format | `libs/memex-core/memex_core/formatters/citation_formatter.py` | `_format_inline()` / `_format_footer()` |
| Max citations | `config/output.yaml` | `citations.max_citations` |
| Max answer length | `config/output.yaml` | `length.max_chars` |
| Confidence threshold | `config/output.yaml` | `confidence.threshold` |

**Test command:** `python scripts/test_harness.py format "your answer text"`

**Test with low confidence:** `python scripts/test_harness.py format "answer" --confidence 0.3`

**Test staleness warning:** `python scripts/test_harness.py format "answer" --days-old 45`

---

### 🏷️ Classification Changes

| Change | File to Edit | Section |
|--------|--------------|---------|
| Available themes | `config/role.yaml` | `themes:` |
| Available topics | `config/role.yaml` | `topics:` |
| Available products | `config/role.yaml` | `products:` |
| Classification prompt | `config/prompts/classify.jinja2` | Full file |
| Classification logic | `libs/memex-core/memex_core/ai/classifier.py` | `classify_thread()` |

**Test command:** `python scripts/test_harness.py classify "your thread text"`

---

### 🔍 Retrieval Changes

| Change | File to Edit | Section |
|--------|--------------|---------|
| Semantic vs recency weight | `config/retrieval.yaml` | `weights:` |
| Recency decay curve | `config/retrieval.yaml` | `recency:` |
| Re-ranking behavior | `config/retrieval.yaml` | `reranker:` |
| Context limits | `config/retrieval.yaml` | `context:` |
| Re-rank prompt | `config/prompts/rerank.jinja2` | Full file |
| Priority weights by topic | `config/priority.yaml` | `topic_weights:` |
| Priority weights by theme | `config/priority.yaml` | `theme_weights:` |

**Test command:** `python scripts/test_harness.py retrieve "your query"`

---

### 💬 Answer Generation Changes

| Change | File to Edit | Section |
|--------|--------------|---------|
| Answer prompt | `config/prompts/answer.jinja2` | Full file |
| Personality/tone | `config/behavior.yaml` | `personality.tone` |
| Answer generation logic | `libs/memex-core/memex_core/ai/generator.py` | `generate_answer()` |

**Test command:** `python scripts/test_harness.py answer "your question"`

---

### 🚫 Gap/Out-of-Scope Changes

| Change | File to Edit | Section |
|--------|--------------|---------|
| Known gaps | `config/gaps.yaml` | `known_gaps:` |
| Out-of-scope topics | `config/gaps.yaml` | `out_of_scope:` |
| Ambiguity handling | `config/gaps.yaml` | `ambiguity:` |
| Staleness warnings | `config/gaps.yaml` | `staleness:` |

---

### 👥 RBAC/Permissions Changes

| Change | File to Edit | Section |
|--------|--------------|---------|
| Curator IDs | `.env` | `CURATOR_IDS` |
| Teacher IDs | `.env` | `TEACHER_IDS` |
| Feedback weights | `config/feedback.yaml` | `weights:` |
| RBAC logic | `src/cards_memex/rbac.py` | Full file |

---

### 💬 UX Messages Changes

| Change | File to Edit | Section |
|--------|--------------|---------|
| Thinking messages | `config/ux.yaml` | `thinking:` |
| Error messages | `config/ux.yaml` | `error_states:` |
| Empty state messages | `config/ux.yaml` | `empty_states:` |
| Greeting message | `config/ux.yaml` | `greeting:` |
| Reaction emojis | `config/ux.yaml` | `reactions:` |

**Test commands:**
- `python scripts/test_harness.py thinking`
- `python scripts/test_harness.py errors`

---

## Testing Workflow

### Before making a change:

```bash
# 1. Test current behavior
python scripts/test_harness.py <command> "test input"

# 2. Make your change in the appropriate file

# 3. Test new behavior
python scripts/test_harness.py <command> "test input"

# 4. Run full API test
python scripts/test_api.py
```

### Safe iteration pattern:

1. **Identify the dimension** you want to change (use this guide)
2. **Find the single file** that owns that dimension
3. **Test in isolation** before running full bot
4. **Make minimal changes** - one thing at a time
5. **Verify** with test harness before deploying

---

## Architecture Principles

### Single Ownership

Each dimension should have ONE owner file:
- Response format → `formatters/response_formatter.py`
- Citations → `formatters/citation_formatter.py`
- Classification → `config/role.yaml` + `prompts/classify.jinja2`
- UX messages → `config/ux.yaml` (values) + `response_formatter.py` (rendering)

### Config vs Code

- **Config files** (YAML): Values that non-developers might tune
- **Code files** (Python): Logic that requires programming

### Library vs App

- **Library** (`libs/memex-core`): Reusable, generic functionality
- **App** (`apps/cards-memex`): Cards-specific behavior, configuration overrides

---

## Common Iteration Scenarios

### "The answers are too long"
→ Edit `config/output.yaml` → `length.max_chars`
→ Or edit `response_formatter.py` → `_truncate_answer()`

### "Low confidence answers aren't qualified enough"
→ Edit `config/ux.yaml` → `success.low_confidence_prefix`
→ Or edit `config/output.yaml` → `confidence.threshold`

### "Staleness warnings are annoying"
→ Edit `config/output.yaml` → increase `staleness.warn_after_days`
→ Or set to a very high value (e.g., 9999) to effectively disable

### "Retrieval is returning old irrelevant threads"
→ Edit `config/retrieval.yaml` → increase `weights.recency`
→ Or decrease `recency.half_life_days`

### "The bot sounds too formal/informal"
→ Edit `config/behavior.yaml` → `personality.tone`
→ Then edit `config/prompts/answer.jinja2` if needed

### "Need to add a new theme/topic"
→ Edit `config/role.yaml` → add to `themes:` or `topics:`

### "Thinking messages are boring"
→ Edit `config/ux.yaml` → `thinking.variants`

---

## Test Harness Commands

| Command | What it tests | Example |
|---------|---------------|---------|
| `format` | Response formatting | `python scripts/test_harness.py format "answer text"` |
| `thinking` | Thinking/loading messages | `python scripts/test_harness.py thinking` |
| `errors` | Error and empty messages | `python scripts/test_harness.py errors` |
| `classify` | Thread classification | `python scripts/test_harness.py classify "thread text"` |
| `retrieve` | Retrieval (no generation) | `python scripts/test_harness.py retrieve "query"` |
| `answer` | Full pipeline | `python scripts/test_harness.py answer "question"` |
| `compare-prompts` | Compare lib vs app prompts | `python scripts/test_harness.py compare-prompts answer` |

### Format command options:
- `--confidence 0.3` - Test low confidence handling
- `--days-old 45` - Test staleness warning
- `--n-results 10` - Number of results for retrieve

