# Current Task

**Status:** IDLE — Session 318 (web_fetch redirect crash + tool-failure recovery) shipped + LIVE-VERIFIED.

## Session 318 outcome — LIVE-VERIFIED
Two bugs from the user's live transcript fixed + live-tested on z.ai/glm-4.5-flash:

### 1. web_fetch crashed on redirects (the "sync close on an async stream" error)
- **Bug:** `response.close()` (sync) was called on an httpx async response during redirect handling. This raised "Attempted to call a sync close on an async stream" and crashed web_fetch on every redirect (weather.com 301/302s).
- **Fix:** `await response.aclose()` — the correct async close.
- **Live-verified:** web_fetch no longer crashes on redirects.

### 2. Loop terminated on recovered tool failure (the "Agent loop terminated: tool_failure" error)
- **Bug:** `classify_failure()` returned "tool_failure" if ANY tool step failed — even when the model recovered (tried a different URL, succeeded, produced a real answer). The user saw "Agent loop terminated" AFTER getting the weather answer.
- **Fix:** only classify as tool_failure when the run did NOT produce a final answer (≥ 20 chars). A recovered tool failure with a real answer is a success.
- **Live-verified:** no `agent_loop_failure` emitted; the user gets the clean answer without the termination error.

### Live trace (z.ai/glm-4.5-flash, Cheptais weather task)
- **Real answer produced (212 chars):** "The current weather in Cheptais, Bungoma, Kenya is: Partly Cloudy Night, Temperature: Low 10°C, Precipitation: 20%, Wind: NNE 8 km/h..."
- **No agent_loop_failure** — the "Agent loop terminated" error is GONE.
- **No web_fetch sync-close error.**
- Model ran 8 iterations: web_search → web_fetch → synthesized answer.
- 2066 broad regression pass (0 failures); ruff clean.

## Next
- **B-2026-08-20-10 (High):** MiniMax XML interception conflicts with prose-commitment detector.
- **B-2026-08-20-11 (Medium):** 429 on iter=1 (before any tool) → empty bubble.
- Continue live-testing every change before claiming done.

**Feature:** none (idle)
**ADR:** ADR-54 (ParentSession), ADR-53 (Parent-only), ADR-52 (warm kernel)
**Review:** `.context/memory/reviews/2026-08-20-review-84.md` (to be written)
