# Current Task (overwrite each session)

Holds exactly one task — the one being worked on right now. Set it at
session start (protocol Step 3), clear it at session end (Step 15). If
you find a stale in-progress entry here, a prior session died mid-task —
check its session entry and backlog before starting.

- **Session:** —
- **Feature:** none — no session in progress (Session 32 raised MAX_ITERATIONS from 3 to 8 + made it configurable; made fallback messages say "iteration limit reached" when hit_limit is True instead of guessing "overload"; added the universal "check before acting" safety workflow. See `.context/memory/reviews/2026-07-27-review-3.md`.)
- **Task:** none
- **Status:** idle
