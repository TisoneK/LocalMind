# Current Task

**Status:** IDLE — Session 316 (deterministic evidence extraction) shipped.

## Session 316 outcome
Implemented the user's insight: "the thinking text and other evidence already has all the answers." When synthesis fails, the answer often already exists in the reasoning buffer or tool observations. Added `_extract_answer_from_evidence()` — a DETERMINISTIC extractor that pulls the answer directly from evidence already in hand, with ZERO LLM calls and ZERO latency.

It runs FIRST (before the retry and clean-message fallback) at two synthesis-failure paths:
1. Empty-response fallthrough (reasoning buffer available): extracts the answer sentence from the model's reasoning.
2. `_force_final_answer` empty path: extracts from tool observations (search snippets, shell output).

When extraction succeeds → user sees the answer immediately, no retry, no extra LLM call, no latency. When it fails → falls through to retry-then-clean-message.

11 new tests; 2066 broad regression pass (0 failures); ruff clean.

## The three-layer fallback (priority order)
1. **Deterministic extraction** (Session 316) — zero LLM calls, <1ms. Pulls from reasoning + observations.
2. **Synthesis retry** (Session 315) — one LLM call with thinking OFF. Fresh attempt.
3. **Clean message** (Session 315) — "I found the information... Actions panel... retry."

## Next
- **B-2026-08-20-10 (High):** MiniMax XML interception conflicts with prose-commitment detector.
- **B-2026-08-20-11 (Medium):** 429 rate-limit produces empty answer bubble.
- Live-verify the extractor on z.ai with the weather task.

**Feature:** none (idle)
**ADR:** ADR-54 (ParentSession), ADR-53 (Parent-only), ADR-52 (warm kernel)
**Review:** `.context/memory/reviews/2026-08-20-review-82.md` (to be written)
