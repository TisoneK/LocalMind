# External-audit intake — owner-supplied ChatGPT review of LocalMind (2026-10-31)

Session: Leila (S007). The owner brought an external audit of LocalMind
(a ChatGPT conversation reviewing an exported LocalMind session, plus two
screenshots and the exported session itself) and asked that nothing in it
be missed or overlooked. This document is the intake: every claim in the
audit is inventoried, verified against the actual codebase where that is
possible from this sandbox, mapped onto what LocalMind already has, and
either converted into a backlog row or recorded as advisory. No product
code was changed in this session.

## Provenance — what came in

| Item | What it is | Status of my review |
|---|---|---|
| ChatGPT share `6ae5e1ff-1e9c-83ea-bfd2-a378bca6f56d` | The audit conversation (8-capability roadmap, 12-problem diagnosis, turn-lifecycle investigation) | Rendering was attempted with a real headless browser per the owner's suggestion; ChatGPT's Cloudflare edge blocked the sandbox IP ("Unable to load site … Ray ID"). The owner's pasted export of the same conversation (45,344 bytes) was verified complete: no truncation markers, head and tail match the live conversation's first and last messages. Everything below is read from that paste. |
| `LM-CHAT.jpg` | LocalMind v0.5.16 live screenshot, "Friendly greeting" session, turn 2 in flight (glm-4.5-flash, Local) | Read in full. This is the session the audit's numbers refer to (greeting turn 8.0s / 547.92 tok; turn 2: prompt 6.7K, cached 5 (92%), completion 273, latency 23.9s, 2 turns · 0 steps). |
| `LM-CHAT PROBLEM.jpg` | The full-screen error boundary: `Cannot read properties of undefined (reading 'retryAttempts')` | Already fixed earlier today: Zara (S005) `05551ec4` (Thought-row crash) and Maya (S006) `4f688dd3` (scoped `RecoveryBoundary` recovery). Nothing new to do; listed here only to close the loop. |
| `localmind-chats-1-2026-10-27.json` | Export of the "Capability inquiry" chat (the ⚠️ one in the sidebar): greeting, capability question, "What's the weather like where I am" | Read in full, including tool calls, todos, agent run, thinking and the structured error. |

## Part 1 — Claims verified against the code

### 1.1 Perspective reversal — CONFIRMED, live

The screenshot shows the thinking text "The user is stating that they are my
creator…" (correct) and the reply "As your creator, I'm sure you have
valuable insights…" (relationship reversed). This is a model-level
grounding failure, exactly as the audit classifies it: the understanding is
right, the generated text inverts the speaker/owner relationship.

The audit is also right that this must NOT be fixed with a pronoun
substitution rule — the correct polarity depends on who established the
relationship ("I'm your creator" vs "you're my assistant" vs quoted speech).
What is actionable here is small and concrete:

- Add this exact exchange to a regression/eval set (the audit's own
  suggestion, and a good one — it is cheap to reproduce and meaningful).
- Evaluate a bounded consistency check on replies that assert a
  relationship: who is speaking, who is addressed, does the reply preserve
  the polarity the context established. Same shape as the existing
  reply-is-pending judge lane (ADR-66): read-only, bounded, nudges only.

→ Backlog row **B-2026-10-31-21**.

### 1.2 Irrelevant tool selection on a reflective turn — CONFIRMED as observed

The audit reports (from the session it saw): a self-assessment request
produced an elaborate plan, a gate cycle, and exactly one tool call —
`get_goal` — which returned `{goal: null, activation: "disarmed"}` and
contributed nothing; the turn then answered anyway. I verified the
mechanism: `backend/src/tools/goal.py` reads/mutates the durable
same-session goal; "disarmed" is the designed no-goal state. Calling it on
"assess yourself" is a plausible-sounding but wrong selection — the model
confused having a self with having a reason to read goal state.

What already exists (the audit assumed missing): the task-type distinction
it recommends is built — `Intent` (~40 values) and compositional
`Capability` in `backend/src/core/models.py`, a dispatcher that classifies
intent and can withhold tool schemas entirely on answer-only calls
(restored via FORCE_TOOL on recovery), and `DESCRIBE_TOOL` for on-demand
long-tail schemas. So the fix is not "build the distinction"; it is:

- A replay set of reflective/identity turns ("assess yourself", "what are
  you", "who made you") asserting which tools are acceptable (ideally
  none) and that the answer does not lean on a null meta-tool result.
