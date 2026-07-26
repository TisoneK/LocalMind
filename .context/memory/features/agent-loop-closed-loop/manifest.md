# Feature: agent-loop-closed-loop

Goal: implement ADR-5 — formalize LocalMind's agent-mode as the CODING
HARNESS closed-loop (Context → 5-step Agent Loop → Tools, with a
Workspace feedback bar that pipes git/diff/test output back into
context every turn). Drains backlog items B-2026-07-26-1 (5-step loop +
iteration cap + workspace-state injection — High) and B-2026-07-26-2
(explicit context compaction step — Medium).

- **Goal:** Agent-mode becomes a real harness, not a bare API call.
  Concretely: (a) `backend/src/core/agent/loop.py` gets a hard
  `max_iterations` + `max_wall_clock` cap; (b) new
  `backend/src/core/workspace_state.py` service exposes
  `snapshot() -> dict` returning `git status --short`, `git diff --stat`
  since last turn, last test/build/typecheck result, currently-open
  files; (c) the agent loop calls `workspace_state.snapshot()` at step 1
  of each turn (assemble prompt) and injects it into the context for the
  next model call; (d) `backend/src/core/context_builder.py` (or a new
  `context_compactor.py` sibling) gains an explicit compaction step
  before the model call so older tool outputs are summarized, not
  truncated, when the assembled prompt exceeds a configured token
  budget (sized for the gemma3:1b-class target hardware).
- **Started:** 2026-07-26 (Session 13)
- **Branch:** main (LocalMind pushes to main directly per
  `workflows/active.md` — no feature-branch flow; this feature commits
  alongside other work but every commit touching agent-mode is prefixed
  to make the trail greppable: `feat(agent-loop):` / `feat(workspace):`
  / `feat(context):`)
- **Status:** in-progress
- **Current state:** ADR-5 captured in `plans/decisions.md` (Session
  12). Feature-scoped memory directory created Session 13 — this
  manifest is the live dogfood for the 0.3.0 feature-scoped memory
  design. Implementation not started — this is the planning +
  scaffolding state. The four modules the user offered to sketch all
  have rough analogues already in the codebase (verified via `wc -l`
  in Session 12): `context_builder.py` (736 LOC), `agent/loop.py`
  (2926 LOC), `tool_dispatch.py` (109 LOC) + `safety_gate.py`
  (135 LOC), and `workspace/manager.py` (272 LOC, the per-turn
  scratch directory — NOT the new workspace-state service; do not
  conflate). The work is integration + one new service
  (`workspace_state.py`), not greenfield. Last touched: Session 13
  (2026-07-26) — scaffolding only, no code changes.
- **Next steps:** First implementation session should: (1) read this
  manifest + `plans/decisions.md` ADR-5 + backlog items
  B-2026-07-26-1 and B-2026-07-26-2; (2) start with
  `workspace_state.py` — it's the highest-leverage piece per the
  diagram's thesis (the workspace feedback loop is the differentiator
  between a harness and a bare API) and is greenfield, so no existing
  code to refactor; (3) wire it into `agent/loop.py` step 1; (4) add
  the iteration cap to `agent/constants.py` + the loop; (5) leave the
  context compaction step (B-2026-07-26-2) for a follow-up session —
  it's Medium priority and touches `context_builder.py` which is
  already well-tested. Update this manifest's "Current state" at the
  end of each implementation session.
