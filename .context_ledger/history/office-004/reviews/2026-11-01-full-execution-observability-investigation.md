# INVESTIGATION: LocalMind full execution observability (2026-11-01)

Session: Zuri (S011). Source of record: the owner's brief of 2026-11-01
("Before we try to make LocalMind faster, smarter or more capable, we need to
be able to observe it accurately") plus the three-turn token/latency review
that preceded it (greeting 6,159 prompt tokens / capabilities 564 / compliment
6,301; turn-2 timestamps 3 ms apart against a recorded 14,610 ms latency).

**This was an investigation, not an implementation request.** No product code
was changed. One read-only capture harness was added
(`scripts/obs_trace_capture.py`, the established 8765 + scratch-home +
deterministic-provider pattern) so every claim below about what the running
system emits and persists is backed by an actual captured trace, not by
reading alone. Artifacts: `scratch/obs-trace/` (per-turn SSE streams, history
payloads, observation snapshots, raw DB rows, summary).

Evidence classes used, per the brief's constraints:
- Code read first-hand at every stage of the lifecycle (anchors below).
- A live capture of the owner's exact three messages on the real server +
  real transport (deterministic provider; the wire/path contract is
  provider-independent — the sandbox holds no provider key, per Rosa S008's
  recorded limit). The capture reproduced the owner's pathology: the greeting
  and the compliment took the parent-agent loop, the capabilities question
  took the conversational fast path, and the fast-path turn's user/assistant
  rows landed 0.7 ms apart while `latency_ms` recorded 253 ms for the same
  turn.
- The owner's exported numbers were used as observations to explain, never as
  facts assumed about the code.

Companion documents this one builds on (not duplicates): Rosa S008's
turn-close attribution, Nora S009's greeting analysis intake, Sefu S010's
external-harness deep study (its gap G7 — request derivability from the
durable record — is the same hole this investigation measures from the other
side). All terms are LocalMind's own.

---

## Deliverable 1 — Current observability architecture

One sentence summary: **LocalMind records rich events while a turn runs, but
persists only projections of them; there is no durable execution trace, and
several stages emit nothing at all.**

The event backbone is `core/obs.py`. `ObsEvent` = `{type, data, ts}` where
`ts` is epoch-ms stamped at emit time (obs.py:18-30). A per-request
`ObsCollector` accumulates the full history in memory (obs.py:43-51) and an
emit wakes the SSE transport immediately (obs.py:53-71). Each event reaches
four destinations:

| Destination | What survives | Where |
|---|---|---|
| SSE wire | the event itself, **without its `ts`** — `to_sse_dict()` sends `{type, data}` only (obs.py:32-33) | chat.py drains at 245, 409, 762, 984, 1161 |
| Workspace projections | `build_run_tree` / `build_agent_phases` / `collect_injected_items` fold the history at persist time; the raw stream is then dropped | agent_workspace.py:265-697; persisted into `messages.agent_runs / agent_phases / injected_items` (db.py:66-74) |
| Observation snapshot | the **last 50 events** (cap `_MAX_CAPTURE_EVENTS = 50`, observation.py:22) into a bounded per-session summary row | observation.py:86-93, 105-151; `observations` table; served by `GET /api/observability/{id}` |
| Merged turn observation | intent/latency/tools/stage_timings/tool_timings/anomalies folded into the same `observations` row | agent_runtime.py:760-843 |

Beside the event bus sit: `MetricsStore` (process-memory only; its percentile
recorder `record()` has **no callers** — metrics.py:157-193 is dormant), the
`messages` telemetry columns (metrics/thinking/tool_calls/diff_data/
candidates — db.py:51-78), the live-written `actions` table (the tool
timeline, chat.py:192-212), `failure_memory` and `decision_ledger` tables, and
an env-gated prompt-payload audit (`LOCALMIND_PROMPT_AUDIT`,
openai_compat.py:181-189, 286-326) which is the **only** mechanism anywhere
that captures the exact outgoing model payload — off by default.

Two clocks are in play for the same events: the SSE wire carries no event
timestamps, so the live frontend stamps everything with its **renderer
arrival clock** (`Date.now()` at useLocalMind.ts:814-821), while the persisted
rebuild stamps from the backend **emit `ts`** (agent_workspace.py:532). After
Nora S009's fix both are event-time — but they are still two different
clocks, and neither is visible on the wire.

What the conversation export carries is the **snapshot-plus-projections**
view: messages, thinking, tool pills, `agentRuns`/`agentPhases`
(projections), and a six-field `performance` block. It does not carry the
execution itself. There is currently **no way to open a finished turn and
reconstruct what LocalMind actually did** — the brief's central ask.

## Deliverable 2 — Complete execution lifecycle map

Stage-by-stage, with today's telemetry classification: **stamped** (an event
or timestamp exists), **derivable** (can be computed from what survives), or
**silent** (nothing is recorded).

