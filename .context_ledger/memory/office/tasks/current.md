# Current Task (overwrite each session)

Holds exactly one task — the one being worked on right now. Set it at
session start (protocol Step 3), clear it at session end (Step 15). If
you find a stale in-progress entry here, a prior session died mid-task —
its roster row (if left behind) says who was here; check the session
entry and backlog before starting.

<!-- TEMPLATE — replace everything below this comment:
- **Session:** YYYY-MM-DD — <agent> / <model>
- **Task:** <what is being worked on right now>
- **Status:** done | done | blocked (<blocker>)
-->

- **Session:** 2026-10-27 — Kai / GLM (Z.ai) (S005)
- **Feature:** none
- **Task:** setup — pull latest and bring the checkout to a working dev state (core 2.0.4 → 2.2.0, entry points refreshed, guard hooks installed, backend venv on Python 3.13, npm workspace, gates green)
- **Status:** done