- Tightened dispatcher/answer-only guidance for identity/reflective
  questions, verified by that replay set.

→ Backlog row **B-2026-10-31-22**.

### 1.3 Turn lifecycle: "Working" persists after the answer is visible — CONFIRMED PLAUSIBLE, attribution required

The owner's observation (and the screenshot): the reply is fully on screen
while the panel still says "Writing the answer…", the status strip counts
"Deep diving for 23.9s…", and Stop is live. The audit suspects the turn
lacks "a reliable definition of when its work is actually finished." The
code says otherwise in one direction and agrees in another:

- A finished definition exists: the SSE protocol ends `token → done (usage)
  → obs_event turn_complete` (`backend/src/api/routes/chat.py`), and the
  loop has real done-gates.
- But there are genuine post-answer lanes that hold the tail:
  - **Completion judge** (ADR-66, `backend/src/core/agent/completion_judge.py`):
    an extra model call that judges DONE vs PENDING; the loop **blocks on it
    at the final-answer gate**, bounded at 8s, on SHORT replies only
    (≤600 chars — the screenshot's reply ≈490 chars, so it fires).
  - **Acceptance gate** (`loop.py::_acceptance_gate_at_final_answer`): when
    success criteria are unmet with iterations remaining it makes an
    explicit replan LLM call and the loop continues.
  - Post-answer memory/reflection lanes (passive-memory and
    reflection-lesson obs events are emitted on the turn bus).
- The screenshot's own numbers also show streaming itself is most of that
  23.9s: 273 completion tokens at 14.13 tok/s ≈ 19s. The owner separately
  reports other turns where the answer lands well before the timer stops —
  those are the cases the lanes above explain.

The audit's instrumentation request is therefore the right move, and it is
cheap: record per-stage timestamps (turn_started, model_started,
thinking_started, first_token, response_completed, model_finished,
agent_finished, turn_completed) plus tokens and which lanes ran after the
last token. Then decide the user-facing contract: whether the UI should
show a distinct "answer ready — finishing up" state instead of
indistinguishable "Working", whether Stop should be honest about what it
can still stop, and (with B-2026-10-31-5 / ADR-66b) whether post-turn
lanes should hold the SSE connection open at all.

The audit's three diagnostic questions land here, for the owner to answer
during that pass: (1) does the reply stay visible while the timer grows?
(2) does the agent stop by itself? (3) does the terminal show extra model
calls in that window?

→ Backlog row **B-2026-10-31-24** (includes prompt-size attribution below).

### 1.4 Prompt growth 547 → 6,148/6.7K tokens — CONFIRMED observable, attribution missing

The greeting turn's prompt was 547.92 tok; the follow-up's was 6.7K (92%
provider-cache hit). Candidates: system prompt, 39 tool schemas, history,
memory facts, prior-turn thinking. The cache hides most of the cost after
the first turn, but the first-turn latency and the second-turn size are
still real. No per-section accounting exists today; the audit's ask
("investigate what is being passed") folds into B-2026-10-31-24 as a
prompt-composition breakdown delivered alongside the timestamps.

### 1.5 The Oct 27 "Capability inquiry" export — ALREADY FIXED on main

The audit never saw this export; I did. Its story: web_search succeeded
(Bing, 8 results) → web_fetch AccuWeather 403 → the tool's own recovery
hint said "try the NEXT URL, synthesize from snippets, do not invent" →
web_fetch MSN **succeeded with the actual weather** (25°C, partly sunny) →
the provider died on the write-up with `payment_required` (balance=0) →
the turn ended as a generic error ("switch to a larger model" — wrong
advice for a quota failure).

On main this is already repaired at the root:

- `backend/src/core/agent/turn_outcome.py` — the DEGRADED_ANSWER done-rule
  exists **because of this exact incident** (the comment cites the 12:45
  run of 2026-10-27): a provider death after successful tool work now
  preserves the evidence and delivers what it supports with an honest note
  about what stopped the write-up, instead of throwing the run away.
- `backend/src/core/error_normalizer.py` maps `payment_required` as a
  known terminal, non-retryable code; `_TERMINAL_DEATH_CODES` includes it.
- The frontend's provider-death honesty fallbacks
  (`frontend/src/lib/localmind/errorText.ts`) name the provider and code
  instead of the generic try-again line.

So the audit's general claims "weak task execution" and "no error
recovery" do NOT hold for this evidence: the tool layer recovered from the
403 correctly and the failure was a provider balance, now handled with
evidence preservation. No backlog row; recorded here as verified-fixed.

### 1.6 What the audit recommends that already exists (so we don't build it twice)

| Audit claim | Reality on main (anchors) |
|---|---|
| "No verification cycle; verification must use evidence, not self-narration" | Acceptance gate rejects the model's "done" against success criteria and refuses "done" when the last real action failed (`loop.py`); completion judge is grounded in a tool-evidence digest; association-grounding judge queued (B-2026-10-31-15); fresh-eyes acceptance judge is on the Target's NEXT list (read-only, re-reads the deliverable against the original request). |
| "Build a Tool Capability Registry" | 39 tools registered with schemas; `DESCRIBE_TOOL` loads long-tail schemas on demand; narration labels every call. A registry table would duplicate this; the real gap is selection behavior (→ B-2026-10-31-22). |
| "Task-type distinction (reasoning-only / retrieval / tools / multi-step)" | `Intent` + compositional `Capability` enums, dispatcher classification, tool-schema withholding with FORCE_TOOL restore. Exists; needs the reflective-turn evals (→ B-2026-10-31-22). |
| "Don't trust thinking text as ground truth — instrument decisions" | Agreed and already partially practiced (obs events, bus facts, run traces); B-2026-10-31-24 extends it to per-stage timing. |
| "Agents spawned unnecessarily" | Outdated: live multi-agent delegation is parked by standing decision — the Parent is the only active agent. Orchestration cost on chat turns is real but is a turn-economy question (B-2026-10-31-14), not a fan-out one. |
| "Memory should consolidate and retrieve by relevance" | Reflection lessons exist; the known gap is recall-by-relevance at decision time — already queued as B-2026-10-31-9 ("storage is not application"). The audit adds emphasis, not a new task. |
| "Creativity / challenge assumptions" | Covered by the anti-sycophancy guard row B-2026-10-31-10 (concede only with evidence, defend when the user is wrong). |
| "Learning from corrections" | B-2026-10-31-16 (feedback-turn routing) + B-2026-10-31-9 cover the two halves; the audit's three-level correction split (fix response / update working context / reusable lesson) matches the existing design and is recorded here for B-9's implementer. |
| "Fact vs assumption classes in replies" | The enforceable core is ADR-67's confirmable-refusal program (B-2026-10-31-4: refuse only on a verified fact, name the fact and the confirming flag). Response-language labeling (verified/observed/inferred/assumed) is advisory — see Part 3. |
| "Asks the user to do too much thinking" | Legit behavior gap on the self-assessment turn; it is a prompt/Thinker-contract matter, covered by the eval harness's "unnecessary questions" metric once B-2026-10-31-23 lands. |

### 1.7 Genuinely new work the audit surfaces

1. **Perspective/speaker-identity consistency** — nothing in the office
   covered it; now B-2026-10-31-21.
2. **Reflective-turn tool selection** — never replayed as a failure class;
   now B-2026-10-31-22.
3. **A standing evaluation harness** — the audit's strongest structural
   recommendation, and it aligns with this office's live-verify
   discipline (`system/live-testing.md`): scenarios × metrics (task
   completion, factual accuracy, tool success, recovery rate,
   unnecessary questions, latency), run against the live app; B-21/B-22
   cases feed it. Now B-2026-10-31-23.
4. **Turn-close attribution + honest completion contract** — now
   B-2026-10-31-24.

## Part 2 — Mapping the audit's 8-capability roadmap onto LocalMind

The audit proposes eight capabilities in three build phases. Mapping each
to what LocalMind already has or has queued (so the owner can decide
re-prioritization without double-building):

| Audit capability | LocalMind home |
|---|---|
| 1 Conversational Context Engine | Dispatcher/intent + the conversation-recall lane (Nadia S002, af347f95/253ae0b4); "structured clarifying questions" is already a Tier-2 Target candidate. The "continuously updated understanding" framing is advisory until the eval harness can show a gap. |
| 2 Intent/objective recognition | `Intent`/`Capability` + dispatcher (exists); confidence-gated questioning → Tier-2 candidate. |
| 3 Tool intelligence / execution orchestration | 39 tools + withholding + gates (exists); gaps → B-22; **MCP client support (Target NEXT 1)** widens exactly this surface. |
| 4 Memory systems + consolidation | memory_op, vector facts, reflection lessons; recall-by-relevance → B-9. |
| 5 Reasoning/problem-solving | Dispatcher plan + success criteria + orchestrator replan (exists); efficiency → B-14 (turn economy). |
| 6 Self-awareness / self-correction | Acceptance gate, completion judge, grounding judge (B-15), fresh-eyes judge (Target NEXT 3). |
| 7 Creativity / independent thinking | B-10 anti-sycophancy. |
| 8 Continuous learning | Reflection lessons → recall (B-9), feedback routing (B-16). |

The audit's own closing caution — "don't translate observations into new
agents; don't build ten independent agents" — matches this office's
Parent-only standing decision and the owner's no-borrowed-vocabulary
ruling. Nothing above should be built as a new agent; every mapped item
lands in an existing subsystem.

## Part 3 — Advisory (not backlog rows)

- **Fact-class labeling in replies** (verified / observed / inferred /
  assumed): worth a prompt-contract experiment after ADR-67's rollout
  (B-2026-10-31-4) establishes the verified-fact vocabulary; until then a
  labeling convention has no enforcement to lean on.
- **The audit's state machine** (GENERATING / RESPONSE_READY / EXECUTING /
  FINALIZING / COMPLETED): the useful, adoptable part is a
  user-visible RESPONSE_READY-vs-COMPLETED distinction, which belongs to
  B-2026-10-31-24's contract decision. The full five-state machine is
  over-specified for a single-agent turn.