| # | Stage | Where | Today |
|---|---|---|---|
| 1 | Transport entry (POST /api/chat, session identify) | chat.py:615-683 | silent (no turn-started on the wire) |
| 2 | Runtime entry — `turn_started` base clock | agent_runtime.py:915, 2468 (loop) | stamped (loop only; fast path has no `turn_stages`) |
| 3 | Routing decision (client hint honored / pre-init guards / fast-path regex vs parent loop) | agent_runtime.py:937-959, 1340-1415 | **silent** — `logger.info` only; the decision is inferable only indirectly (which metrics keys survived) |
| 4 | Context gathering (history, memory facts, parent session, attachment) | agent_runtime.py:1730-1886 | silent except the summary `agent_context_ready` and `attachment_failed` |
| 5 | Prompt assembly (runtime) | agent_runtime.py:1906-1939 | `stage_timing context_build` start/end only — no size, no composition |
| 6 | Parent loop start / init-classify call | loop.py:2468, 2818-2906 | stamped (init lifecycle events; `init_prompt_chars`) |
| 7 | Planning | loop.py:2978-3221 | stamped (todo/plan events) |
| 8 | Per-iteration context build + injections | loop.py:3560-3685 | `context_injected` ledger (kind/source/text/chars — good); breakdown computed per call at 4452-4464 but **only on full iterations** (init-direct answers skip it) |
| 9 | Model call | loop.py:4466-4545; adapters | **silent at the boundary**: per-call latency is a log line (`llm_ms`, loop.py:4523); no submit/first-byte/last-byte stamps from the adapter on any loop path; usage folded with **last-call semantics** (loop.py:567-584) |
| 10 | Tool execution | loop.py:4615-4809, 5389-5960; tool_dispatch.py:330-378 | stamped well: started/done with duration, retry ledger, terminal output, grounding checks |
| 11 | Acceptance gate / completion judge / replans | loop.py:8049-8860 | stamped (`agent_loop_gate_*`, judge verdict + `elapsed_ms`, replan events, honest-stop attribution) |
| 12 | Response streaming to the UI | chat.py:886-1107 | first/last token stamped by the runtime (agent_runtime.py:2094-2141); `response_ready` marker before `done` (Rosa S008) |
| 13 | Persist (user row, assistant row + artifacts) | agent_runtime.py:1594-1638 (fast path, **awaited back-to-back after the timed work**), 1711-1719 (loop: user row fire-and-forget at turn start), 2343-2372 | stamped — but the stamps are **row-write instants, not turn milestones** |
| 14 | Turn close (`turn_completed`, `turn_complete`, `metrics` SSE, done payload) | agent_runtime.py:2339-2463; chat.py:1107, 1163-1197 | stamped; persisted metrics include `turn_stages` but **not** `post_answer_lanes`/`context_breakdown` (agent_runtime.py:2349-2366) |
| 15 | Post-turn background lanes (facts, reflection, title refine) | agent_runtime.py:2470-2485; chat.py:1281-1318 | memory events emitted via final drain; **title work fully silent** |
| 16 | Frontend rendering state (strip, timers, phase labels) | useLocalMind.ts:905-1899 | live-only (`statusText`, `thinkMs`, `answerMs`, `stageTimings`); `answerMs` recorded and consumed by nothing |
| 17 | Delegation / nested runs | delegation.py:177-505; obs.py:140-186 | stamped (run_id chain, depth, started/completed; child events forwarded tagged) |

