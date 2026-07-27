# Current Task (overwrite each session)

Holds exactly one task — the one being worked on right now. Set it at
session start (protocol Step 3), clear it at session end (Step 15). If
you find a stale in-progress entry here, a prior session died mid-task —
check its session entry and backlog before starting.

- **Session:** —
- **Feature:** none — no session in progress (Session 34 Phase 1 complete: ADR-8 agent classes moved INTO their directories at `backend/src/agents/{coding,research,browser,direct}/agent.py`. Backward-compat shims retained at the old `*_agent.py` paths. Registry auto-discovers directories with `agent.py`. 434 tests pass (412 baseline + 22 new Phase 1 layout tests). Real-model smoke test N/A for Phase 1 (pure structural move, no model path touched). Phase 2 (wire `build_context()` into `BaseAgent.run()` — workflow files reach the model — real-model test mandatory) is next. See `.context/memory/features/adr-8-agent-centric-routing/notes.md` for the Phase 1 implementation record + Phase 2 entry points.)
- **Task:** none
- **Status:** idle
