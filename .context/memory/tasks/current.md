# Current Task

- **Session:** 177 (2026-08-13)
- **Feature:** adr-18-verification-first-hardening (continuing)
- **Task:** Session 177 of the user's "agentic workflow" target —
  implement F2 (Goal Interpreter) from the Session 176 audit roadmap.
- **Done (177):**
  - New `backend/src/core/agent/goal_interpreter.py` (~330 LOC).
    Two-tier: LLM criteria win; when omitted, derive 1-3 deterministic
    checkable criteria per intent from `intent + first tool args`.
  - Wired into `engine/_pipeline.py:2542-2570` — falls through to
    the interpreter when `_reused_criteria` is empty.
  - 18 new tests in `tests/core/test_goal_interpreter.py`.
  - Engine-level integration smoke (4 cases) — derived criteria
    verified checkable by `criteria_gate` against real tool evidence.
- **Next:** Session 178 — F1 Wire `AgentOrchestrator.replan()`.
  Replace the self-contained `_replan_for_gate` LLM call in
  `loop.py:3931` with `orchestrator.replan(failed_step, observation)`
  so the orchestrator sees the failure and can re-route to a
  different agent (e.g. coding → debugger).