**The one-line lifecycle truth:** tools, gates and replans are the best-observed
parts of the system; the stages in front of the first model call (routing,
context gathering, prompt assembly) and inside each model call (submit →
first byte → last byte) are the least observed. The owner's "mysterious
seconds" live precisely in the unobserved band.

## Deliverable 3 — Inventory of existing events and telemetry

**SSE events the renderer handles** (useLocalMind.ts dispatch, verified live):
`token`, `thinking_start/token/end`, `tool_call`, `tool_result`, `intent`
(**dead** — its producer `intent_classified` has no emitter anywhere in the
backend), `anomaly`, `diff`, `obs_event:*` (agent lifecycle, delegation,
stage_timing, plan, gate, replan, injected-context, thinker, evidence,
turn_complete), `response_ready`, `done`, `error`, `metrics`, `goal`,
`goal_round`, `response_blocks`, `reflection_lesson`, `passive_memory`,
`terminal_event`, `status_update`, `todo_*`.

**Persisted per assistant row** (db.py:51-78; verified in the live capture):
content, thinking, acknowledgement, error, tool_calls, metrics
(prompt/completion/latency_ms ± cached_tokens/llm_calls/think_ms/model/
provider/turn_stages — the fast-path variant omits cached/llm_calls/
turn_stages), agent_runs, agent_phases, injected_items, diff_data,
candidates.

**Persisted elsewhere:** `actions` (tool timeline), `observations`
(bounded per-session snapshot + merged turn observation), `failure_memory`,
`decision_ledger`, `parent_sessions`, `todos`, `goals`, `objectives`,
permission audit journal, tool-result index chunks.

**Wire-only (never persisted):** `post_answer_lanes`, `context_breakdown`,
the completion judge's full record, turn-bus facts, the raw obs stream
itself.

**Memory-only (frontend):** `turnRecord` (the recorded obs stream of the
current turn), `lastMetrics` (incl. `turnStages`/`postAnswerLanes` — parsed
and stored but **rendered nowhere**), `SessionStats` (resets on reload),
reflection/passive logs (cap 20), State-Explorer runs (localStorage, last 10,
its own `EngineEvent` seq/t_ms timeline — the app's one existing
trajectory-shaped store).

**Export fields (sessionsToJson, exportChats.ts:176-250):** message id/role/
content/timestamp, model/provider, toolCalls (without runId/timestamp/
retryCount/retryAttempts), thinking, acknowledgement, error, performance
(latencyMs, promptTokens, completionTokens, tokensPerSecond, model,
provider — **no cached tokens, no llm_calls, no turn_stages, no breakdown**),
agentRuns, agentPhases, fileResults. Missing entirely: injectedItems,
thinkMs, thinkingSegments, statusText, responseBlocks, candidates.

## Deliverable 4 — Invisible execution stages

1. **The routing decision** — which path a turn took (fast vs loop) and why.
   Log-only. On the owner's three turns this invisible decision is the single
   biggest cause of the 564-vs-6159-vs-6301 spread (see Deliverable 5).
2. **Context gathering** — history/memory/parent-session reads emit nothing;
   their durations are unknowable after the fact.
