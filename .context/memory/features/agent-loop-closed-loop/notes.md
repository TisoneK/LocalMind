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
