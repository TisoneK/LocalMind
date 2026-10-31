# Greeting-export analysis intake — the audit's second slice (2026-10-31)

Session: Nora (S009). The owner pasted a further slice of the ChatGPT audit
conversation (the same share `6ae5e1ff-…` Leila (S007) intaked earlier the
same day — this slice is LATER: the advisor analyzing the owner's SECOND
export, the "Quick check-in" greeting session of 2026-10-31 18:22–18:23).
None of its markers existed in office memory when this session started
(grep for "sup LM", "User Objective Primacy", "deepseek", "Prompt Budget",
"gate_failed_replan" over `.context_ledger/`: no hits), so this document is
its intake. The owner's directive: "I gave you to build not to ask me
again" — the immediate priorities below were BUILT this session, not queued.

## 1. What the slice contains

- The greeting session's chat export (v3): "Hey sup LM?" → 2 visible
  messages, 4 model iterations, 0 tool calls, latency 99,656 ms, prompt
  6,369 tokens (99% cached), completion 401 tokens; a
  `gate_failed_replan` phase ("Unmet: model committed to a tool action in
  prose but emitted no tool_call") at iteration 2; `agentRuns[0]` with
  `startedAt == completedAt == 1793460225183`.
- The advisor's six-point analysis (false-positive gate; reasoning loop;
  4.02 tok/s; identical timestamps; instruction leakage in thinking; final
  answer right, process wrong), priorities P1–P5, a regression-test matrix,
  a capability-flow diagram (no mandatory tool call / agent spawn /
  replan stage), a prompt-overload discussion, "User Objective Primacy"
  (4-layer instruction structure), a Prompt Budget and Relevance Manager,
  a recommendation to study DeepSeek Harness for context/prompt/trajectory
  design, and a closing observability goal: know exactly what the model
  received and what it did with it.
- Advisory note: the slice references "the six architectural capabilities
  we discussed" — the enumeration is NOT in this paste. The earlier audit
  slice's 8-capability roadmap is already mapped in Leila's intake (Part
  2); treat the "six" reference as covered there unless the owner pastes
  the missing middle. Not invented here.

## 2. Root cause — deeper than the advisor's diagnosis

The live harness (`scripts/live_test_greeting_gate.py`, deterministic
provider, adversarial init+judge) reproduced the EXACT export and split the
regression into its real stack:

1. **The classifier misrouted the greeting into an agent intent** (the
   export's own phase label reads "Replanning — analyze criteria unmet" —
   the intent was `analyze`, not `chat`).
2. **PRIMARY trigger — the stream-time tool-talk recovery**
   (`loop.py` iteration head): with the reply in an agent intent,
   `_is_tool_talk` matched the greeting reply's "thanks for checking
   **in**" against the narration pattern
   `(searching|fetching|looking up|checking).{0,30}(for|on|in|about)\b`,
   suppressed the streamed reply, and injected a **user-role message**:
   "You described wanting to use a tool but did not call it. You MUST use
   the tool-calling API directly — do NOT narrate or describe your intent.
   Call the tool now…". That injected demand is the "imagined user
   instruction" the advisor saw the model reasoning against — the model was
   quoting OUR card back, not hallucinating. (A prior session had already
   patched this site once for "Hi" via the AGENT_INTENTS gate; the
   misrouted intent walked straight past that gate.)
3. **SECOND trigger — the acceptance gate's reply-pending judge**: on a
   zero-tool turn the judge's evidence digest is empty by construction, so
   it re-judges bare text, and on the greeting it returned PENDING → one
   more replan.
4. **The reporting lie**: whichever trigger fired, the gate's obs event
   hardcoded unmet="model committed to a tool action in prose but emitted
   no tool_call" — the advisor's P1 diagnosis ("a gate that assumes a tool
   call is required because the model mentions actions") is exactly this.
5. **The telemetry lie**: every persisted workspace timestamp was stamped
   at persist-time rebuild → `startedAt == completedAt` on a 100 s turn.

## 3. What was built this session (both priorities P1–P4)

