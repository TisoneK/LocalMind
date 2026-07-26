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
  design. Implementation not started — this is the planning +
  scaffolding state. The existing modules that map to the target
  structure (verified via `wc -l` in Sessions 12 + 14):
  `backend/src/core/agent/loop.py` (2926 LOC) → `base_agent.py`,
  `backend/src/core/agent/orchestrator.py` (532 LOC) → shared planning,
  `backend/src/core/agent/tool_dispatch.py` (109 LOC) → shared dispatch,
  `backend/src/core/safety_gate.py` (135 LOC) → shared permission layer,
  `backend/src/core/context_builder.py` (736 LOC) → per-agent
  context_builders, `backend/src/tools/` (14 flat tools) → per-agent
  scoped tools/, `backend/src/core/workspace/manager.py` (272 LOC —
  the per-turn scratch directory, NOT the new workspace-state service;
  do not conflate). The work is decomposition + redistribution + one
  new service (`workspace_state.py`), not greenfield. Last touched:
  Session 14 (2026-07-26) — ADR-6 capture only, no code changes.
- **Next steps:** First implementation session should: (1) read this
  manifest + `plans/decisions.md` ADR-5 AND ADR-6 + backlog items
  B-2026-07-26-1 and B-2026-07-26-2; (2) **promote the existing
  `backend/src/tools/browser_agent.py` to a full agent first** — it's
  already domain-scoped in name, so it's the natural first concrete
  step and the smallest risk (no existing coding/research agent to
  break); (3) extract `base_agent.py` from `agent/loop.py` as the
  shared loop, with `browser_agent.py` as the first subclass; (4) then
  build `coding_agent.py` + `workspace_state.py` (the highest-leverage
  piece per ADR-5's thesis); (5) then `research_agent.py` and
  `direct_agent.py`; (6) leave the context compaction step
  (B-2026-07-26-2) for a follow-up session — it's Medium priority and
  touches `context_builder.py` which is already well-tested. Update
  this manifest's "Current state" at the end of each implementation
  session. **Tool descriptions are the real design risk** (per ADR-6
  point 6) — test early that the gemma3:1b-class model reliably picks
  the right tool from each agent's scoped surface.
