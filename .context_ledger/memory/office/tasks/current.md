# Current Task (overwrite each session)

Holds exactly one task — the one being worked on right now. Set it at
session start (protocol Step 3), clear it at session end (Step 15). If
you find a stale in-progress entry here, a prior session died mid-task —
its roster row (if left behind) says who was here; check the session
entry and backlog before starting.

- **Session:** 2026-10-29 — Rafael / Opus 4.8 (S032)
- **Feature:** trajectory view → projection of the record — `docs/reference-harness-gap-inventory.md` rows B + G (1 of 3 parallel worktree sessions)
- **Task:** the agent run tree + phase strip are now derived by one deterministic reducer (`frontend/src/lib/localmind/turnProjection.ts`) from the turn's recorded obs stream — the same projection the backend persists and a reload renders — replacing the imperative live accumulator in `useLocalMind.ts`; a cross-language contract test pins the two ports together; `has_content` now requires real work so a direct turn shows no run node on any path (live == reload).
- **Status:** done — FE 660/660 (tsc+eslint clean), backend 3749 passed / 2 skipped (ruff clean), live proof PASS (`scripts/live_test_trajectory_projection.py`, fake + `--real deepseek`). Committed `14e18caa` on branch `claude/trajectory-projection-13b286`. Follow-ups B-2026-10-29-1 (flat tool-pills) and B-2026-10-29-2 (async-suite config flake). Awaiting owner review / merge.
