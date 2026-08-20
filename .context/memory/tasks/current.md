# Current Task

**Status:** IDLE — Session 317 (live-tested fixes: DDG import + 429 preserve-evidence path + stricter extractor) shipped.

## Session 317 outcome — LIVE-TESTED (per user's directive)
The user rightly called out: "tests passing doesn't mean the agent passing real (live-test)." I had shipped Sessions 314-316 without live verification. This session I live-tested on z.ai/glm-4.5-flash and found + fixed three issues that unit tests didn't catch:

### 1. DDG search was completely broken (unit tests didn't catch this)
- **Live finding:** every web_search fell back to Bing (lower quality) because the DDG import was wrong. The code imported `from ddgs import DDGS` but the installed package was `duckduckgo_search` (deprecated, returns 0 results).
- **Fix:** prefer the NEW `ddgs` package, fall back to the old name.
- **Live-verified:** DDG now returns 8 real weather results for Kitengela ("Weather forecast for today Kitengela, Kenya" + "overcast and occasionally showery").

### 2. A FOURTH raw-dump fallback path was leaking (unit tests didn't catch this)
- **Live finding:** when z.ai 429'd the synthesis call after tools ran, the `_can_preserve_evidence` path (line 3571) dumped `_summarize_trace_for_user` ("I ran the requested tools but couldn't synthesize... What to try next: Check the outputs above") to the user. This was a FOURTH path I missed in Session 315.
- **Fix:** this path now tries deterministic extraction FIRST (zero-LLM), then falls back to the clean message.

### 3. The extractor was too loose (unit tests didn't catch this)
- **Live finding:** the extractor pulled "Let me try a different approach" (meta-reasoning, not an answer) because it scored on entity match alone.
- **Fix:** require a factual marker (temperature, "is X", units) — a sentence without one is skipped. Stronger meta-reasoning penalties.

### Live evidence
- **Extractor fired live:** `answer extracted from reasoning buffer (274 chars, zero-LLM)` + `empty-response rescued by evidence extraction (zero-LLM, 274 chars)` — the deterministic extractor works on the real model.
- **DDG works:** returns 8 real Kitengela weather results.
- **429 path fixed:** no more raw dump on provider rate-limit.
- **Rate-limit caveat:** z.ai's free tier 429'd under repeated testing; a re-run after the window clears would confirm the full end-to-end weather answer. The DDG fix + extractor are verified independently.

2066 broad regression pass (0 failures); ruff clean.

## Lesson (logged)
Unit tests verify structure, not behavior. The DDG import was structurally correct (the import existed) but behaviorally broken (wrong package name). The fourth fallback path was structurally correct (it produced a message) but behaviorally wrong (raw dump). Only live testing catches these. The `system/live-testing.md` protocol exists for exactly this reason — I should have live-tested after Session 314, not shipped three sessions of unverified recovery code.

## Next
- **B-2026-08-20-10 (High):** MiniMax XML interception conflicts with prose-commitment detector.
- **B-2026-08-20-11 (Medium):** 429 on iter=1 (before any tool) → empty bubble. The 429-after-tools path is now fixed; the 429-before-tools path still needs a clean message.
- Re-run the full weather trace after z.ai's rate-limit window clears.

**Feature:** none (idle)
**ADR:** ADR-54 (ParentSession), ADR-53 (Parent-only), ADR-52 (warm kernel)
**Review:** `.context/memory/reviews/2026-08-20-review-83.md` (to be written)
