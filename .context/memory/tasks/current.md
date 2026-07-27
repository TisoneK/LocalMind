# Current Task (overwrite each session)

Holds exactly one task — the one being worked on right now. Set it at
session start (protocol Step 3), clear it at session end (Step 15). If
you find a stale in-progress entry here, a prior session died mid-task —
check its session entry and backlog before starting.

- **Session:** —
- **Feature:** none — no session in progress (Session 34 Phase 2 complete: build_context() now wired into BaseAgent.run(); agents/coding/workflow.md + agents/research/workflow.md loaded and reach the model via the new `agent_context` section in build_agent_system_prompt(); AgentLoop.run() honors agent_config.max_iterations / max_wall_clock_secs (was dead code). 445 tests pass (434 + 11 new Phase 2 wiring tests). Real-model smoke test ran BEFORE and AFTER code changes (Zen/deepseek-v4-flash-free — 5/5 baseline, 4/4 after). Baseline found Session 31's trailing-tool-role 400 bug is fixed server-side; adapter workaround is now redundant but kept for safety. Phase 3 (agent-initiated delegation, SubAgentType merge) is next. See `.context/memory/features/adr-8-agent-centric-routing/notes.md` for the Phase 2 implementation record + Phase 3 entry points.)
- **Task:** none
- **Status:** idle
