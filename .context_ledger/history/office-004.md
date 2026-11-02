# Office 004 — accomplishments record (permanent)

- Opened: 2026-10-31
- Closed: 2026-11-02
- Sessions: 21

The frozen office lives at history/office-004/ until it is zipped into
archive/office-004.tar.gz. This record stays in history/ forever — even after
the tarball is garbage-collected, the office is never forgotten. Not read at
session start; deliberate lookback only.

## Accomplished

- **Core upgrade:** vendored `.context_ledger` 2.2.1 → 2.3.2 with the
  union-merge `.gitattributes` adoption.
- **Runtime integrity fixes:** the vector-dimension mismatch that silently
  stopped memory writes (startup now reconciles against the vec0 table DDL,
  not only `vector_meta.dim`); the renderer crash on `retryAttempts` plus a
  friendlier recovery than the full-screen Reload-or-Reset wall; the Cerebras
  `messages.N.user.tool_calls` payload rejection (per-role wire normalization,
  `invalid_request` → failover) and the conversation-recall behaviour behind
  it (transcript-only recall lane, name-identity dedupe).
- **Prompt architecture program (B-2026-10-31-25) completed:** named-section
  registry with enforced order slots and a TURN-only cache guard; the 4-layer
  User Objective Primacy layout; instruction dedupe; packaged as
  `core/agent/prompt/` (engine, catalog, staging, rules, per-surface section
  families, dispatcher, planner, pipeline); per-turn relevance budget with a
  hard byte-prefix constraint; honest tokens-per-second (decode-window
  denominator); mid-flight settle net (unknown-outcome tool reconciliation);
  fail-closed auxiliary-call contract; request derivability (G7) from the
  durable record with `?derive=1` and fingerprint linkage; the prompt
  architecture doc (G8).
- **Observability:** the durable per-turn execution trace — every turn's event
  stream persisted verbatim (turn_traces store, retention/cascade), adapter
  model-call stamps (submit / first byte / last byte, usage, payload size +
  hash), path-selection decisions, context assembly + stage events,
  context_breakdown and post_answer_lanes persisted, trace list/replay API and
  Trace tab in the UI.
- **Honest completion contract:** `response_ready` SSE event + per-stage
  `turn_stages` / `post_answer_lanes` attribution (loop → runtime → done),
  removal of the false "Answer ready · finishing up" strip, Stop disabled once
  the reply is final; post-turn services (fact extraction, reflection) detached
  from the transport.
- **Greeting / conversational gate:** the zero-tool false-positive execution
  gate fixed, honest gate-replan attribution, event-timestamped workspace
  telemetry, the greeting regression matrix, retirement of the canned-greeting
  path, and the harness-note registry.
- **Continuous goal pursuit:** investigation answering the owner's continuity
  questions; the durable open-question record (migration 015) with the
  `open_question_reply` reroute lane, question section, and supersede/social
  preservation rules; the carried objective on ordinary turns; idle/reconnect
  continuation of an armed deep dive (`core/goal_idle.py`, human
  resume/pause endpoints, same durable cap); the native `update_goal` /
  `get_goal` call flattening fix.
- **Standing eval harness:** 13 scenarios × the external audit's six metrics
  driven against the live app, structural gating + defect-signature
  exclusions, JSON/markdown/SSE artifacts, and a `--provider real` mode that
  refuses fast without keys. Its first full run caught and fixed two real
  calculator defects (name/intent mismatch routing SHELL; the allowed-tool
  fence comparing intents to tool names).
- **Todo Planning & Hierarchical Execution (B-2026-11-02-1):** `{todo,
  outcome}` classify contract with fail-closed parsing inside the init-prompt
  budget; the Todos panel hierarchy (steps, "Done when:" contract, result /
  failed / blocked closing line); honest lifecycle (in_progress on first tool,
  evidence-carrying completions, failed with reason, never-reached → blocked
  "Not reached" instead of a false 100%); migration 016 persistence and
  re-render for mid-objective resume; per-todo outcomes seed the acceptance
  gate's criteria.
- **Port flexibility:** `npm start` now resolves ports before spawning
  (`scripts/dev-full.js` + `core/ports.py`): free → use, healthy LocalMind →
  reuse via watcher slot, foreign app → next free port with a loud notice,
  `LOCALMIND_PORT_STRICT=1` → the old fail-fast naming the occupant; env
  propagation to Vite, proxy, Electron, backend bind and CORS; the occupancy
  probe's hung-connect hole fixed.
- **Arsenal-export fix pack (owner "Fix all"):** structured `system_search`
  args survive dispatch (digits no longer re-parsed as a filename filter);
  live-data / results questions forced into the tool loop with the
  capability-honesty spine naming the internet; the execution record (last six
  tool calls with honest outcomes) injected into the free `transcript_focus`
  slot so the model judges its own actions from the record; the completion
  judge runs thinking-off inside 5s; deterministic provider management (the
  implicit "any keyed provider" failover tail retired — explicit `fallback_to`
  only, switch recorded, persisted identity stamps report the adapter that
  actually served the turn); a new standing live harness
  (`scripts/live_test_arsenal_fixes.py`).

