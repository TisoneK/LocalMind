# Current Task

- **Session:** 181 (2026-08-13, in progress)
- **Feature:** adr-18-verification-first-hardening (continuing)
- **Task:** Session 181 — F4 Frontend Phase Visibility from the
  Session 176 audit roadmap.
- **Done (180):**
  - New `core/agent/plan_parser.py` (~260 LOC).
  - New `PlanNode` dataclass + `TaskState.nodes` field.
  - Wired into `AgentLoop.run()` with `plan_nodes_created` +
    `plan_node_advanced` obs events.
  - 27 new tests in `tests/core/test_plan_parser.py`.
- **Next:** Session 181 — F4 Frontend Phase Visibility. Consume the
  now-live backend events in the frontend:
  `agent_loop_gate_passed`, `agent_loop_gate_failed_replan`,
  `orchestrator_replan_start/_done`, `agent_loop_failure`,
  `plan_nodes_created`, `plan_node_advanced`.
