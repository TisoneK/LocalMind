# Review — 2026-09-15 — Zuri (S004) — per-category context-usage breakdown

## What happened

The supervisor pointed at ZCode's "Context windows" stats panel (MCP tools
39.5%, system tools 38.3%, messages 15.9%, ...) and noted LocalMind lumps
all context into one number. This session built the equivalent: the
occupancy meter in the chat header is now clickable and opens a
per-category breakdown of the last model call — system prompt, turn
context, tool schemas, conversation history, current message, tool
results, and loop injections, each with its token count and share.

Also: synced the vendored protocol core 1.1.1 → 1.1.3 (patch releases:
harvest path fix + prune-marker scoping; no migration steps) and
registered the feature in the office's feature system.

## What shipped

- `c7414ee1` — backend: `core/agent/context_breakdown.py` estimates each
  category from the exact message list + tool-schema payload the loop
  built for the call (same tiktoken counter the budgeting path uses),
  then scales the shares so they sum to the provider's real
  `prompt_tokens`. Wired into the agent loop's execute path; rides the
  existing usage dict through `turn_complete` and the `metrics` event.
  Observability only — the call payload is never mutated, and a failure
  in the estimator is swallowed (logged, call unaffected).
- `d3d861c4` — frontend: meter click opens the panel (shares sorted by
  size, bars, honest footnote that per-category numbers are estimates
  while the total is exact). Turns that never reach the loop (greetings,
  fast-path answers) leave the meter unclickable rather than showing
  fabricated categories.
- `842d0e7d` — changelog entry (plain language).

## Verification

- **Live (the bar):** isolated server on 8765, real provider
  **zai/glm-4.5-flash**, prompt "What is the weather in Nairobi today?"
  (7 LLM calls, tool loop): `turn_complete` carried
  `context_breakdown = {system_prompt: 1963, turn_context: 709,
  tool_schemas: 2853, current_message: 12, tool_results: 654,
  turn_additions: 361}` — sum **6552 = provider-reported
  prompt_tokens exactly**. The interesting number is already visible:
  the tool catalogue alone is ~44% of that call's context.
  Evidence: `scratch/sse-breakdown-weather.sse`,
  `scratch/server-breakdown-zai.log`.
- **Before/after:** prior-session SSE artifacts (old code) contain zero
  `context_breakdown`; the new trace carries it scaled.
- **Bankofai (the primary live-test provider) is QUOTA-EXHAUSTED** —
  every call returns 400 `credit insufficient balance: balance=0`. Not
  a rate limit; the account balance is zero. The owner needs to top it
  up or re-key before the next session that depends on the primary
  provider. The zai fallback carries the verification above.
- **Unit:** 10 new backend tests (`tests/core/test_context_breakdown.py`);
  2 new frontend hook tests; existing usage/metrics/chat/agent suites
  green (66 + 30 in the touched areas); tsc clean; ruff clean.
- **Not verified:** the second live prompt ("what time is it") hit a zai
  429 before finishing — one clean tool turn is the live evidence.
  The Electron app itself was not relaunched (the user's instance runs
  on its own); the UI change is proven by component wiring + hook tests,
  not a screenshot of the running app.

## Findings along the way

1. **`LOCALMIND_ADAPTER` env var does NOT override the settings file.**
   The scratch tracehome's `settings.json` pins `adapter`, and it wins —
   a harness run with `LOCALMIND_ADAPTER=zai` still hit bankofai.
   Live-testing docs say "provider/model is set in the settings file"
   but don't warn the env var is dead on arrival. Logged as an
   inefficiency so the next agent edits the file instead.
2. **1438 ledger-vocabulary leaks sit in product comments** (ADR
   numbers, bug IDs, session numbers) — a systemic legacy pattern, not
   a drive-by fix. Filed as `B-2026-09-15-1`; Baraka (S005) claimed the
   sweep the same day (their check-in landed mid-session; coordination
   note emitted, main tree left with them for the sweep).
3. The dedicated `{"type":"metrics"}` SSE re-emit never appears in the
   stream — PRE-EXISTING (old and new traces alike, so the final flush
   evidently drains `turn_complete` through a path that skips the
   re-emit; mechanism not chased). Harmless here since the frontend
   reads the breakdown from `turn_complete` directly. Not worth its own
   backlog row until someone needs the metrics event.

## Open items

- `B-2026-09-15-1` — the vocabulary sweep (Baraka, in progress).
- bankofai quota — owner action (top up / re-key).
- Optional follow-up for the breakdown feature: persist the breakdown
  with per-turn metrics (today it's live-only; a reload loses the
  panel's data until the next turn).
