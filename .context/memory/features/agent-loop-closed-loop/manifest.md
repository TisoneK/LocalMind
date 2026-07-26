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
- **Status:** in-progress (core complete — Phase 2 loop extraction + context compaction deferred)
- **Current state:** ADR-5 captured Session 12. ADR-6 captured Session 14.
  Sessions 15-18 built all 4 agents (browser, coding, research, direct) +
  workspace_state feedback service (ADR-5 differentiator, live in
  AgentLoop.run()). **Session 19** built the intent→agent selection layer
  (`agents/selection.py`): maps every Intent enum value to an agent name,
  then looks up the agent class via the registry. 16 new tests verify every
  intent is mapped, the mapping is deterministic, and each intent maps to
  the agent whose scoped toolset includes that intent. The selection layer
  is non-breaking (opt-in — the existing engine pipeline still uses
  AgentLoop directly; a future session wires `select_agent(intent)` into
  the engine to replace the if/else). Baseline held: 297 tests pass (197
  baseline + 19 agents + 25 workspace_state + 17 coding_agent + 23
  research/direct + 16 selection), 0 real ruff bugs (112 E501 pre-existing).
  Last touched: Session 19 (2026-07-26).

  **Feature at natural completion point.** The ADR-5 differentiator
  (workspace_state feedback loop) is live. The ADR-6 organizational
  structure (4 specialized agents sharing BaseAgent, each with scoped
  tools) is in place. The intent→agent selection layer is built and
  tested. What remains deferred: (1) Phase 2 loop body extraction
  (BaseAgent._run_loop() — the 2926-line refactor, non-blocking); (2)
  wiring select_agent() into the engine pipeline (replaces if/else with
  registry lookup — opt-in, needs a design decision on UI picker vs
  auto-selection); (3) context compaction (B-2026-07-26-2, Medium).
- **Next steps:** Next implementation session should: (1) build
  `research_agent.py` (web_search + web_fetch scoped tools, enough-sources
  is_done) and `direct_agent.py` (tools_enabled=False, steps 1-2 only).
  Both are the same thin-subclass pattern as browser + coding — should
  be quick. (2) Then wire the intent router / engine pipeline to call
  `agents.registry.get_agent()` by name so agents actually get selected
  (currently the registry has 2 agents but the engine doesn't call it —
  intentional Phase 1 non-breaking behavior). This requires deciding
  where the agent name comes from: UI picker (ADR-6 preferred) or
  intent-based auto-selection. (3) Phase 2 loop body extraction
  (`BaseAgent._run_loop()`) — the big 2926-line refactor — can happen
  any time but isn't blocking; the workspace_state feedback loop (the
  ADR-5 differentiator) is already live. (4) Context compaction step
  (B-2026-07-26-2) — deferred. Update this manifest's "Current state"
  at the end of each implementation session. **Tool descriptions are
  the real design risk** (per ADR-6 point 6) — test early that the
  gemma3:1b-class model reliably picks the right tool from each agent's
  scoped surface.
