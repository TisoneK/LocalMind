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

- **Session:** 2026-09-17 — Buffy (S014, extended) / model unknown
- **Feature:** memory-write-path
- **Task:** `B-2026-09-17-1` — route memory READS and DELETES through the deterministic path like writes, so an id-bearing list / forget-by-id is reachable without the model choosing the tool, then live-verify the answer comes from the store. (Follow-up to the shipped write path `9ba42626`/`b1a8aa96`, same session, same codename.)
- **Status:** in-progress (scoping the intent router)
