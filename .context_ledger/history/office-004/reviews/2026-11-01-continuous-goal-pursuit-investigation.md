# Continuous Goal Pursuit — Investigation (Amara, S016, 2026-11-01)

**Mandate (owner brief, 2026-11-01):** LocalMind "feels like it's designed to run
1 turn == 1 step". The location conversation in the newest export is the evidence:
the agent re-derives the situation from scratch on every message, asks the same
clarifying question twice, and *suggests* `web_search`/`sysinfo` in prose without
executing either. The owner asked for an investigation of task continuity —
whether an objective survives individual model calls — separate from the prompt
investigation, plus a study of how the external reference harness handles real
long and heavy work. Investigation first, then the build.

**Method:** every claim below was read first-hand from the code at HEAD
`1aa3bc7a` (post S015); the reference study was verified from the cloned source
at `/home/z/my-project/research/deepseek-harness` HEAD `22ddee37` (it moved past
the `ce7073d5` anchor S010 recorded — noted, nothing read depended on the drift).
Exploration sweep + first-hand reads of every load-bearing site listed.

---

## 1. The owner's seven questions, answered from code

### Q1 — Is an objective created and maintained?
**Yes, but almost invisibly.** There is a durable per-session goal
(`session_goals`, migration 013; `storage/goals.py::GoalStore`, compare-and-set
revisions, phases active/paused/blocked/complete, round accounting with a 256
cap). The model creates and mutates it only through its own `update_goal` tool
calls (`tools/goal.py`). **No ordinary turn ever sees the goal**: the store is
read only by the chat route's round driver (`api/routes/chat.py:628,703-707`),
the goal tools, and the sessions API. Neither the parent loop nor the fast path
injects it. On a session with an active goal, the model only knows about it if
it calls `get_goal` or if the turn IS a `<goal_round>` continuation.

### Q2 — Do outstanding questions and expected actions persist?
**No — and the scaffold proves it was intended.** `core/agent_runtime.py:291`
declares `self._pending_clarification: dict[str, dict] = {}` — cleaned up in
`cleanup_session`, never written, never read anywhere in the repo. A turn that
ends in a clarifying question leaves zero state: the clarify exits
(`core/agent/loop.py:2644-2656` confidence gate; `2904-2919` pre-init
clarification) yield the question and `return`. Nothing records "awaiting the
answer to X".

### Q3 — Can the loop execute multiple reasoning/action/observation cycles?
**Yes.** `core/agent/loop.py:4158` iterates to a hard cap (parent config: 20
iterations / 600s, `agents/parent/agent.py:17-24`; absolute ceiling 100); tool
results are appended as proper `role:"tool"` messages and feed the next model
call in the same turn (5160-5202 and seven more dispatch sites). The in-turn
engine is not the problem.

### Q4 — Do tool results return to the same active objective?
Within a turn, yes (Q3). Across turns, no — the per-turn `TaskState` is built
with `objective=_user_message_text(messages)` (`loop.py:3284-3289`) and dies
with the turn; the derived goal route (`core/agent/goal_interpreter.py`) is
regex over the current message only — "yes" derives an empty tree.

### Q5 — Does a new user message resume, modify or abandon an existing objective?
Only through the goal-rounds driver, and only inside one SSE request.
`core/goal_rounds.py:166-274` queues `<goal_round>` rounds **while the chat
request is open**; a dropped connection or restart ends the deep dive while the
goal row stays `active` but disarmed (arming is process-local by design —
`storage/goals.py:6-9`, an explicit safety contract). For ordinary conversation
there is no resume semantics at all.

### Q6 — Does the agent independently determine completion?
Within a goal, yes (`update_goal complete`; blocked requires a persisted
3-round condition, `tools/goal.py:193-202`; cap writes a durable blocker,
`core/goal_rounds.py:129-142`). Within a turn, the completion judge classifies
DONE/ACT/INCOMPLETE. But a *conversational* objective (the location question)
never becomes a goal, so none of this machinery engages.

### Q7 — Do interface and backend represent an active task across turns?
Partially. The UI has a goal meter (`ChatStatsStrip.tsx:47-76`, `Goal N/M`,
paused/blocked states), goal SSE events, and restore-from-API; there is no
goal-authoring UI (no caller of `update_goal` outside the model). History and
export do not carry the goal; only persisted `<goal_round>` rows represent it.

## 2. Why the location conversation behaved 1-turn-1-step (mechanism chain)

1. **"yes" after a statement → pleasantry.** `approves_pending_offer`
   (`core/trivial_input.py:903-921`) routes a bare affirmation to the loop only
   when the last assistant message ends with `?` or matches an offer phrase.
   The fast path's trivial prompt then answers the gesture as small talk —
   the reply is never interpreted against anything.
2. **"yes" after a real question → re-clarified.** The message does reach the
   loop, but the initialization classify's rule — a bare phrase with no
   referent MUST clarify, "only choose execute if the conversation history
   makes the referent obvious" (`core/agent/initialization.py:154-162`) — has
   no record that the referent is *the agent's own outstanding question*, and
   the clarify exit is stateless (Q2). Repeating the clarification is the
   expected output of this machinery, not a one-off prompt defect.
