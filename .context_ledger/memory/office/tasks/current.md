# Current Task (overwrite each session)

Holds exactly one task — the one being worked on right now. Set it at
session start (protocol Step 3), clear it at session end (Step 15). If you
find a stale in-progress entry here, a prior session died mid-task — its
roster row (if left behind) says who was here; check the session entry and
backlog before starting.

<!-- TEMPLATE — replace everything below this comment:
- **Session:** YYYY-MM-DD — <agent> / <model>
- **Task:** <what is being worked on right now>
- **Status:** in-progress | done | blocked (<blocker>)
-->

- **Session:** 2026-09-18 — Nia (S015) / deepseek-v4-pro → claude-sonnet-5 (owner directive: pull Nia's worktree, finish as her)
- **Task:** AI Connections layer (P-2026-09-18-1) — Settings UI connection manager + /api/models fix, on top of Nia's backend
- **Status:** done — merged to main (`106a612e`), live-verified end-to-end
