# Current Task (overwrite each session)

Holds exactly one task — the one being worked on right now. Set it at
session start (protocol Step 3), clear it at session end (Step 15). If
you find a stale in-progress entry here, a prior session died mid-task —
check its session entry and backlog before starting.

- **Session:** —
- **Feature:** none — no session in progress (Session 34 Phase 3 complete: agent-initiated delegation via the `delegate` tool. Any agent with `delegate` in its toolset (CodingAgent, ResearchAgent, BrowserAgent — NOT DirectAgent) can call `delegate(target_agent='...', task='...')` to hand off a sub-task. Recursion depth capped at 2, wall-clock cap 120s per delegation. Adapter passed through `dispatch_with_retry()` via contextvar. 465 tests pass (445 + 20 new Phase 3 delegation tests). Real-model smoke test 4/4 pass on Zen/deepseek-v4-flash-free — delegation actually ran end-to-end against the real model. SubAgentType merge deferred (Phase 3 ships the primitive; SubAgentType is the OLD delegation system, both coexist). Phase 4 (task-type classifier) is next — the FINAL phase of ADR-8. See `.context/memory/features/adr-8-agent-centric-routing/notes.md` for the Phase 3 implementation record + Phase 4 entry points.)
- **Task:** none
- **Status:** idle
