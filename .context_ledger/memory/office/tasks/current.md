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

- **Session:** 2026-10-26 — Dara / deepseek-flash
- **Feature:** post-close fixes
- **Task:** owner-reported — (1) the assistant error card showed raw provider JSON (`Zen AI returned 400: {...}`), fixed in the error normalizer; (2) the composer stacked a second steering field over the main input, folded into one input whose steer action appears only while a turn is running with text
- **Status:** done
