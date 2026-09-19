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

- **Session:** 2026-09-19 — Tariq (S020) / not exposed to the session (Freebuff desktop)
- **Task:** B-2026-09-15-15 — passive context awareness: build the user/env profile from incidental conversation signals (no "remember this" trigger); constraints are -3's durability policy and -4's keyed mechanics; ADR-64 visible-write rule applies
- **Status:** in-progress
