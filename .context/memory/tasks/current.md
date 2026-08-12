# Current Task

- **Session:** 170 (2026-08-12)
- **Feature:** adr-21-provider-agnostic-errors
- **Task:** ADR-21 P0 — provider-agnostic error normalization, complete.
- **Done (169-170):**
  - **169** (`611e126`): `error_normalizer.py` — `_ERROR_TYPE_RULES` token
    catalog (~45 tokens: OpenAI `insufficient_quota`/`tokens_exceeded`/
    `requests`/`context_length_exceeded`/`invalid_api_key`, Anthropic
    `rate_limit_error`/`overloaded_error`/`not_found_error`/
    `request_too_large`/`api_error`, Zen `FreeUsageLimitError`,
    Azure/gateway codes); `_walk_error`/`_dig_type` envelope walking (error
    dict, double-nested `error.error`, `errors[]`, error-as-string,
    top-level `code`, numeric-code-as-status); classification order token →
    status → keywords → generic; provider-shaped generic errors keep
    `source=model_provider`. Adapter truncation `[:200]` → `[:1000]` (3
    openai_compat sites). 28 new provider-matrix tests.
  - **170**: deepseek-flash review → 4 fixes (529 → server_error, `code`
    fallback for generic type buckets, `raw` capped 2000, numeric-token
    cleanup) + 4 tests. Full backend suite **1468 green**, ruff clean.
    Feature memory updated, everything pushed.
- **Next:** ADR-21 P0 complete. Standing pendings unchanged:
  successful-turn live smokes for ADR-19/20/21 when a provider frees up
  (Zen completions still 429); B-2026-08-12-4 (live two-turn UI check);
  ADR-18 P1-P3; ADR-19 P1-P3.
