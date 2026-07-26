# Notes: agent-loop-closed-loop (append-only while the feature is alive)

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
## 2026-07-26 — Super Z / GLM-5.2 (Session 13)

Feature directory created. No implementation attempted this session —
this was the scaffolding session (Session 13 = core-0.3.0 preview
adoption + first feature directory seeded). The architectural target
itself was captured in the prior session (Session 12, ADR-5).

Two design refinements surfaced while writing the manifest:

1. **Branch policy vs feature-scoped memory.** The 0.3.0 design's
   concurrency story assumes feature branches (`memory/features/<slug>/`
   travels with the code and merges with it — separate directories per
   feature make concurrent branches naturally conflict-free in memory).
   LocalMind pushes to `main` directly per `workflows/active.md`, so
   the "branches naturally conflict-free" benefit doesn't apply here.
   That's fine — the value for LocalMind is the *archival* story (the
   ledger + the ability to move a feature directory to `archive/` once
   merged, instead of leaving its breadcrumbs forever in
   `tasks/backlog.md` and `agents/sessions.md`), not branch isolation.
   Worth noting in `plans/decisions.md` if ADR-5 ever gets a follow-up
   ADR about branching.

2. **`workspace_state.py` vs `workspace/manager.py` naming collision
   risk.** The existing `backend/src/core/workspace/manager.py` is the
   per-turn scratch directory (TODO.md / CONTEXT.md / inbox / outbox —
   tool I/O isolation within one turn). The new service proposed in
   ADR-5 is `backend/src/core/workspace_state.py` (persistent project
   state across turns — git/diff/test output fed back into context).
   They are siblings, not replacements, but the names are close enough
   that an agent skimming the codebase could conflate them. ADR-5
   already calls this out explicitly ("Do NOT conflate"), and the
   manifest repeats it. If the naming proves confusing in
   implementation, candidates for the new module: `workspace_state.py`
   (current), `project_state.py`, `turn_feedback.py`, `loop_observability.py`.
   Defer the rename decision until implementation reveals actual usage.

---
## 2026-07-26 — Super Z / GLM-5.2 (Session 14)

User provided more architectural context for the same ADR, working
through three options for how `backend/` should be organized. Captured
as ADR-6 (refines ADR-5 — specifies the organizational structure ADR-5
left open).

**The three options explored:**

1. **Multi-harness framework** — `harness/coding/`, `harness/research/`,
   `harness/direct/`, each implementing the same loop shape with
   different context/tools/termination. base.py supplies the abstract
   loop; each harness supplies `build_context()`, `tools`, `observe()`,
   `is_done()`. User rejected the framing: "More like an agent" —
   harnesses are workflow pickers, agents are addressable things.

2. **Single unified agent** — one `agent.py` loop, all tools available
   flat, the model dynamically picks tools per task. Closer to Claude
   Code. User identified the core risk: tool descriptions have to be
   good enough that a gemma3:1b-class model reliably picks the right
   one. With a flat tool surface and a 1B model, wrong-tool selection
   is the likely failure mode.

3. **Multiple distinct agents with shared base** — `agents/base_agent.py`
   + `coding_agent.py` + `research_agent.py` + `browser_agent.py` +
   `direct_agent.py`. Each is a thin subclass supplying its own
   `context_builder`, scoped `tools`, `is_done()`. Shared in base: 5-step
   loop, compaction, streaming, permission checking. User converged
   here: "Like coding agent, research agent, browser agent." Key
   argument: scoped toolset per agent = fewer tools for the small model
   to choose from = more reliable selection. Explicit user selection
   (UI picker) avoids an expensive LLM-based router.

**Decision: option 3.** Captured as ADR-6 with Status: accepted. The
decision rests on three pillars: (a) scoped tools per agent for small-
model reliability, (b) explicit user selection over LLM-based router
(cheaper on gemma3:1b-class hardware, no wasted turns from wrong
classification), (c) shared base_agent.py keeps the 5-step loop +
compaction + streaming + permission checking DRY across agents.

**Implementation order refined.** The manifest's "Next steps" now
recommends promoting the existing `backend/src/tools/browser_agent.py`
to a full agent FIRST — it's already domain-scoped in name, so it's the
smallest-risk first concrete step (no existing coding/research agent to
break). Then extract `base_agent.py` from `agent/loop.py` with
`browser_agent.py` as the first subclass. Then build `coding_agent.py`
+ `workspace_state.py` (highest leverage per ADR-5). Then
`research_agent.py` and `direct_agent.py`.

**Design risk flagged.** Per ADR-6 point 6: tool descriptions are the
real design risk. Even with a scoped toolset per agent, a 1B-class model
needs the tool schema itself to pre-disambiguate. This is an
implementation-time concern but the most likely failure mode — test
early that the model reliably picks the right tool from each agent's
scoped surface. Don't wait until all agents are built to discover the
tool descriptions are too vague.

