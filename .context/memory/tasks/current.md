# Current Task (overwrite each session)

Holds exactly one task — the one being worked on right now. Set it at
session start (protocol Step 3), clear it at session end (Step 15). If
you find a stale in-progress entry here, a prior session died mid-task —
check its session entry and backlog before starting.

- **Session:** none (idle)
- **Feature:** none
- **Task:** none
- **Status:** idle

---

## Handoff Notes (Session 49, 2026-07-31)

The gap analysis (`.context/memory/reviews/2026-07-31-review-6.md`) is
8/10 complete. The next priority is:

**B-2026-07-31-4 — Browser upgrade (High)**
- Audit `backend/src/tools/browser_agent.py` against the 10-point capability list
- Current description claims: navigate, click, fill, scroll, screenshot, execute JS
- Likely missing: inspect DOM, inspect network, read console
- Wire `diagnostics` into BrowserAgent's tools if useful
- See `.context/memory/sessions/SUMMARY.md` for the full session history

**Before starting any new work:**
1. Read `.context/kickoff.md` and follow the protocol
2. Read `.context/memory/workflows/active.md` for the standing target
3. Read `.context/memory/reviews/2026-07-31-review-6.md` for gap context
4. Run `cd backend && source .venv/bin/activate && python -m pytest ../tests/agents/ ../tests/tools/test_diagnostics.py ../tests/tools/test_git_tool.py ../tests/tools/test_process_tool.py -q` to verify 335 tests still pass