| Advisor priority | Disposition | Where |
|---|---|---|
| P1 fix execution gates | BUILT: the tool-talk recovery now requires the user's message to actually imply a tool action (or approve one) — the same condition its sibling detector uses; the acceptance gate accepts a clean zero-tool answer outright (injected-context fact requests keep their grounding/decline class checks — the fabricated-date guard is untouched and green) | `fd480e3e` |
| P2 control reasoning iterations | BUILT (same commits): a clean zero-tool turn takes ONE provider call (the pre-init conversational lane skips even the init call), zero judge calls, zero replans — measured on the live harness. The advisor's target ("one model call, zero tool calls, zero replanning cycles") is met exactly | `fd480e3e` |
| P3 separate model calls from tool calls | VERIFIED ALREADY EXISTS: `llmCalls` (provider calls that reported usage) and tool executions (`toolCalls` / `agentRuns[].tools`) are independent fields in metrics and the export; the advisor's "calls: 4" reading conflated what the record already separates. No change needed | — |
| P4 fix lifecycle telemetry | BUILT: `ObsEvent` carries emit-time `ts`; `build_run_tree`/`build_agent_phases` reconstruct from event stamps; run window = first→last event when the caller supplies none. The SSE wire shape is unchanged | `3a0f15e8` |
| P5 audit prompt construction | PARTIALLY INSTRUMENTED ALREADY: the per-section `context_breakdown` reaches the occupancy meter (verified live by Rosa S008); instruction LEAKAGE into thinking is a model-behavior symptom of the same overloaded guidance the architecture row below addresses. Queued, not separately actioned | backlog |

Regression matrix (the advisor's mandatory table) — pinned where it can run
today: gate-level in `tests/core/test_zero_tool_chat_accept.py` (greeting →
accepted, judge never invoked; misrouted intent → same; prose commitment →
nudged with the prose reason; post-evidence judge trigger → named
honestly), turn-level in `scripts/live_test_greeting_gate.py` (the full
"Hey sup LM?" turn on the 8765 harness: PASS — 1 provider call, zero
replans, no demand card, persisted record time-consistent). The
model-dependent rows (Excel transactions → file tools; web research → web
search; failed tool → recovery) belong to the standing eval harness
(B-2026-10-31-23) once a real provider is reachable from this sandbox.

Honest scope note: the sandbox holds no provider key, so the live trace ran
on the repo's deterministic provider (the established pattern, Rosa S008).
The wire/path contract is provider-independent; the judge's PENDING
behavior on a REAL weak model is covered by the adversarial fake (it
returns PENDING on the judge's exact prompt marker) plus unit tests. One
real-provider before/after on the owner's box remains the natural
follow-up, per the verification bar.

## 4. Queued (not built this session)

- **User Objective Primacy + instruction dedupe + per-turn relevance
  budget + model-visible payload reconstructability** — the slice's
  architectural program, now backlog row **B-2026-10-31-25** (medium; the
  backlog was at 19/20 rows, so it landed at cap with no prune). The
  advisor's four-layer instruction structure and the Prompt Budget
  Manager's per-source measurement fold into it. Verified-existing
  components are listed in the row so nothing is double-built.
- **DSH study** — done this session, see
  `2026-10-31-dsh-architecture-study.md` (repo verified real, principles
  extracted from source, migration cautions recorded). Per the owner's
  standing ruling the study is reference-only: adopt principles, express
  them in LocalMind's own vocabulary.
- **The advisor's capability-flow diagram** — its useful content (no
  mandatory tool call/agent spawn/replan; conditional capabilities) is
  now enforced by the P1/P2 fixes above rather than drawn as a new
  machine; restating it as a new component would re-introduce the
  over-orchestration the advisor warned against.

## 5. Evidence index

- `backend/src/core/agent/loop.py` — tool-talk recovery site (~line 6860),
  acceptance-gate zero-tool accept (~line 8021), honest unmet attribution
  (~line 8125).
- `backend/src/core/obs.py` — `ObsEvent.ts`.
- `backend/src/core/agent_workspace.py` — event-time reconstruction in
  `build_run_tree` / `build_agent_phases`.
- `backend/src/core/agent/text_tools.py:392` — the over-broad narration
  pattern that matched "checking in".
- `backend/src/core/agent/completion_judge.py` — judge lane; its prompt
  marker is what the live fake answers "PENDING" to.
- `tests/core/test_zero_tool_chat_accept.py`,
  `tests/core/test_workspace_event_timestamps.py`,
  `scripts/live_test_greeting_gate.py`.
- Commits: `fd480e3e` (gate + attribution + tests + live script),
  `3a0f15e8` (event-time telemetry). CHANGELOG: two Fixed entries.
