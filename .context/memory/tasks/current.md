# Current Task

**Status:** IDLE — Session 349 shipped the B-2026-08-20-20 fix (deepseek 500-chunk reasoning cap → empty-reasoning recovery). **The backlog is now EMPTY.**

## Session 349 outcome — reasoning-capped streams route into the empty-reasoning recovery, not the provider-error path

- **Root cause (code, not guess):** the loop's empty-reasoning recovery (Session 256/310) already handled a CLEAN thinking-only stream. The real gap was in the adapter: after Phase 1 broke at the 500-chunk reasoning cap, Phase 2b RESUMED the same still-open httpx stream with no bound (`if not _phase1_exhausted` only). A model stuck in a thinking loop keeps streaming reasoning → the tail read runs until the httpx timeout errors the turn → `has_error=True` → generic provider-error fallback (the Session 323 trace's ~210-char message). Simulated both shapes to confirm: clean-end → recovery ✓, error-end → provider-error ✗.
- **FIX (`src/adapters/openai_compat.py`):** `_reasoning_cap_hit` flag set at the 500-chunk cap break; Phase 2b's tail gate becomes `if not _phase1_exhausted and not _reasoning_cap_hit:` → the cap break yields the buffered reasoning + a CLEAN `done=True` (no error) → the loop's empty-reasoning recovery fires (nudge with the user's original question, thinking forced OFF). Real errors after the cap still take the error path.
- **VERIFIED:** 4 new tests (2 adapter: cap break ends cleanly + does NOT resume the tail [one-shot fake would raise StreamConsumed]; guard: reasoning-then-content still streams the full tail; 2 loop: recovery obs event + original-question nudge, zero error chunks; guard: genuine error still surfaces). Backend **2200 pass / 2 skip / 0 fail**; ruff clean (18 pre-existing E501s in the adapter test file, none mine). LIVE (bankofai, isolated 8765, trace-3 task shape): completed `iter=3, steps=3, hit_limit=False, criteria=3, gate=pass`, real files on disk, zero error/cap events. (The 500-chunk cap itself is model-variance and couldn't be forced live; unit coverage on both sides + no-regression live run is the bar.)
- **Outcome:** the last open backlog item is closed. All of B-2026-08-20-20 and the earlier 2026-08-22 cluster are done.

## Standing notes (not open work)

- **Known flake:** `test_trivial_input.py::test_engine_conversational_followup_uses_direct_chat_context` — pre-existing async flake (unawaited-coroutine warnings), never enters loop.py, passes 3/3 in isolation and in the full run.
- **Session numbering:** numbers collide between machines (this machine's 341–349 vs the mainline's 341–358) — Session 348 flagged a future disambiguation note; harmless for now.
- **User's runtime:** the app backend must be restarted to pick up adapter changes (bankofai path-test workflow).