3. **Model-call boundaries** — no adapter records submit time, first byte, or
   last byte. The fast path emits `provider_call_start` (with a **monotonic
   seconds** `started_at` — a different clock domain than every epoch-ms
   stamp) and a timestamp-less `provider_first_byte` (agent_runtime.py:1471,
   1507 — verified in the live capture); the loop path emits neither. The
   heartbeat's "waiting for the provider" stall detection therefore cannot
   fire on loop turns (chat.py:500-519 reads the pair's history).
4. **Per-call usage and payload** — last-call semantics overwrite
   prompt/completion/cached each call; per-call latency is a log line; the
   actual rendered payload is captured only by the off-by-default env audit.
   What the model saw on a finished turn is not reconstructable.
5. **`context_breakdown`** — computed per full iteration, scaled to the
   provider total, but last-call-only, wire-only, never persisted, never
   exported, absent on init-direct answers, absent entirely on the fast path.
6. **Iteration-cap hits** — silent (loop.py:3997-4005), unlike the
   wall-clock cap which emits.
7. **Title generation/refine** — fully silent (chat.py:677-683, 1281-1318).
8. **Post-turn lanes** — bounded and event-tagged, but their wall-clock holds
   the SSE open with per-lane durations only on the wire.
9. **The raw event stream** — never persisted; only projections survive. The
   observation snapshot caps at 50 events. A finished turn cannot be replayed.
10. **Frontend execution state** — strip/timer/anomaly records, `answerMs`,
    `turnStages`/`postAnswerLanes` (parsed, stored, never rendered) are
    memory-only and vanish on reload.
11. **Attempted-vs-never-attempted** — the brief's distinction is not
    uniformly expressible today: silence is ambiguous between "decided
    against", "never ran", and "ran but emitted nothing" (e.g. a skipped
    Thinker consult and a crashed consult look identical in the record).

## Deliverable 5 — Explanation of the current measurement inconsistencies

**(a) Turn 2's 3 ms user→assistant timestamps vs 14,610 ms latency.**
Both numbers are real; they measure different events. `latency_ms` is a
monotonic wall clock taken at runtime entry and closed at completion
(agent_runtime.py:915 → 2304 / fast path 1436 → 1572 — verified first-hand).
The exported `timestamp` of each message is the **DB row-write instant**
(`message.timestamp or time.time()`, db.py:419). On the fast path the user
row is awaited immediately before the assistant persist **after the timed
work is done** (1594 → 1606) — my live capture measured the two inserts
0.7 ms apart with `latency_ms` 253 for the same turn, reproducing the
owner's 3 ms/14,610 ms shape exactly. On the loop path the user row is
fire-and-forget at turn start (1711-1719), so user→assistant row distance
≈ the whole turn — which is why turn 3's timestamps differ by ≈ its latency.
Timestamps tell when the record was written; latency tells how long the work
took. Neither is a lie; together they are not a timeline.

**(b) 564 vs 6,159 vs 6,301 prompt tokens.** Two different prompt
assemblers, chosen per turn by an invisible routing decision:
- The conversational/trivial fast path sends ONE system message (a compact
  chat prompt + boot-cached user-context and about-user suffixes) + at most
  4 history messages + the user message (trivial_input.py:1106-1117) — the
  ~564-token class.
- The parent loop sends the stable system prompt + dynamic turn context
  (intent tail, environment block, memory block, intent history, workspace
  and todo state, goal route) + tool schemas + history + turn additions
  (loop.py:3567-3685) — the ~6K class.
The capabilities question took the fast path; the greeting and the compliment
took the loop (my capture reproduced exactly this split on the same three
messages). Turn 3's slightly larger prompt than turn 1's is consistent with
one more turn of accumulated history/memory. **The spread is path routing,
not context growth.** Which is itself the finding: a tiny social gesture and
a capability tour can land on either path, and nothing in the record says
which ran or why. The number the owner asked to justify is currently
unjustifiable from the record — by design of the missing stage events, not
by accident.

