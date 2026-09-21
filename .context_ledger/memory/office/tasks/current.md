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

- **Session:** 2026-09-21 — Mosi / deepseek-flash (ZCode)
- **Feature:** state-engine
- **Task:** the engine selection + Explorer, the standalone-engine extraction (ADR-72), and the Simulator slice (predict an action that must not be performed)
- **Status:** done
