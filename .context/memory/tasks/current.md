# Current Task

**Status:** IDLE — Session 308 (B-2026-08-20-7) implemented + unit-verified; backstop finding recorded.

## Session 308 outcome
- Implemented `_post_loop_synthesis_from_evidence()` in `core/agent/loop.py` + wired into the empty-response fallthrough path. Fires when tools ran + observation_log non-empty + final text empty. Does NOT count against the recovery budget.
- 7 new tests; 1010 broad regression pass; ruff clean.
- Live-verified on z.ai/glm-4.5-flash (2 traces): the B-2026-08-18-11 reasoning rescue fired FIRST and produced real answers (327 chars on trace 2). The post-loop synthesis is a **backstop** for when there's no reasoning buffer — unit-tested but the specific backstop case wasn't exercised live (reasoning rescue handled it first).
- **New finding (B-2026-08-20-9):** the shell tool's error message when given a JSON-wrapped command could suggest "pass the command as a plain string." The model called `shell({"action":"execute","command":"hostname"})` which failed; a helpful error would have let it retry with `shell("hostname")`.
- review-75 records the implementation + live evidence + the backstop finding.

## Next: recovery & speed focus (user directive)
The live traces show z.ai/glm-4.5-flash takes ~30s/iter × 6 iters = ~180s per tool-bearing turn, and the recovery cap (2/turn) is hit frequently. Next sessions should focus on:
- **B-2026-08-20-4:** frontend parent_ready indicator (quick UX win, then return to recovery/speed)
- **Raise `_MAX_EMPTY_REASONING_RECOVERIES`** from 2 to 3 for parent turns (the recovery cap is too tight for weak models)
- **B-2026-08-17-10:** overlap init LLM call with memory retrieval (latency win)
- **B-2026-08-17-11:** fold classify + first action (3 calls → 2, biggest latency win, risky — needs live A/B)

**Feature:** none (idle)
**ADR:** ADR-54 (ParentSession), ADR-53 (Parent-only), ADR-52 (warm kernel)
**Review:** `.context/memory/reviews/2026-08-20-review-75.md`
