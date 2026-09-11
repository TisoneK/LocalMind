# Current Task

**Status:** IDLE — **Session 469 (Zawadi / glm-5.3-flash, ZCode local, Windows)
COMPLETE (2026-09-11): B-2026-08-25-4 fixed and live-verified.**

**Outcome:** the internal "Worker report — tool execution evidence:" block no
longer reaches the model's own context or its answers. Root cause: the
deterministic user-facing append persisted into assistant messages and flowed
verbatim back through the prompt tail, ParentSession tail, thinker history,
episode distill, memory resolver, and social fast path — the model mimicked
the format into later answers. Fix (`78fadbcc`): one canonical strip helper
beside the format owner in `core/agent/models.py`, applied at all 7
model-facing history feeds and at the loop's full-text emission boundaries
(`_force_final_answer`, `_rescue_final_answer`, both buffered gate-flush
blocks) — the deterministic renderer stays the sole author of the format and
the fallback report still reaches the user. 14 new tests
(`tests/core/test_work_report_strip.py`); changelog `bb9555b1`; review +
release event + backlog line delete `b6203c2a`.

**Verification:** live before/after on bankofai/qwen3.8-flash (isolated 8765,
scratch home, 3-turn same-session scenario with a readback probe) — pre-fix
worktree readback reproduced the internal report verbatim from context;
post-fix, zero model-authored report text (every SSE header occurrence is the
exact deterministic append shape). Full suite 3056 pass; failure set = the 22
documented Windows baseline entries + the tracked date-bomb trio only.
Evidence: `scratch/results-s469-*.json` + matching SSE/server-log captures.

Feature: none
