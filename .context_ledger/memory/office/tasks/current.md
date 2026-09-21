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

- **Session:** 2026-09-21 — Mosi / deepseek-flash (ZCode)
- **Feature:** state-engine
- **Task:** finish the in-app State Explorer + the Classic/State engine selector (the state-driven engine, ADR-71) — the React port of the explorer plus the engine setting wired through config, the API and the UI, with tests and a live run
- **Status:** in-progress
