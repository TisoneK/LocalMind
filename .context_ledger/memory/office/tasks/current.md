# Current Task (overwrite each session)

Holds exactly one task — the one being worked on right now. Set it at
session start (protocol Step 3), clear it at session end (Step 15). If
you find a stale in-progress entry here, a prior session died mid-task —
its roster row (if left behind) says who was here; check the session
entry and backlog before starting.

- **Session:** 2026-10-29 — Nadia / unknown model id (S031)
- **Feature:** done-rules extension — roadmap §U item 4 (`docs/reference-harness-gap-inventory.md`, row E)
- **Task:** the provider-death completion path is now a named state of the turn contract (`DEGRADED_ANSWER`) with its delivery composed there, not inline in the loop; an unanswered call now leaves a recorded result (`OUTCOME UNKNOWN`, blind re-run forbidden for side-effecting tools) plus a pairing invariant at every iteration head; the batch path no longer lets one raised call kill its siblings; and the parent completion floor spends the bounded replan budget instead of re-asking 19 times.
- **Status:** done — backend 3717 passed / 4 skipped (+22 new) in three sequential batches; the only failures are 23 in `tests/tools` (22 are the documented Windows baseline, and `test_stop_already_stopped` passes in isolation — batch-order flake). `tsc -b --noEmit` clean, eslint clean, live wire proof PASS (`scripts/live_test_done_rules.py`), the three prior live harnesses re-run PASS. §U item 5 (session durability barriers, permission modes, spill fidelity) is the next tier.
