# Survey — S024: "Decision Core" / event bus / silent system_tools, checked against the real design

**Agent:** Imani (S024) · **Date:** 2026-09-19 · **Core:** 2.0.2
**Task:** owner directive — survey the existing design, limits, strengths, backlog and impact BEFORE any ADR is written for the design floated in a pasted chat thread. No product code changed. The survey itself is read-only; one live trace was added afterwards (see the addendum at the end). Every "measured" number in the thread is UNVERIFIED here.

## Verdict in one paragraph

The thread's diagnosis ("LocalMind has no decision layer; five decisions are slow LLM calls or heuristics") is mostly **not what the code and ADRs show**. Most of the five decisions already have a deterministic or purpose-built home, and several thread bugs are either already fixed, already tracked, or not present in the ledger at all. What the thread does surface that is real: the shell blocklist is still substring matching, there is no fresh-eyes acceptance judge yet (already the Target's item 3), model routing is intent-keyed and thin, and there is no provenance schema on Thinker verdicts. A new "Decision Core + bus" module would collide with ADR-53, ADR-57/60 and the Do-NOT-regress list unless it is scoped down to those real gaps.

## Claim-by-claim

| Thread claim | What the repo shows | Status |
|---|---|---|
| Tier classify is a full LLM call, half the latency | Tiering is layered: `pre_init_classifier.classify_pre_init` (deterministic, before any LLM) → `trivial_input` fast paths (`Hi` = zero provider calls; conversational = one direct call) → only ambiguous turns hit the LLM classify call in `initialization.py` (classify-only since ADR-38/46; it also yields title/objective/ack). | Mostly false. Real cost only on ambiguous turns. |
| Thinker gate is not wired in, causes dual-reply | Thinker is wired and streaming: `thinker/thinker.py`, `_BackgroundConsult` in `loop.py` (~478, 3229, 5397), concurrent per ADR-60, capped (`_THINKER_CONSULT_CAP`=5), failure keeps the blocking inline consult. ADR-37 names *Direct Mode as a second path* (not the Thinker) as the structural source of dual replies; the enum half was removed, the user-facing toggle was re-added (parking-lot P-2026-09-16-12). | Premise wrong; dual-reply has a known different root, still open. |
| No synthesize/evaluate stage → premature "turn complete" | There is one: `_acceptance_gate_at_final_answer` (`loop.py:7201`) + `verify.py` criteria gate + `post_execution_verifier.py` + `turn_outcome.classify_turn_outcome` (one seam, pure function). ADR-18 (verification-first) is the standing contract. Still open: ADR-57 slice 5 (turn the gate's LLM call into a code check where possible), the "fresh-eyes acceptance judge" (standing Target item 3), test nondeterminism in the gate (B-2026-09-09-7). | Exists; deepening is already on the roadmap. |
| Todos self-mutate to 100% | Real mechanism found: `_advance_plan_on_narration` / `_complete_current_plan_step` in `loop.py` (~2896–2960) and `_finalize_plan_todos` in `api/routes/chat.py:439`, which flips remaining `plan-*` rows to done at turn end. The honest-stop `skip=True` path already stops this when the acceptance gate reports unmet criteria. The remaining gap: a turn that ends WITHOUT the gate firing still gets all rows flipped, unverified. | Partly fixed; residual gap is precise and small. |
| Command-safety filter is false-positive substring matching | `tools/shell.py` `BLOCKED_COMMANDS` is still a substring list (`shutdown`, `reboot`, `mkfs`, `dd if=`, `net user`…). The worst case (`format`) was already fixed with `_BLOCKED_FORMAT_RE` after a live trace. `core/safety_gate.py` is a separate regex layer (hard blocks + destructive-op flags) and explicitly warns against vocabulary matching. | True for the remaining substrings (e.g. `shutdown`/`reboot` inside paths/args). Small, local fix; not evidence for a new subsystem. |
| Phantom "do NOT read it back" instruction in a user-facing tool | It existed and is already removed: the comment at `loop.py:8536` records the fix; the loop now surfaces its own read-back as evidence (P-2026-09-16-13, L3 done + live-verified). | Already fixed. |
| Misrouted panel events | No ledger row or code note found under that name. Related known item: ADR-64's rule that autonomous events must be top-level SSE events, not the generic `obs_event` wrapper the frontend drops. | Unverified — need the actual repro. |
| Two sequential calls latency bug | Known and addressed: ADR-57 (serial→concurrent, silent→streamed, redundant→gated) and ADR-61 (evidence-sufficient turns answer on one schema-free call; live 184.8s→14.1s). | Already in flight/shipped. |
| Provider/model routing is ad hoc | `core/model_router.py`: `best_model_for(intent, fallback)` (local Ollama specialists by intent), per-agent env overrides `LOCALMIND_AGENT_MODEL_*`, `routing_report`. ADR-53's maturity bar lists "provider/model escalation" as future Parent work. Intent is a **constant** on the parent path (ADR-61), so intent-keyed routing carries no signal for the Parent. | Real gap, but the router's key is the problem, not a missing "Core". |
| A `Decider` component, event bus, `system_tool_result` type | None exist. (`_normalize_system_tool_call` in `text_tools.py` is unrelated: it normalizes model tool-call names.) The cloud-backed "Jev" backend from the thread is out of scope per the owner (2026-09-19) and is not considered here. | New; nothing to conflict with, nothing to reuse. |
| A bus/append-only fact record with `grounded_in` provenance | Nothing like it exists. Closest: `AgentTrace`, `TaskState` (ADR-18), `_obs` events, `decision_ledger.py` (durable *user* decisions, not turn verdicts), Thinker `Evidence.prior_analysis` (one-way carry-forward). | New — the one genuinely additive idea. |

## What already exists and must not be re-built (strengths)

- Deterministic pre-classification and zero-call `Hi` boundary (S206) — a binding guardrail.
- Thinker with streamed prose, structural JSON-never-surfaces invariant, background per-tool consults, cap, one-in-flight throttle (ADR-59/60).
- One-seam turn-completion contract (`turn_outcome.py`) — the design direction is *fewer* guards routed through one pure function.
- Verification-first program (ADR-18), evidence-first answers (ADR-38/61), read-back after mutation (ADR-63).

## ADR / guardrail collisions a Decision Core would have to resolve

1. **ADR-53 (Parent-only, no peer agents):** Thinker/Decider as bus "components" is fine only if they stay Parent-internal modules, never framed as agents.
2. **ADR-57/60:** "hard-await gate before irreversible actions" vs "do NOT await in-flight consults at turn end" and "do not reintroduce serial every-tool consults (S420)". The thread's hard gates need an explicit reconciliation.
3. **ADR-46:** execute is opt-in, never fail-open — a new classifier must fail *closed to clarify/direct*, not to execute.
4. **ADR-62 build order + ADR-64:** thinking infrastructure (reflection, signal fusion, gap detection, active memory) outranks new features; any "silent" mechanism that writes/mutates conflicts with ADR-64's visibility rule. The thread's silent **read-only** `system_tools` would need to be explicitly compatible: silent to the panel is fine; silent *mutation* is not.
5. **ADR-40/41 guardrails and the live-testing mandate:** any loop change requires live verification on real models (a flash-tier model + cerebras for tool selection); no such run exists for this design.
6. **"No weak model" / model-agnostic rule:** the thread's "local-model-adapter fallback" and per-model latency framing must not become a `slow_provider`-style special case.
7. **Trust-over-latency (preferences, 2026-09-19):** the thread's headline (milliseconds) is not an acceptable justification.

## In-flight work and collision risk

- **Tariq (S020)** is live on B-2026-09-15-15 (passive context awareness; builds on `core/user_context.py`, ADR-63/64/65, memory write path). Overlap risk is low for a survey, but medium for any change to `loop.py`/`initialization.py` — under the collab override, a peer is live, so any product edit needs its own worktree + claim event.
- `loop.py` is ~9.5k lines; the acceptance gate and Thinker wiring live there. Any change is high blast radius.
- Standing Target (owner, 2026-09-12): MCP client, read-only Explorer subagent, fresh-eyes acceptance judge, plugin skills. The "evaluate" half of the thread overlaps the judge directly.

## Real, evidence-backed gaps (candidate work, ranked by evidence — NOT yet decided)

1. **Unverified end-of-turn todo finalize** when the gate did not run (`chat.py:_finalize_plan_todos`) — concrete, small, ties to ADR-18. Needs a live repro to prove it fires.
2. **Substring blocklist in `tools/shell.py`** (`shutdown`, `reboot`, `mkfs`, `dd if=`, `net user`) — tokenise/anchor as was done for `format`; needs a live false-positive trace to justify.
3. **Fresh-eyes acceptance judge** (already Target #3) — the honest home for the thread's "typed evaluate" idea; should be designed against ADR-18/57-slice-5 and B-2026-09-09-7 nondeterminism.
4. **Provider/model escalation** keyed on task shape, not on the constant `intent` (ADR-53 maturity bar; ADR-57 slice 4 "right-size the Thinker role") — needs a design that isn't `slow_provider`-shaped.
5. **Dual-reply root** (P-2026-09-16-12, user-facing Direct toggle re-added) — the thread blamed the wrong component; the ledger has the real one.
6. **Fact/provenance schema for verdicts** — the only truly new idea; worth a small spike *only after* items 1–3 show it is needed (ADR-62 favors thinking infrastructure, so this is welcome if scoped to the Parent).

## Unverified / needs the owner

- Where were the "misrouted panel events" and the dual-reply repro observed (trace, session id)?
- Is the thread's "70–500 ms" a measurement or a target? No measurement exists in the repo for it.
- Owner call: proceed with 1–3 as separate small, live-verified changes, or still want a bus/Core ADR after seeing this?

## Method / limits

Read: STATE, decisions (ADR-62–65 + frozen ADR-18/37/38/46/53/57–61), overrides, preferences, backlog/parking-lot rows by keyword, `thinker/`, `initialization.py`, `pre_init_classifier.py`, `trivial_input.py`, `turn_outcome.py`, `safety_gate.py`, `tools/shell.py` blocklist, `model_router.py`, `loop.py` at Thinker/gate/todo sites, `chat.py` todo finalize. Not done: no live run, no full read of `loop.py`, no test execution, frontend not inspected (panel-event claim unchecked).

## Live trace addendum (S024, same day) — where one real turn's wall-clock goes

**One run, one provider, one prompt — an observation, not a benchmark.** Provider: gemini/gemini-2.5-flash (zai returned 401 "token expired"; bankofai returned `credit insufficient balance: balance=0` — neither could be traced; owner must refresh the zai key in Settings, no key was read or printed). Isolated port 8765 + scratch `LOCALMIND_HOME`, backend from source, harness kept outside the repo. Prompt: list `/Users/bao/Code`, get the latest commit message, count `.py` files under `backend/src/core` (three independent read-only asks).

| Measurement | Value |
|---|---|
| Wall clock to `done` | 15.0 s |
| LLM calls / prompt tokens / completion tokens | **17** / 76,523 / 3,446 for a three-tool, four-iteration turn |
| Tool execution time (dir_explorer / git / find) | 2 ms / 44 ms / 29 ms — negligible |
| Tool calls | 3, **emitted one per model iteration** (independent, none batched) |
| First answer token → `agent_loop_done` | 4.95 s → 11.69 s |
| `agent_loop_done` → `done` | 11.69 s → 15.02 s: **post-answer reflection (3.3 s, ~22% of the turn) sits on the critical path to `done`** |
| Reflection outcome | score 8, flagged a truncated folder list and issued a correction — it earned its time |

Readings (each needs finer instrumentation before it's trusted):
1. Time is essentially all model calls, not tools; the 17-call count is the outlier and its breakdown (Thinker consults vs reflection vs synthesis vs other) is unknown — the ADR-57 "calls/turn" metric is the first thing to instrument.
2. The model serialised three independent reads; harness-level batching/speculation of independent read-only calls has real headroom on this model (it does not emit parallel calls, matching P-2026-09-16-17).
3. Reflection runs after the loop and `done` waits for it — confirmed blocking at `agent_runtime.py:2121`. It caught a real defect, so the candidate change is to overlap/stream it, not remove it (trust-over-speed).
4. A ~5 s stretch between the last answer token (6.69 s) and `agent_loop_done` (11.69 s) is unexplained by the events emitted; `agent_thinker_start iteration 3` has no matching `done` before loop end. Needs a stage timer.
5. SSE events arrive in clumps (several sequential events at the identical timestamp; a tool's `done` event trails its `terminal_output` by ~1.4 s, i.e. until the next model call) — either the bridge batches or the client read does; the panel may show tool completion late. Unverified which.