- **The audit's vision question** (personal conversational AI vs
  autonomous executor vs learning system vs all three): this is an owner
  decision that re-weights the Target. Recorded here verbatim as open;
  the standing Target (MCP client → explorer subagent → fresh-eyes judge
  → skill packaging) remains in force until the owner re-ranks.

## Part 4 — Backlog surgery done in this intake

The backlog was at its 20-row cap. To land the four new rows (B-21…B-24)
four rows moved to the parking lot (deferred, with reasons — veto
freely):

- B-2026-10-31-8 (Windows verification of the state engine) → **P-2026-10-31-2**: blocked on owner-box availability, no code work possible from this side.
- B-2026-10-31-11 (memory edit path tolerance) → **P-2026-10-31-3**: small, low-traffic, no recent demand.
- B-2026-10-31-12 (conversation-too-long false positive) → **P-2026-10-31-4**: needs a repro on the owner's live setup.
- B-2026-10-31-17 (repo-root pytest config) → **P-2026-10-31-5**: small infra nicety, no active failure traced to it today.

B-2026-10-31-5 (turn-bus follow-ons) gained a cross-reference to
B-2026-10-31-24: the owner-observed post-answer "Working" window is the
user-visible face of its "slow reflection holds the trailing SSE open"
note.

## Evidence index

