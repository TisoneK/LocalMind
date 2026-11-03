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

- **Session:** 2026-11-03 — Sanaa / GLM (Z.ai sandbox)
- **Task:** B-2026-11-02-2 remainder — the model's own todo_write rewrite: a mid-turn todo_write call diffs against the live panel (dropped rows retire with a reason, new rows append, todo_revised on the record) instead of the silent clear+replace; revised steps carry outcome contracts (model expected_outcome joins the acceptance criteria; the gate replan parses per-step done-when outcomes)
- **Status:** in-progress