## Decisions still in force

- **ADR-41** — thinking policy on the answer path (per-call override; aux
  calls may run thinking-off).
- **ADR-66b** — turn-bus attribution: an answer is final when the reply is
  final; post-turn bookkeeping runs as detached lanes, never holding the
  transport; the user must never see "Working" after the answer is on screen.
- **ADR-67** — confirmable refusal: refuse only on a verified fact, name the
  fact and the confirming flag; never guess.
- **ADR-69** — provider failover: bounded, announced, explicit; a local model
  never silently falls back to cloud. As amended this office: no implicit
  keyed-provider tail — only an explicit `fallback_to`, running the
  destination's own configured model, with the switch `{from, code, to}`
  recorded and the turn's persisted identity stamps naming the adapter that
  actually served it.
- **ADR-70** — where commands run and where installs land are user settings.
- **ADR-71** — the state engine is built beside the classic parent, importing
  only stable capabilities; the engine owns state, the model proposes moves;
  simulation is real read-only probing; hard budget with an honest `stopped`;
  read-only by construction in slice 1; every step is an `EngineEvent`; engine
  and model are independent axes and `Auto` is deliberately not built first.
- **ADR-72** — the state engine is environment-agnostic and owns its own
  architecture; LocalMind is its first adapter. No engine import of LocalMind
  (enforced by `tests/state_agent/test_boundary.py`); host-specific code lives
  in `state_agent/adapters/localmind.py`; terminal conditions are injectable
  objects; the `Simulator` seam exists; no `SearchStrategy` interface until a
  second strategy exists.
- **Working agreements:** the live-testing bar is mandatory for loop / tool /
  adapter changes (`system/live-testing.md`; report live-verified vs
  unit-tested vs assumed); cure the disease, not single prompts; model- and
  environment-agnostic fixes — "there is no weak model", neutral terms only; a
  defect triggered by different wording gets a semantic or state check, never
  a wording list; push to main after each commit; two-surface commit prefixes,
  never mixed; explicit `git add` paths; roster check-in every session; never
  port 8000 (the owner's app runs there) — isolated 8765 + `LOCALMIND_HOME`
  only; no secrets in tracked files, ever; closeout leaves `git status` clean.

## Open threads

- **In flight when the office closed:** adaptive plan revision & objective
  fidelity (re-seeded as backlog B-2026-11-02-2). Recon was done and the build
  had started: `retired` todo status carrying the discovery, a `todo_revised`
  added/retired/kept diff in the Todos panel, and a bounded objective-fidelity
  judge at the close. Re-seeded into the fresh office with its full spec.
- **Re-seeded actionable backlog:** state-engine follow-ons (in-app State
  Explorer + engine selector; execute-behind-confirmation slice with a second
  `Environment` adapter and persisted state; the Classic-vs-State benchmark);
  confirmable-refusal rollout; perspective/speaker-identity consistency;
  lane expansion on the turn bus (Decider, parallel read-only lanes,
  per-provider concurrency budget); provider-health UI, per-provider budget,
  failed-source memory for browse/research; learning transfer at decision
  time; anti-sycophancy guard; turn economy for verification-heavy tasks;
  association-level grounding judge; feedback-turn routing; trajectory
  projection completion (`message.toolCalls` live vs reload shape);
  mode-gating mixed-intent effecting tools; reflective/identity turns must not
  reach for meta-tools; LocalMind as a consumer of the public engine repo.
- **Standing follow-up:** the real-provider eval scoring run
  (`scripts/eval_suite.py --provider real`) on the owner's box — every sandbox
  run used deterministic fake providers because no key lives there. Same for a
  genuinely live failover switch between two real keyed providers.
- **Parking lot (knowledge, not queue):** teach `reset_vector_db.py` the cloud
  embedder path; Windows verification of the State Explorer page and live SSE
  run route; `PATCH /api/memory/{id}` tolerance when the store was built by
  the plain-text fallback (refuse with a reason, not 404); reproduce the
  "Conversation too long" false positive on the owner's setup (raw provider
  error + missing provider label); async test-isolation flake + repo-root
  pytest config (`asyncio_default_fixture_loop_scope`); Windows test
  portability (raw `tmp_path` backslashes in JSON args, `PYTHONUTF8=1` in CI,
  stabilizing the nondeterministic failure families, refreshing
  `scripts/pytest-baseline.txt` as a ratchet).
- **Resolved this office (do not re-litigate):** the post-turn phase question
  (bounded services detached from the transport); the implicit provider
  failover tail (retired); the canned-greeting path (retired by owner ruling);
  the calculator fence (intent/name sets aligned, read-only arithmetic
  allowed); the false 100% todo completion.
