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

- **Session:** 2026-10-31 — Zara / GLM (Z.ai sandbox)
- **Task:** Fix the renderer crash from the owner's screenshot: `Cannot read properties of undefined (reading 'retryAttempts')` — locate the unguarded read, add a failing test, fix, run the frontend suite.
- **Status:** in-progress
