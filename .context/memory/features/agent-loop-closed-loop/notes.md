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