**(c) tokens/sec arithmetic "explaining" latency.** `tokensPerSecond` is
computed as completion tokens ÷ **whole-turn wall clock** (renderer
useLocalMind.ts:1466-1468; server at history-read time, sessions.py:181-185).
The ChatStatsStrip tooltip claims "provider output tokens per second of
decode time" — that label is wrong today. So `latency ≈ completion ÷ tok/s`
is circular arithmetic on the same number, not independent evidence, and it
cannot isolate pre-generation delay. The advisor's inference that turn 1's
25.9 s was "consistent with generation time" is an artifact of this
definition, not proof the model generated for 25.9 s.

**(d) Where the pre-generation seconds actually hide.** On loop turns:
routing, context gathering, prompt assembly, the init-classify call, any
Thinker consult, then the model call — and none of these boundaries are
stamped except init lifecycle events. `turn_stages.first_token` (the
runtime's first thinking-or-text chunk) is the only pre-generation boundary
that survives, and only on loop turns (fast-path turns persist no
`turn_stages` at all — verified in the capture: turn 2's metrics lack the
key). The adapter-level submit→first-byte window — where provider queue and
cached-prefix processing time live — is recorded nowhere on any path.

**(e) promptTokens semantics.** The export's `promptTokens` is the **last
model call's** prompt (loop.py:567-584 last-call semantics by design — the
meter shows what the next call carries), not the turn's total; the
`total_*` accumulators exist and are correct but are not exported. On the
owner's greeting turn (4 calls), 6,369 was the final call's context. The
"99% cached" figure rides the same event. Whether the provider's reported
prompt base on turn 2 (564) could itself be cache-adjusted accounting rather
than our assembly cannot be settled without a real-provider trace — flagged
as an open question the trace capability resolves definitively (persist the
per-call reported usage next to the per-call local estimate).

**(f) Other named inconsistencies in the brief.** "Recorded timestamps vs
actual event ordering": row-write instants vs emit-time stamps vs renderer
arrival clock (three clocks). "Agent status in the UI vs backend state":
the strip's state machine is driven by wire events that carry no backend
timestamps, and `metrics.latency` on `/api/metrics` measures a **different
window** than the persisted `latency_ms` (parent-loop phase only,
agent_runtime.py:1887 → 2294 — a third definition sharing the name).

## Deliverable 6 — Proposed full execution-trace capability

