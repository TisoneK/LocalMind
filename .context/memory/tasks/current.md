# Current Task

- **Session:** 168 (2026-08-12)
- **Feature:** adr-20-error-normalization
- **Task:** ADR-20 P0 — canonical error normalization + friendly presentation layer, implemented and live-verified (provider still rate-limited for completions).
- **Done (165-168):**
  - **165** (`f261ef0`): `core/error_normalizer.py` — pure deterministic normalizer;
    parses `{provider} returned {status}: {body}` (openai_compat + ollama
    shapes), digs nested provider JSON (FreeUsageLimitError), classifies into
    canonical codes (rate_limit/auth_error/payment_required/model_not_found/
    context_overflow/timeout/server_error/network_error) with retryable flags
    + friendly provider-agnostic messages; raw kept for debug; internal-source
    override for uploads. 28 tests.
  - **166** (`6cd514f`): SSE boundary — `chat.py` chunk.error emits the
    canonical object; exception path yields a friendly token + canonical error
    + done (Session 31 guarantee kept); uploads use source_hint=internal.
  - **167** (`ca56845`): frontend — `ModelError` type + `ChatMessage.error`;
    hook stores the canonical error object (legacy string fallback kept);
    `ErrorMessage` card (headline, friendly message, provider·status·retryable
    meta, Try again + Switch model via `localmind:open-model-selector`, raw in
    collapsed Technical details); rendered in ChatMessage. 18 new tests;
    vitest 105 green, tsc clean.
  - **168**: full backend suite **1437 green**; deepseek-flash review → 3 fixes
    (canonical passthrough short-circuit, JSON-safe exception raw, friendly
    persisted exception text). Restarted backend; LIVE SMOKE — Zen 429 persists
    for completions BUT the exact user-reported error now emits the canonical
    `rate_limit` object live (friendly message in the UI path, raw confined to
    debug). Success-turn smoke half pending on a live provider.
- **Next:** ADR-20 P0 complete. Standing pendings: successful-turn live smoke
  for ADR-19/20 when a provider frees up (Zen completions still 429);
  B-2026-08-12-4 (live two-turn UI check); ADR-18 P1-P3 (verifier-as-stage,
  failure memory, transitional wiring); ADR-19 P1-P3 (context hierarchy,
  decision ledger, LLM value-scoring).
