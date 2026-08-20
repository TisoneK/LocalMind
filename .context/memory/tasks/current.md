# Current Task

**Status:** IDLE — Session 314 (anti-hedging detector + recovery nudge context) shipped.

## Session 314 outcome
Fixed the user's live transcript failure: model had 8 web_search results with weather data but answered "Would you like me to get the current weather from weather-atlas.com?" — a non-answer after real work.

Three fixes:
1. **Anti-hedging detector** (`answer_hedges_after_evidence`): fires when tools ran + answer contains a hedge phrase ("Would you like me to...", "Which source..."). Injects a [HEDGE] re-prompt forcing the model to synthesize or fetch, not ask. One-shot bounded, parent-scoped, iteration-capped.
2. **Recovery nudge includes the user's question**: the old generic nudge caused the model to lose context ("I don't have any information about what the original task was"). Now includes `The user's request was: "<original question>"`.
3. **Parent contract anti-hedging steering**: added an "Anti-hedging rules" section to the parent contract.

13 new tests; 2055 broad regression pass (0 failures); ruff clean.
Live trace on z.ai/glm-4.5-flash: recovery nudge with context working (model continued through 5 iterations, ran web_search twice). Hedge detector unit-tested but not live-fired (model hit empty-response before hedging).

## Next
- **B-2026-08-20-10 (High):** MiniMax XML interception conflicts with prose-commitment detector — still open from Session 313.
- **B-2026-08-20-11 (Medium):** 429 rate-limit produces empty answer bubble.
- **B-2026-08-20-9 (Low):** shell tool JSON-wrapped command hint.
- Live-verify the hedge detector on a real hedging answer (needs faster provider).

**Feature:** none (idle)
**ADR:** ADR-54 (ParentSession), ADR-53 (Parent-only), ADR-52 (warm kernel)
**Review:** `.context/memory/reviews/2026-08-20-review-80.md`
