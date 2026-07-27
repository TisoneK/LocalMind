# Notes: adr-8-agent-centric-routing (append-only while the feature is alive)

Feature-scoped findings, attempts, dead ends — the detail that would
otherwise bloat the global logs. Facts that outlive the feature go to
their real domain: architectural decisions → `plans/decisions.md`,
user preferences → `user/preferences.md`, environment facts →
`system/environments.md`, protocol friction → `flaws/log.md`.

<!-- TEMPLATE — copy below the last entry:
---
## YYYY-MM-DD — <agent> / <model> (Session N)
<findings, attempts, dead ends — detail that would otherwise bloat the
global logs. Facts that outlive the feature go to their real domain.>
-->

---
## 2026-07-27 — Super Z / GLM-5.2 (Session 34)

Feature directory created. No implementation attempted this session —
this was the scaffolding session (Session 34 = standing-Target switch
from ADR-5 to ADR-8 + feature-scoped memory seeded). The
architectural target itself was captured in the prior session
(Session 33, ADR-8 proposed — see `.context/memory/plans/decisions.md`
ADR-8 for the full five-principle + four-phase plan).

Three observations from this initialization session:

1. **The existing partial directory structure already does half of
   Phase 1.** `backend/src/agents/{coding,research,browser,direct}/`
   each already have `__init__.py` + `context_builder.py` +
   `is_done.py` + `tools.py` (per the Session 15-18 build-out per
   the `agent-loop-closed-loop` manifest). What's MISSING from each
   directory is: the agent CLASS itself (`agent.py` — currently lives
   as a sibling standalone module like `coding_agent.py`), the
   workflow file (`workflow.md` — currently lives in
   `backend/data/workflows/<name>.md`), the persona (`persona.md` —
   currently inline in `prompts.py:_PERSONA_MAP`), and the per-agent
   `tests/` directory. **Phase 1 is mostly "move the class + workflow
   + persona INTO the directory that already exists for them."**
   Quick structural refactor — should ship in one session.

2. **The Session 33 backlog item "Wire `build_context()` into
   `BaseAgent.run()`" IS ADR-8 Phase 2 verbatim.** No need to re-file
   it — when Phase 2 starts, that backlog item gets marked in-progress.
   The `tasks/backlog.md` entry already lists the four files to touch
   (`base_agent.py`, `agents/coding/context_builder.py`,
   `core/agent/loop.py`, `core/agent/prompts.py`) and the four
   sub-steps. Phase 2 is fully specified — just needs the real-model
   smoke test plan. The other Session 33 backlog item ("Make
   `AgentLoop.run()` respect `agent_config.max_iterations`") is also
   Phase 2 work — fold it in. Both backlog items become Phase 2's
   acceptance criteria.

3. **The two-system fragmentation (BaseAgent vs SubAgentType) is
   Phase 1's hidden work.** Per ADR-8's "Current state (pre-ADR-8)"
   section: `core/agent/sub_agent.py` has its own agent types (CODER,
   RESEARCHER, WRITER, OPERATOR, ANALYST) with its own registry and
   execution path — completely decoupled from the `BaseAgent`
   subclasses. ADR-8 Phase 1 unifies these — but the ADR's "Current
   state" notes the SubAgentType agents "should be `agents/coder/`,
   `agents/researcher/`, etc. (or merged into the existing agents
   per Phase 1)." **Decision needed at Phase 1 start:** merge
   SubAgentType into the existing BaseAgent subclasses (CODER →
   CodingAgent, RESEARCHER → ResearchAgent, WRITER → new
   WritingAgent?, OPERATOR → DirectAgent, ANALYST → ?) OR keep them
   as separate thin agent directories. The `agent-loop-closed-loop`
   feature manifest didn't resolve this — it focused on the BaseAgent
   side. Recommend: **start by merging** (CODER → coding, RESEARCHER
   → research, OPERATOR → direct) and treat WRITER + ANALYST as new
   agent directories to seed later if a use case appears. The merge
   is non-breaking if the SubAgentType execution path stays — it's
   just a registry consolidation. Defer the SubAgentType execution
   path removal to Phase 3 (agent-initiated delegation replaces it).
