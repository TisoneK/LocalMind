# Current Task

**Status:** IDLE — Session 315 (clean user-facing fallback) shipped.

## Session 315 outcome
Fixed the user's live transcript failure: the chat bubble showed raw harness internals ("I ran the requested tools but couldn't synthesize... What to try next: Check the outputs above") instead of a clean answer.

Three fallback paths in `loop.py` were dumping `_summarize_trace_for_user` (raw tool-call list + debug advice) directly to the user when synthesis failed. All three now:
1. Try ONE more synthesis retry with thinking OFF before giving up.
2. If that fails, yield a CLEAN message: "I found the information you asked for, but I'm having trouble putting it into a clean final answer right now. The search results and tool outputs are in the Actions panel above — take a look, or ask me again and I'll retry."

The raw tool evidence (shell calls, search results, outputs) is still available in the Actions panel — the chat bubble just stays clean.

8 e2e/unit tests updated to assert the new clean contract. 2055 broad regression pass (0 failures); ruff clean.

## Next
- **B-2026-08-20-10 (High):** MiniMax XML interception conflicts with prose-commitment detector.
- **B-2026-08-20-11 (Medium):** 429 rate-limit produces empty answer bubble.
- **B-2026-08-20-9 (Low):** shell tool JSON-wrapped command hint.
- The synthesis retry (fix #1) should rescue many turns that previously fell to the clean fallback — live-verify on z.ai with the weather task.

**Feature:** none (idle)
**ADR:** ADR-54 (ParentSession), ADR-53 (Parent-only), ADR-52 (warm kernel)
**Review:** `.context/memory/reviews/2026-08-20-review-81.md` (to be written)
