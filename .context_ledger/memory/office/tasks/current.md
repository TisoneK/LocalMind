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

- **Session:** 2026-09-17 — Buffy (S014) / model unknown
- **Feature:** memory-write-path
- **Task:** backlog head — typed memory write path: durability policy in code (volatile refused, stable facts tagged), one row per fact by canonical key, read-back confirmations, deletion by id/prefix/content/key, id-bearing list. Shipped `9ba42626`/`b1a8aa96` + live before/after trace; now in the bookkeeping + gate phase.
- **Status:** in-progress (writing the report/session/closeout and running the exit gate)
