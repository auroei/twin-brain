# Dimension Registry: Single Source of Truth

> **Rule**: Every dimension has ONE owner file. If you're editing two files for one change, something is wrong.

---

## 🎨 Response Format Dimensions

| Dimension | Owner File | Config File | Test Command |
|-----------|-----------|-------------|--------------|
| Answer length (truncation) | `libs/memex-core/memex_core/formatters/response_formatter.py` → `_truncate_answer()` | `config/output.yaml` → `length.max_chars` | `python scripts/test_harness.py format "long text" --confidence 0.9` |
| Low confidence prefix | `libs/memex-core/memex_core/formatters/response_formatter.py` → `_apply_confidence_prefix()` | `config/ux.yaml` → `success.low_confidence_prefix` | `python scripts/test_harness.py format "text" --confidence 0.3` |
| Staleness warning | `libs/memex-core/memex_core/formatters/response_formatter.py` → `_apply_staleness_warning()` | `config/output.yaml` → `staleness.*` | `python scripts/test_harness.py format "text" --days-old 45` |
| Citation format | `libs/memex-core/memex_core/formatters/citation_formatter.py` | `config/output.yaml` → `citations.*` | N/A (test via full pipeline) |
| Thinking messages | `libs/memex-core/memex_core/formatters/response_formatter.py` → `get_thinking_message()` | `config/ux.yaml` → `thinking.*` | `python scripts/test_harness.py thinking` |
| Error messages | `libs/memex-core/memex_core/formatters/response_formatter.py` → `get_error_message()` | `config/ux.yaml` → `error_states.*` | `python scripts/test_harness.py errors` |
| Empty state messages | `libs/memex-core/memex_core/formatters/response_formatter.py` → `get_empty_message()` | `config/ux.yaml` → `empty_states.*` | `python scripts/test_harness.py errors` |

---

## 🔍 Retrieval/Ranking Dimensions

| Dimension | Owner File | Config File | Test Command |
|-----------|-----------|-------------|--------------|
| **Which info wins (freshness)** | `libs/memex-core/memex_core/ranking/freshness.py` | `config/retrieval.yaml` → `weights.*`, `recency.*` | `python scripts/test_integration.py --test freshness` |
| Superseded thread penalty | `libs/memex-core/memex_core/ranking/freshness.py` → `_apply_supersession_penalty()` | N/A (hardcoded constants) | `python scripts/test_integration.py --test supersession` |
| Feedback boost (L2) | `libs/memex-core/memex_core/ranking/freshness.py` → `_apply_feedback_boost()` | `config/feedback.yaml` → `reinforcement.*` | `python scripts/test_integration.py --test feedback` |
| Priority weights | `libs/memex-core/memex_core/ranking/freshness.py` → `_apply_priority_weight()` | `config/priority.yaml` | N/A |
| Re-ranking (LLM) | `libs/memex-core/memex_core/pipelines/retrieval.py` → `_rerank_results()` | `config/retrieval.yaml` → `reranker.*` | `python scripts/test_harness.py retrieve "query"` |

---

## 🏷️ Classification Dimensions

| Dimension | Owner File | Config File | Test Command |
|-----------|-----------|-------------|--------------|
| Available themes | N/A | `config/role.yaml` → `themes:` | `python scripts/test_harness.py classify "text"` |
| Available topics | N/A | `config/role.yaml` → `topics:` | `python scripts/test_harness.py classify "text"` |
| Available products | N/A | `config/role.yaml` → `products:` | `python scripts/test_harness.py classify "text"` |
| Classification prompt | N/A | `config/prompts/classify.jinja2` | `python scripts/test_harness.py classify "text"` |
| Classification logic | `libs/memex-core/memex_core/ai/classifier.py` → `classify_thread()` | N/A | `python scripts/test_harness.py classify "text"` |

---

## 💬 Answer Generation Dimensions

| Dimension | Owner File | Config File | Test Command |
|-----------|-----------|-------------|--------------|
| Answer prompt | N/A | `config/prompts/answer.jinja2` | `python scripts/test_harness.py answer "question"` |
| Personality/tone | N/A | `config/behavior.yaml` → `personality.tone` | `python scripts/test_harness.py answer "question"` |
| Answer generation logic | `libs/memex-core/memex_core/ai/generator.py` → `generate_answer()` | N/A | `python scripts/test_harness.py answer "question"` |

---

## 🚫 Gap/Scope Dimensions

| Dimension | Owner File | Config File | Test Command |
|-----------|-----------|-------------|--------------|
| Known gaps | N/A | `config/gaps.yaml` → `known_gaps:` | N/A |
| Out-of-scope topics | N/A | `config/gaps.yaml` → `out_of_scope:` | N/A |
| Gap checking logic | `libs/memex-core/memex_core/ai/gap_checker.py` | N/A | N/A |

---

## 👥 RBAC/Permissions Dimensions

| Dimension | Owner File | Config File | Test Command |
|-----------|-----------|-------------|--------------|
| Curator IDs | N/A | `.env` → `CURATOR_IDS` | N/A |
| Teacher IDs | N/A | `.env` → `TEACHER_IDS` | N/A |
| Feedback weights | N/A | `config/feedback.yaml` → `weights.*` | N/A |
| RBAC logic | `apps/cards-memex/src/cards_memex/rbac.py` | N/A | N/A |

---

## 🔄 Iteration Workflow

### Before making any change:

```bash
# 1. Identify the dimension in this registry
# 2. Find the ONE owner file
# 3. Run the test command to see current behavior
# 4. Make your change in ONLY that file
# 5. Run the test command again
# 6. Run integration tests
python scripts/test_integration.py
# 7. Run full API tests
python scripts/test_api.py
```

### Red flags that you're editing wrong:

- ❌ Editing two files for one dimension change
- ❌ Can't find a test command for what you're changing
- ❌ Change requires bot restart to test
- ❌ No clear owner file in this registry

---

## Adding New Dimensions

If you need to add a new configurable dimension:

1. **Choose the owner**: Pick ONE file in `libs/memex-core` that will own this logic
2. **Add config if needed**: Add to appropriate YAML in `config/`
3. **Add test command**: Extend `test_harness.py` or create specific test
4. **Update this registry**: Add row to appropriate table
5. **Write contract test**: Add to `test_contracts.py`

