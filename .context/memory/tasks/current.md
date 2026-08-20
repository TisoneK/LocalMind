# Current Task

**Status:** IDLE — Session 312 (test fix + turn-init parallelism) shipped; user feedback addressed.

## Session 312 outcome
- **Fixed the failing test** I dismissed in Session 311. `test_shell_command_retains_trailing_output` used bash-specific brace expansion `{1..5000}` but the shell tool runs `/bin/sh` (dash) which doesn't support it. Rewrote the test to use POSIX `seq`+`tr`. Per protocol: fix safe issues found, don't skip them.
- **Maximized turn-init parallelism.** Three changes to `_process_unlocked`:
  1. `_persist_user` is now fire-and-forget (`asyncio.create_task` + `asyncio.to_thread`). The user-message DB write is NOT on the critical path to the first token.
  2. `get_history` folded into the concurrent `_gather_nonessential` task (alongside memory + parent_session). All DB reads + memory retrieval now run in parallel via `asyncio.gather`.
  3. The concurrent task is created FIRST — before cwd sync + adapter setup. Maximum head start.
- **Live audit on z.ai/glm-4.5-flash:** turn-init ~1s (parallelism working), LLM call 8.5s (z.ai API latency — the real bottleneck, cannot control from harness). The user feels "instant" only with a faster provider; the harness now adds <1s on top of model latency.
- 2042 broad regression tests pass (0 failures); ruff clean.
- review-78 records the honest audit + answers the user's three questions.

## Honest answers to user's questions
1. **"Did you actually fix everything?"** — No. I dismissed the failing test. Now fixed.
2. **"Does each process wait for another or work in parallel?"** — Before Session 312: `get_history` and `_persist_user` were serial DB ops blocking the event loop. Now: all DB reads + memory + adapter setup run concurrently via `asyncio.gather` + `asyncio.to_thread`. Verified by live audit.
3. **"User feels the answer is instant / thinking in real time"** — Turn-init is now <1s. The 8.5s bottleneck is the z.ai API itself (provider latency, not harness). Thinking tokens DO stream in real-time via SSE. The only way to get sub-second first-token is a faster provider (Zen, Cerebras, local Ollama).

## Next
- **B-2026-08-17-11 (risky):** fold classify + first action — biggest remaining latency lever (saves one full 8.5s generation on execute turns).
- **B-2026-08-17-12:** create→file_write steering — collapses ~4 LLM calls per create task.
- **B-2026-08-20-9:** shell tool JSON-wrapped command hint.

**Feature:** none (idle)
**ADR:** ADR-54 (ParentSession), ADR-53 (Parent-only), ADR-52 (warm kernel)
**Review:** `.context/memory/reviews/2026-08-20-review-78.md`
