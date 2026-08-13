# Current Task

- **Session:** 178 (2026-08-13)
- **Feature:** adr-18-verification-first-hardening (continuing)
- **Task:** Session 178 of the user's "agentic workflow" target —
  F1 from the Session 176 audit roadmap. Wire the dead
  AgentOrchestrator.replan() into the verify-fail path.
- **Done (178):**
  - Added `orchestrator` + `reformulated_message` kwargs to
    `AgentLoop.run()` and `BaseAgent.run()`.
  - `_acceptance_gate_at_final_answer` now calls
    `orchestrator.replan()` BEFORE the legacy `_replan_for_gate`
    fallback when an orchestrator is provided.
  - Defensive: raised replan is swallowed.
  - `orchestrator_replan_start/_done/_failed` obs events now fire
    for real (emitted from the loop side).
  - Wired in `_pipeline.py` at all 3 call sites.
  - 5 new tests in `tests/core/test_orchestrator_replan_wiring.py`.
- **Next:** Session 179 — F3 Structured Planner DAG. New
  `core/agent/planner.py` returning `list[PlanNode]` with
  `{subgoal, depends_on, success_criteria, token_budget,
  iter_budget}`. Extend TaskState to track per-node state.