**No code changes this session** — ADR-6 capture only, same scope
discipline as Sessions 9, 12, 13 (architecture-capture sessions don't
touch product code).

---
## 2026-07-26 — Super Z / GLM-5.2 (Session 15)

First implementation session for this feature. Three architecture-
capture sessions (12, 13, 14) preceded it; the manifest's "Next steps"
was detailed enough that implementation could start immediately.

**What landed:**

Created `backend/src/agents/` package — the structural skeleton ADR-6
calls for:

- `base_agent.py` — abstract `BaseAgent` class + `AgentConfig` dataclass.
  The `AgentConfig` carries the ADR-5 hard caps (`max_iterations`,
  `max_wall_clock_secs`) and the scoped `allowed_tools` frozenset per
  ADR-6. `BaseAgent` defines the abstract interface (`config()`,
  `build_context()`, `is_done()`, `description()`) plus a shared
  `run()` that delegates to the existing `AgentLoop` in Phase 1
  (non-breaking) and a `scoped_tools()` helper that filters the global
  tool list down to the agent's allowlist.
- `registry.py` — name → agent class registry with `register()`,
  `get_agent()`, `list_agents()`, `is_registered()`. The UI picker /
  intent router will call `get_agent(name)` to look up agents.
- `browser_agent.py` — first concrete `BaseAgent` subclass. Supplies
  browser-specific config (15 max iterations, 240s wall clock, scoped
  to `Intent.BROWSE` only), delegates to `browser/` subpackage for
  context/tools/is_done.
- `browser/` subpackage — `context_builder.py` (browser-context header
  + memory facts + orchestrator plan), `tools.py` (`BROWSER_TOOLS =
  {Intent.BROWSE}` — the smallest possible scoped surface, ideal for
  testing the scoped-tools concept), `is_done.py` (Phase 1: always
  returns `(False, "")` — lets existing AgentLoop handle termination).

19 new tests in `tests/agents/test_agents.py` lock in: BaseAgent is
abstract, BrowserAgent config/description/context/is_done/scoped_tools,
registry register/get/list/is_registered/conflict-raises. All 19 pass.
Full suite: 216 pass (197 baseline + 19 new), 0 real ruff bugs (112
E501 pre-existing), mypy error is pre-existing numpy stub issue.

**Design decisions made during implementation:**

1. **Non-breaking Phase 1 delegation.** `BaseAgent.run()` delegates to
   the existing `AgentLoop` rather than hosting the loop body itself.
   This keeps the new abstraction non-breaking — all existing traffic
   continues to flow through `AgentLoop` unchanged. Phase 2 (next
   session) will extract the loop body into `BaseAgent._run_loop()`.
   The `agent/loop.py` docstring documents this phase plan.

2. **The existing `tools/browser_agent.py` stays registered.** The new
   `BrowserAgent` class composes the existing tool — it doesn't replace
   it. The tool continues to be available via the flat `tools/`
   registry; the new agent class is the structural skeleton for
   per-agent scoping. A future session will migrate the routing so
   browser tasks go through `BrowserAgent.scoped_tools()` instead of
   the flat `_filtered_tool_defs()`.

3. **`AgentConfig` carries the ADR-5 hard caps.** `max_iterations` and
   `max_wall_clock_secs` are per-agent, with sensible defaults
   (`DEFAULT_MAX_ITERATIONS = 20`, `DEFAULT_MAX_WALL_CLOCK_SECS = 300`).
   BrowserAgent overrides to 15 / 240 (browser tasks are slow but
   rarely need many iterations). These caps aren't enforced yet in
   Phase 1 (the existing AgentLoop has its own MAX_ITERATIONS); Phase 2
   will enforce them in `BaseAgent._run_loop()`.

4. **`scoped_tools()` is a method, not a property.** It takes the full
   tool list as an argument so the agent can filter against whatever
   the global registry currently has, at call time. This avoids
   ordering issues with tool registration vs. agent construction.

5. **Description quality matters (ADR-6 point 6).** The test
   `test_browser_agent_description_is_concrete` asserts the description
   is >50 chars, mentions "browser" and "click"/"navigate", and
   mentions what it CAN'T do. This locks in the ADR-6 point-6
   requirement that agent descriptions must be concrete enough for a
   gemma3:1b-class model to disambiguate.

**What didn't land (deferred to next session):**

- Loop body extraction (`BaseAgent._run_loop()`) — Phase 2
- Intent router wiring (`model_router.py` → `agents.registry.get_agent()`)
- `coding_agent.py` + `workspace_state.py` — the ADR-5 highest-leverage piece
- `research_agent.py`, `direct_agent.py`
- Context compaction step (B-2026-07-26-2)

The session stayed scoped to "promote browser_agent to a full agent as
the smallest-risk first concrete step" per the manifest's next-steps.
Didn't try to do too much — the loop body extraction is a separate
session's work.