3. **"you clearly can see" → suggests tools, executes none.** It reaches the
   loop, but nothing orients the turn to the outstanding objective; a
   capability statement ("I can run web_search or sysinfo") classifies DONE by
   the completion judge ("asked the user a question, or offered a choice"),
   and no state anywhere says an action is *owed*.
4. **The durable goal never engages** because no turn creates one for a
   conversational objective (Q1), and even if it existed, ordinary turns would
   not see it.

## 3. How the external reference handles real long and heavy work
(verified from source at HEAD `22ddee37`; reference-only — nothing here enters
product artifacts in borrowed vocabulary)

- **One durable goal per session** (`packages/goal`): create/edit/pause/resume/
  complete/block/clear; "records completion state rather than scheduling work";
  model tools + a human command; survives restarts, resumes, forks.
- **An idle-driven continuation driver** (`goal-round-driver`): the decisive
  architectural difference from LocalMind's driver. Rounds fire **at
  whole-agent idle** — between human messages, as distinct request series —
  not only inside one live request. Reservation-then-admission with revision
  fences; a durability flush must succeed before the next round is queued
  (flush failure disarms); only rounds that actually enter history consume the
  cap; at the cap a durable `round-limit` blocker is recorded; human work
  arriving before a reservation makes automatic work yield; after
  resume/fork/restart an active goal stays disarmed until an explicit human
  resume — it never revives on its own.
- **A whole-list plan** (`packages/todo`): the model replaces the entire list
  per update; it persists across turns and reopened sessions; hosts render the
  standing plan.
- **Fresh-agent heavy loops** (`experimental/tool-ralph`): an explicitly
  human-request-only fixed script — fresh child per round, one immutable
  objective, only a bounded structured report crosses rounds, the shared
  workspace is the long-term memory, invalid reports fail loudly. Kept strictly
  separate from ordinary goal work.
- **Durability discipline** throughout: state changes create flush obligations;
  continuation is fail-closed (a failed durability write disarms, never
  silently retries).

**LocalMind already has** the durable goal row, the model tools, round prompts,
round caps, blocked floors, and the whole-list todo store. **What it lacks** is
(a) idle-continuation (B-2026-10-31-13's recorded remainder), (b) any
conversational continuity: outstanding questions and the active objective are
invisible to ordinary turns, and (c) short-reply resolution against the
agent's own outstanding questions.

## 4. Gap table (own vocabulary)

| # | Gap | Evidence | Fix slice |
|---|-----|----------|-----------|
| C1 | Outstanding questions leave no state; the `_pending_clarification` slot is dead scaffold | agent_runtime.py:291; loop.py:2644-2656, 2904-2919 | **Open-question record** (durable, per session) + short-reply resolution at the routing seam |
| C2 | Re-clarification loops: the classify rule can't know the referent is the agent's own question | initialization.py:154-162; stateless clarify exits | When a fresh open question exists, the forced-clarify exits stand down; the question renders into the turn context and the model keeps judgment |
| C3 | The active goal is invisible to ordinary turns | GoalStore read only by chat.py driver/goal tools/sessions API | **Carried-objective surface**: render the active goal into the loop's TURN band and a one-line conditional into the fast path |
| C4 | Goal-round continuation dies with the SSE request; no idle/reconnect resume | goal_rounds.py:166-274 | B-2026-10-31-13's recorded remainder (idle-tick/reconnect driver) — adjacent, not this session's slice |
| C5 | Suggested-but-not-executed actions leave nothing owed | completion judge treats an offer as DONE | Partially addressed by C1/C2 (the reply rides with the outstanding question); no new enforcement machinery this slice |

## 5. Build order (this session)

1. **Migration 015 + `storage/open_questions.py`** — `session_open_questions`
   (one current record per session: question text, asking turn id, timestamps;
   upsert = latest wins; clear). Same store discipline as `storage/goals.py`
   (short-lived connections, no state held across model calls).
2. **Recording** — after a turn's final text is known (both persist paths), a
   final text ending in `?` upserts the record; trace events
   `open_question_recorded`/`open_question_cleared` ride the durable trace.
3. **Resolution at the routing seam** (`trivial_input.py` + the fast-path gate):
   a trivial-shaped reply that is not pure social gesture, when a fresh record
   exists, is an *answer attempt* — it routes to the parent loop, never the
   pleasantry lane. Substantive replies supersede (clear) the record.
4. **Loop surfaces** — new TURN-band sections `carried_objective` (objective
   layer, slot 1020) and `open_question` (context layer, slot 1095), registered
   in `prompt/names.py` TURN-only set; the forced-clarify exits stand down when
   an open question is on record; the injected-items ledger and its source map
   learn the two new kinds.
5. **Fast path** — conditional one-line active-objective context (only when a
   goal exists); open-question recording on the fast path's persist site too.
6. **Live verification** — the owner's five-message location sequence replayed
   on the 8765 harness: assert the "yes" turns carry the open-question section
   in the audited outgoing payloads, no repeated forced clarification, the
   record lifecycle visible in the trace.

**Respected constraints:** no borrowed terminology in product artifacts; the
process-local arm-on-restart safety contract untouched; the canned-greeting
ruling untouched (social gestures with no outstanding question keep today's
behavior); ADR-68 (no canned plans); the trace discipline (events carry facts,
never payload contents).
