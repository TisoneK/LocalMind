# Current Task

- **Session:** 182 (2026-08-13, in progress)
- **Feature:** adr-18-verification-first-hardening (continuing)
- **Task:** Session 182 — F5 Open up WorkspaceOrchestrator to
  substantive intents from the Session 176 audit roadmap.
- **Done (181):**
  - New `AgentPhase` type + `ChatMessage.agentPhases` field.
  - New `AgentPhases.tsx` component.
  - `useLocalMind.ts` handles 8 obs_event types.
  - 32 new tests across 2 test files. Real-model smoke PASSED.
- **Next:** Session 182 — F5 Open up WorkspaceOrchestrator.
  `_should_use_orchestrator` (workspace/orchestrator.py:578)
  excludes essentially every substantive intent (CODE_EXEC, FILE_*,
  SHELL, GIT, VERIFY, REVIEW, DEBUG, ANALYZE, etc.) — only SYSINFO
  survives. The structured depends_on DAG only runs for read-only
  sysinfo, exactly where it's least needed. Let coding/shell
  intents route through the structured DAG path.
