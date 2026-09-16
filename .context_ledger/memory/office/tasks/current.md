# Current Task (overwrite each session)

Holds exactly one task — the one being worked on right now. Set it at
session start (protocol Step 3), clear it at session end (Step 15). If
you find a stale in-progress entry here, a prior session died mid-task —
its roster row (if left behind) says who was here; check the session
entry and backlog before starting.

<!-- TEMPLATE — replace everything below this comment:
- **Session:** YYYY-MM-DD — <agent> / <model>
- **Task:** <what is being worked on right now>
- **Status:** in-progress | done | blocked (<blocker>)
-->

- **Session:** 2026-09-16 — Chemi / Qwen3.8 Flash (S013)
- **Feature:** none
- **Task:** backlog triage — 84 rows vs the new cap of 20 (supervisor directive, deliberately deferred to a dedicated session). Split knowledge/deferred/advisory rows into `tasks/parking-lot.md`, delete done/stale/not-a-task rows, keep ≤20 actionable one-line rows in `tasks/backlog.md`. Resolves the `ledger-mem check` warn that fires every run.
- **Status:** in-progress (owned by S013)
