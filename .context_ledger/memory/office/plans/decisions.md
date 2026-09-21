# Architectural Decisions (append-only, ADR-style)

Decisions already made — future agents respect these rather than
relitigating them. To reverse one, append a new ADR that supersedes it.

<!-- TEMPLATE — copy below the last entry:
---
## ADR-N: <short title> (YYYY-MM-DD)
- **Status:** accepted | superseded by ADR-M
- **Context:** <what forced the decision>
- **Decision:** <what was decided>
- **Consequences:** <trade-offs accepted; what future agents must respect>
-->

---
## Carried from office-002 (closed 2026-09-21) — decisions still in force

- **Index:** the full ADR text (ADR-1 through ADR-61, carried into office-002
  from office-001; then ADR-62 through ADR-71, written in office-002 — note
  that ADR-66 was used twice on the same day: passive context writes, and the
  turn bus) is frozen verbatim at `history/office-002/plans/decisions.md` and
  preserved in git history. Do not relitigate them; to reverse one, append a
  superseding ADR here. New decisions in this office start at ADR-72.
- **Binding guardrail set (from `memory/workflows/active.md`, carried
  verbatim):** the ADR-34 event order; the `Hi`→zero-provider-call boundary;
  the thinking-aware-timeout fixes it builds on; ADR-40 (live-verify tool
  SELECTION on a flash-tier model + cerebras before any further schema cut);
  ADR-41 (z.ai thinking ON — never re-add a thinking-disable for GLM; timeout
  scaling is the lever); the provider-stall watchdog fall-through (once a first
  byte lands the heartbeat returns to the truthful prior branches — never
  stall-shame a healthy stream); the Parent-only scope (ADR-53).
- **Thinking infrastructure (ADR-62..66a):** ADR-62 build order Perception →
  Deduction → Self-check → Reflection → Planning, skills last, with its
  anti-pattern list as do-not-regress guidance; ADR-63 durability decided in
  the memory write path (refuse volatile with the reason, `canonical_key`
  identity so a restatement replaces one row, every mutation confirmed from a
  read-back); ADR-64 autonomous memory writes are VISIBLE (dedicated SSE +
  UI, the event fires only on a confirmed write, and what is stored is the
  pattern, not the instance); ADR-65 user-context deduction by trust tier, not
  vote, asserted on every answering surface and persisted once; ADR-66a
  passive context writes deterministic, subject-hinted, keyed, visible only on
  actual writes.
- **Loop and bus (ADR-66b and the loop set):** ADR-66b the turn bus —
  append-only facts with provenance, freshness decided at read time by goal
  version, lanes, one bounded `gate()`; a silent mutation must be a named
  exception, and a per-provider concurrency budget comes before widening
  parallel lanes. ADR-57/60 (never await in-flight consults at turn end; do
  not reintroduce serial every-tool consults), ADR-59 (no machinery prose in
  Thinker output), ADR-61 (never gate loop optimizations on the `intent`
  parameter — constant on the parent path), ADR-18 verification-first applied
  to the memory store as well as files.
- **Tool and provider contracts (ADR-67..70):** ADR-67 refuse only on a fact
  the tool verified itself and name the fact plus the confirming flag —
  verification reads the world directly, never through a tool that can fail
  for unrelated reasons; ADR-68 no canned plans — a step ticks from its tool's
  real outcome, a failed step stays failed and persists; ADR-69 a failover
  layer absorbs provider limits, silent to the user but announced and bounded,
  and a local model never silently falls back to cloud; ADR-70 where commands
  run and where installs land are user settings.
- **The state engine (ADR-71):** built BESIDE the classic parent, importing
  only stable capabilities; the ENGINE owns the state, the model only proposes
  moves and scores outcomes; simulation is real read-only probing; a hard
  budget with an honest `stopped`; read-only by construction in slice 1 (an
  unmarked tool surfaces as `needs_confirmation`); every step is an
  `EngineEvent` (the UI contract — never hidden reasoning); engine and model
  are independent axes and `Auto` is deliberately not built first.
- **Working agreements:** the live-testing bar is MANDATORY for loop/tool/
  adapter changes (`system/live-testing.md`; report live-verified vs
  unit-tested vs assumed); cure the disease, not single prompts; model-agnostic
  and env-agnostic fixes — "there is no weak model" (neutral terms only); a
  defect whose trigger is "the model worded X differently" gets a semantic or
  state check, never a wording list; push to main after each commit;
  two-surface commit prefixes, never mixed; explicit `git add` paths only when
  another session may have files in the tree; roster check-in every session;
  never port 8000 (the owner's app runs there) — isolated 8765 +
  `LOCALMIND_HOME` only; no secrets in tracked files, ever; closeout clears its
  own residue and leaves `git status` clean.
- Earlier permanent summaries: `history/office-001.md` (the Parent-only
  architecture era) and `history/office-002.md` (this office's record).

---
## ADR-72: The state engine is environment-agnostic and owns its own architecture; LocalMind is its first adapter (2026-09-21)
- **Status:** accepted — shipped (`backend/src/state_agent/`, adapter `state_agent/adapters/localmind.py`)
- **Context:** the engine had been built *beside the classic parent* (ADR-71) but still inside LocalMind's core: it imported LocalMind's tool catalog, tool dispatcher and provider adapters directly. The owner then set the direction: this is a new, potentially standalone product — "don't design it around LocalMind" — whose concepts (state, action, transition, simulation, evaluation, search, execution, terminal conditions) are engine-level, and whose UI (the State Explorer) is a prototype of the engine's own interface. The engine must be able to run against other environments (a CLI, an IDE, a browser, a standalone app) without being rewritten.
- **Decision:** (1) The engine lives in its own package, `state_agent/`, with **no import of LocalMind** — enforced structurally by `tests/state_agent/test_boundary.py`, not by convention. (2) Its public surface is contracts, not implementation: `Environment`, `Simulator`, `Proposer`, `Evaluator`, `TerminalCondition`, `ModelPort`, plus `Action`/`Observation`/`Evaluation`/`AgentState`/`EngineBudget`/`EngineEvent`. (3) Everything LocalMind-specific — the read-only tool table, the tool dispatcher, the provider adapters, the web route, the CLI — lives in `state_agent/adapters/localmind.py`; a second environment means a second adapter file, never an engine edit. (4) The ways a run can end are first-class, injectable `TerminalCondition` objects, each declaring the decision point it applies at (`before_propose`, `no_actions`, `no_improvement`), instead of `if` statements inside the loop. (5) A `Simulator` seam exists so an action that cannot be performed can be predicted (labelled `predicted`, never learned as a fact) — the protocol is wired and tested; no implementation ships yet. (6) A `SearchStrategy` protocol is deliberately NOT defined: the loop is the search until a second strategy (beam > 1) exists to justify the interface.
- **Consequences:** the engine can be lifted into its own repository (the host's git history keeps it) and other hosts can adopt it without touching it. LocalMind keeps the State Explorer UI, the `/state-explorer` + `/api/state-engine/*` routes and the Classic/State setting as the engine's first host — the UI already speaks engine concepts only (states, moves, PLY, depth, backtracks, probes, budget, settled/not-settled). Costs accepted: one more package boundary to respect (the boundary test makes a violation loud), and the CLI moved to `python -m state_agent.adapters.localmind_cli` because the engine cannot boot without an environment. Next slices: a real `Simulator` (predicted outcomes for irreversible actions, then execute behind the ADR-67 confirmation), a second `Environment` (CLI or IDE) as the proof the boundary holds, a wider beam, and persistent state.