- `frontend/src/lib/localmind/turnTimeline.ts`, `ChatStatsStrip.tsx` — "Working / Writing the answer / Deep diving" rendering.
- `backend/src/api/routes/chat.py` — SSE protocol: `token` → `done` → `obs_event turn_complete`.
- `backend/src/core/agent/loop.py` — acceptance gate `_acceptance_gate_at_final_answer` (line ~7850), FORCE_TOOL restore, done-gates; 10,219 lines total.
- `backend/src/core/agent/completion_judge.py` — ADR-66 judge lane: 8s bound, ≤600-char replies, evidence digest, blocks at the final-answer gate.
- `backend/src/core/models.py` — `Intent` (~40 values), `Capability`, `DESCRIBE_TOOL`.
- `backend/src/tools/goal.py` — `get_goal`/`update_goal`, authority rules, "disarmed" state.
- `backend/src/core/agent/turn_outcome.py` — DEGRADED_ANSWER done-rule; `_TERMINAL_DEATH_CODES = {payment_required, auth_error}`.
- `backend/src/core/error_normalizer.py` — `payment_required` normalization.
- `frontend/src/lib/localmind/errorText.ts` — provider-death honesty fallbacks.
- Uploads: `LM-CHAT.jpg`, `LM-CHAT PROBLEM.jpg`, `localmind-chats-1-2026-10-27.json`, the owner's audit paste (45,344 bytes, complete).
