# Feature: agent-loop-closed-loop

Goal: implement ADR-5 + ADR-6 — formalize LocalMind's agent-mode as the
CODING HARNESS closed-loop (ADR-5: Context → 5-step Agent Loop → Tools,
with a Workspace feedback bar) AND restructure it into multiple
specialized agents sharing a `base_agent.py` (ADR-6: coding agent,
research agent, browser agent, direct agent). Drains backlog items
B-2026-07-26-1 (5-step loop + iteration cap + workspace-state injection
— High) and B-2026-07-26-2 (explicit context compaction step — Medium).

- **Goal:** Agent-mode becomes a real harness, not a bare API call.
  Concretely: (a) `backend/src/core/agent/loop.py` is decomposed into a
  shared `base_agent.py` (the 5-step loop + hard iteration cap + wall-clock
  cap + compaction + streaming + permission checking) with per-agent
  subclasses (`coding_agent.py`, `research_agent.py`, `browser_agent.py`,
  `direct_agent.py`); (b) new `backend/agents/coding/workspace_state.py`
  service exposes `snapshot() -> dict` returning `git status --short`,
  `git diff --stat` since last turn, last test/build/typecheck result,
  currently-open files; (c) the coding agent's loop calls
  `workspace_state.snapshot()` at step 1 of each turn (assemble prompt)
  and injects it into the context for the next model call; (d) shared
  compaction logic in `base_agent.py` summarizes older tool outputs before
  the model call when the assembled prompt exceeds a configured token
  budget (sized for the gemma3:1b-class target hardware); (e) the flat
  `backend/src/tools/` bag is redistributed into per-agent scoped
  `tools/` subdirectories so each agent has a smaller, more reliable
  tool surface for the small model; (f) Direct Mode vs Agent Mode becomes
  a registry lookup (`direct_agent.py` vs user-selected agent), not an
  if/else in the chat handler.
- **Started:** 2026-07-26 (Session 13)
- **Branch:** main (LocalMind pushes to main directly per
  `workflows/active.md` — no feature-branch flow; this feature commits
  alongside other work but every commit touching agent-mode is prefixed
  to make the trail greppable: `feat(agent-loop):` /
  `feat(workspace):` / `feat(context):` / `feat(agents):`)
- **Status:** in-progress
- **Current state:** ADR-5 captured Session 12 (the closed-loop shape).
  ADR-6 captured Session 14 (the multi-agent organizational structure —
  refines ADR-5). Feature-scoped memory directory created Session 13 —
  this manifest is the live dogfood for the 0.3.0 feature-scoped memory
  design. **Implementation started Session 15** — the first
  implementation session after three architecture-capture sessions (12,
  13, 14). Created the `backend/src/agents/` package: `base_agent.py`
  (abstract `BaseAgent` + `AgentConfig` with hard iteration/wall-clock
  caps per ADR-5), `registry.py` (name → agent class), `browser_agent.py`
  (first concrete subclass), and `browser/` subpackage
  (`context_builder.py`, `tools.py` with scoped `BROWSER_TOOLS`,
  `is_done.py`). 19 new tests in `tests/agents/test_agents.py` lock in
  the interface. Baseline held: 216 tests pass (197 baseline + 19 new),
  0 real ruff bugs (112 E501 pre-existing), mypy error is pre-existing
  numpy stub issue. The new `BaseAgent.run()` delegates to the existing
  `AgentLoop` for backward compatibility (Phase 1) — non-breaking. The
  existing `tools/browser_agent.py` tool stays registered for backward
  compat; the new `BrowserAgent` class is the structural skeleton ADR-6
  calls for. Last touched: Session 15 (2026-07-26) — first code commit
  for this feature.
- **Next steps:** Next implementation session should: (1) **extract
  the loop body from `agent/loop.py` into `BaseAgent._run_loop()`** —
  this is Phase 2 per the `base_agent.py` docstring. The existing
  `AgentLoop` becomes a thin shim that constructs a default agent and
  calls its `run()` method. (2) Wire the intent router / `model_router.py`
  to look up `agents.registry.get_agent()` by name so browser tasks
  route to `BrowserAgent` (currently the registry exists but the router
  doesn't call it — that's intentional Phase 1 non-breaking behavior).
  (3) Then build `coding_agent.py` + `workspace_state.py` (the
  highest-leverage piece per ADR-5's thesis — the workspace feedback
  loop is the differentiator). (4) Then `research_agent.py` and
  `direct_agent.py`. (5) Leave the context compaction step
  (B-2026-07-26-2) for a follow-up session — it's Medium priority and
  touches `context_builder.py` which is already well-tested. Update
  this manifest's "Current state" at the end of each implementation
  session. **Tool descriptions are the real design risk** (per ADR-6
  point 6) — test early that the gemma3:1b-class model reliably picks
  the right tool from each agent's scoped surface.
