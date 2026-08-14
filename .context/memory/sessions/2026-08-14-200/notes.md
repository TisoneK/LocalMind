# Session 200 Notes — Legacy Delegation Routing Removal

Kickoff baseline: core 0.5.0 verified/current; main aligned with origin; full
CI 1759 green before changes.

Trace:

- `_pipeline.py` imported `SubAgentRegistry`, `decompose_task`,
  `execute_sub_tasks`, and `should_use_sub_agents()` inside the agent-intent
  branch.
- The heuristic could intercept a complex-looking request before the parent
  AgentLoop, pay for a separate decomposition call, run legacy direct-chat
  sub-agents, synthesize their prose, and return without the selected ADR-8
  agent ever seeing the request.
- No other production code imported `core.agent.sub_agent`; its remaining
  references were old P11 tests and stale documentation.
- The modern path selects an agent by `primary_domain`, runs `BaseAgent.run()`
  which delegates to `AgentLoop.run()`, and lets the model call scoped
  delegation tools when cross-domain work is needed.

Implementation:

- Removed the entire legacy branch and deleted `core/agent/sub_agent.py`.
- Kept the modern parent-agent delegation tools unchanged.
- Replaced legacy framework tests with routing regressions for module removal
  and delegation-capable Coding/Research selection.
- Updated architecture/instruction documentation and marked B-2026-08-14-1
  complete.

Validation: focused suites 110 passed; full CI 1753 backend tests passed, Ruff
and tsc clean, ESLint 0 errors / 64 existing warnings; backend legacy-symbol
search returned zero matches.