Design principle first (the brief's own words, adopted as the contract):
**an event-backed execution record, not a logging system.** Events are
recorded as they happen; nested operations keep parent-child identity;
component identity travels with every event; successful and unsuccessful
decisions are both recorded; "never attempted" is distinguishable from
"attempted and failed"; secrets never enter the record; large payloads are
referenced, not inlined.

**Shape.** One durable, append-only per-turn event stream — LocalMind already
has the right primitive in `ObsEvent {type, data, ts}`. The change is not a
new machine; it is (1) persistence of the stream itself, (2) a small set of
missing events, (3) one clock discipline.

- **Trace identity & correlation:** `turn_id` (minted at transport entry,
  today implicit), per-event `seq`, and the existing `run_id` contextvar
  chain for parent/child. Correlation ids let any event be grouped to its
  turn, its run, and its model call.
- **Persisted stream:** the per-turn collector history lands in a
  `turn_trace` store (JSONL per turn, or a trace table keyed by turn_id)
  **in addition to** — not instead of — today's projections. Run tree, phase
  strip, injected ledger and tool pills become pure folds of the stream
  (they already are folds; the stream just stops being discarded).
- **The missing events, mapped to the brief's measurement table:**

| Brief's measurement | Event to stamp | Where |
|---|---|---|
| Request received | `turn_accepted {turn_id, session_id}` | transport entry |
| Path decision (incl. negative decisions) | `path_selected {path, reason, classifier, confidence}` — recorded even when the decision is "no tools needed" / "fast path" | routing site |
| Context assembly started/completed | `context_assembly_start/end {sources: {history, memory, parent, attachment} sizes}` | gather + assembly |
| Model request submitted / first token / completed | **adapter-level per-call stamps**: `model_call {call_id, run_id, intent, submitted_at, first_byte_at, last_byte_at, usage {prompt, completion, cached, total}, payload_chars, payload_sha}` | in the provider adapter boundary so it covers every path and every call, loop and fast alike |
| Prompt composition | per-call `context_breakdown` (already computed on iterations) attached to the same `model_call` event + persisted | loop + a fast-path equivalent |
| Response delivered | exists (`response_ready`) — keep | loop/runtime |
| Turn completed | exists (`turn_completed`) — keep | runtime |
| Tool execution | exists (started/done, retry ledger) — keep | loop |
| Memory activity | exists for stored/retrieved events; add durations | memory lanes |
| Errors and retries | exists on tools; add the adapter's retry policy decisions as events | adapter |
| Attempted vs never attempted | skipped stages emit `stage_skipped {stage, reason}` (the `stage_timing status="skipped"` convention already exists) | each gate/lane |

- **Clock discipline:** every event carries epoch-ms. Monotonic values may
  appear only as explicit `{monotonic_delta_ms}` fields inside an event that
  already has an epoch anchor — never as the only timestamp of a record
  (fixes the `provider_call_start.started_at` domain mix found live).
- **Redaction:** existing pattern applies — tool events already strip raw
  output for children (obs.py:179-183); model-call events carry sizes and
  hashes, never keys or unbounded payloads; the full payload stays available
  only behind the existing env-audit switch.
- **Conversation snapshot ↔ trace split:** the chat export gains one field —
  `traceRef {turn_id, recorded_at}` — and optionally a compact per-turn
  summary (call count, path, gate verdicts). The heavy trace stays out of
  the export; the export references it. The history endpoint exposes
  `turn_stages`/cached/llm_calls (persisted but currently unreturned —
  sessions.py:173-195).

**The State Explorer is the inspectable interface.** It already renders a
`seq`/`t_ms` event timeline with rewind over a persisted run store — the
exact contract an execution trace needs. Rendering a turn's trace through
the same projection (and letting TurnView/Agents-tab keep consuming their
folds) gives the brief's "open any conversation and explain what happened at
every stage" without a new UI species.

**What this enables immediately:** the owner's experiment table (fresh vs
existing session; prompt composition per call; time before first token;
generation time; model calls; replan cycles; tool calls) becomes answerable
from the record per turn — no inference from final responses, per the
brief's constraint. And B-2026-10-31-25's relevance-budget work gains its
ground truth: what every token actually bought.

## Deliverable 7 — Integration recommendations

1. **Build order (smallest surface first, each independently shippable):**
   (a) persist the per-turn event stream verbatim (trace store + turn_id +
   seq) — one write site, everything else keeps working;
   (b) adapter-level `model_call` stamps (submit/first-byte/last-byte, usage,
   payload size/hash) — the single highest-value addition, it converts the
   whole pre-generation band from invisible to measured;
   (c) `path_selected` + context-assembly start/end events;
   (d) persist `context_breakdown` + `post_answer_lanes` with the turn (they
   exist on the wire today and die there);
   (e) export `traceRef` + history endpoint exposing the persisted stage
   maps; (f) State-Explorer trajectory rendering of a turn trace.
2. **Do not** widen the SSE contract further until (a) exists — the wire is
   already the richest surface and the least durable one; the gap is
   persistence, not more event types.
3. **Do not** rebuild the projections — they are folds already; point them at
   the persisted stream so reload/replay and live view share one source.
4. **Fold in what exists:** Rosa's `turn_stages`/`post_answer_lanes`, Nora's
   event-time workspace stamps, the injected-items ledger, the retry ledger,
   the actions table. The trace is their union plus the missing boundaries,
   not a parallel system.
5. **Honest limits of this investigation:** no real provider was reachable
   from the sandbox, so provider-side queue/cache accounting (the last open
   question in Deliverable 5e) is inferred from adapter code, not measured;
   the deterministic-provider capture proves the wire/persistence contract,
   not model timing. A real-provider before/after remains the acceptance
   test for slice (b), per the standing verification bar.

— Zuri (S011), 2026-11-01
