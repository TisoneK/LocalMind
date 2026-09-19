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

- **Session:** 2026-09-18 — Juma (S017) / claude-sonnet-5
- **Task:** B-2026-09-15-14 — self-reflection loop (post-turn "what did I miss" assessment stored as atomic lessons)
- **Status:** done — merged to main (`2cbc447d`), live-verified against a real model (gemini)
