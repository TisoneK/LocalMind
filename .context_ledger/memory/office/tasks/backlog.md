# Backlog (work queue — actionable items only)

The queue of work a session can pick up and **do**. One row per item, in
its priority table. It is a queue, not a knowledge base: the test for a
row is "can an agent start on this and finish it?" If the answer is no —
it's a finding, an open question, an advisory "should we…?", a deferred
"someday" idea — it belongs in [`parking-lot.md`](parking-lot.md), not
here. Writing discoveries into the backlog is how a queue turns into a
57-row document nobody can work from.

**Done = delete the row. Stale = delete the row.** The backlog holds
open, actionable work only. When an item is finished, delete its row —
the completion record is the finishing session's `agents/sessions.md`
entry and the commit, never a tombstone here. When an item stops
mattering, delete it too; if it still carries information worth keeping,
move it to the parking lot first. Git history keeps every removed row,
so deleting loses nothing. (The one thing you must not do is delete a row
whose work is genuinely still open and recorded nowhere else — a row
vanishing from the diff with no session entry or promotion behind it is a
dropped handoff, not cleanup. Legacy checkbox-format backlogs:
`ledger-mem closeout` sweeps checked-off `- [x]` tombstones a session
left behind — dry run by default; `--confirm` deletes.)

**The queue is capped at ~20 rows** (`backlog_cap` in
`workflows/history.conf`; `ledger-mem check` warns past it). Twenty is a
working set, not a limit to fill. When you'd add a 21st actionable item,
prune one first: the lowest-value open row goes to the parking lot
(deferred, still valuable) or is deleted (no longer relevant) — never a
row you can't justify dropping. A queue you can hold in your head beats
a comprehensive one you can't.

**Only actionable work, and context lives where the work is.** Every row
gets a stable **ID** — `B-<added YYYY-MM-DD>-<n>`, n = that date's next
sequence in the file — and a **Summary** cell that says what to *do*, not
everything known about it. A fresh agent should be able to start from the
one line; the deep context belongs in the linked issue, PR, ADR, or
parking-lot finding the row points at, not packed into the cell. Keep
status qualifiers short ("partial", "blocked on X"). Don't append
research narrative to a row to "preserve" it — that's the parking lot's
job.

**Priority is the table an item sits in (High / Medium / Low), and it is
dynamic.** Only the top of the queue really matters — when you start a
session, the handful of High rows (roughly the top 3–5) are the work; the
rest is context, and a row that has sat in Low for many sessions is a
candidate for the parking lot, not a permanent resident. When unsure
between two tables, pick the lower one; promoting a row later is cheap,
and a backlog where everything is High says nothing.

This backlog belongs to the **current office**. When the office closes,
open items do not carry over implicitly — the closing session re-seeds
into the new office's backlog **only items with an active owner or a
clear next step**; everything else is recorded in the permanent record
(`history/office-<NNN>.md`, "Open threads") or parked. A re-seeded row
describes the work in plain words and never cites the old office's
session numbers or codenames.

Full spec: `.context_ledger/core/schemas/ledger-schema.md` →
"The backlog: a capped work queue" and "The parking lot".

## Open Items

### High Priority

| ID | Summary |
|----|---------|
| B-2026-10-31-1 | In-app State Explorer + engine selector (ADR-71): port the explorer into the app as its own interface (game tree, move list, eval bar, inspector, meters, rewindable timeline) and add the Classic/State engine setting. Reference: `docs/prototypes/state-explorer/`, `backend/src/api/static/state-explorer/`; engine package `backend/src/state_agent/` (adapter `state_agent/adapters/localmind.py`); `EngineEvent` is the UI contract. Check whether the in-flight port landed before starting. |
| B-2026-10-31-2 | State engine slice 2 (ADR-71, Simulator already ships): EXECUTE a confirmed action behind the ADR-67 confirmation flag and verify it by a read-back probe; a SECOND `Environment` adapter (CLI or filesystem) as proof the boundary holds; beam > 1; persisted state so a turn can resume. |
| B-2026-10-31-3 | Benchmark the state engine against Classic (ADR-71 §8): both engines selectable and observable, same tasks, measurable comparison, only then a decision about an `Auto` engine. Ties to B-2026-10-31-1. |
| B-2026-10-31-4 | Confirmable-refusal rollout (ADR-67): convert every tool that refuses or guesses to "refuse only on a verified fact, name the fact and the confirming flag" — start with delete (`confirm_delete`), the shell tool's destructive/mass-touch commands (replace the substring blocklist), and installs (`scope=system`); record confirming flags in the run trace. |
| B-2026-10-31-21 | Perspective & speaker-identity consistency (external audit 2026-10-31): the turn's reasoning got the relationship right ("they are my creator") while the reply reversed it ("As your creator…"). Add the exact exchange to a regression/eval set and evaluate a bounded read-only consistency check (same shape as the reply-is-pending judge) on replies that assert a relationship — who speaks, who is addressed, polarity preserved; nudge only, never a pronoun-replacement rule. Full context: `office/reviews/2026-10-31-external-audit-intake.md` §1.1. |
| B-2026-10-31-24 | Turn-close attribution + honest completion contract (owner-observed 2026-10-31; audit §1.3): the reply is fully on screen while the turn still reports Working/Deep diving and Stop stays live. Instrument per-stage timestamps (turn_started → turn_completed) plus tokens and which post-answer lanes ran (completion judge ≤8s gate, acceptance gate, memory lanes); attribute the window; then decide the contract — a RESPONSE_READY vs COMPLETED display distinction, Stop honesty, whether post-turn lanes may hold the SSE open (ties B-2026-10-31-5 / ADR-66b). Include the prompt-size breakdown (547 → 6.7K tok across two short turns — what is injected per section; 92% cache hit). |

### Medium Priority

| ID | Summary |
|----|---------|
| B-2026-10-31-5 | Turn-bus follow-ons (ADR-66b): post-turn services as lanes behind `gate()` with the post-turn budget; silent read-only grounding lanes whose verdicts gate irreversible steps; a Decider lane (safety classification replacing the shell blocklist); independent read-only tool calls as parallel lanes. FIRST: a per-provider concurrency budget. Also consider a dedicated post-turn phase — a slow reflection still holds the trailing SSE connection open after `done`. Owner-observed 2026-10-31: the reply completes on screen while the turn still reports Working (screenshot: 23.9s, Stop live) — the user-visible face of this note; attribution pass and contract decision live in B-2026-10-31-24. |
| B-2026-10-31-6 | Provider failover follow-ups (ADR-69): show cooldown/health per provider in the Providers page; per-provider concurrency budget; extend failed-source memory to `browse`/`web_research` and scope it per session; budget the fallback chain (a slower fallback can hit the per-call timeout). |
| B-2026-10-31-7 | Windows test portability + exit-gate reliability: raw Windows `tmp_path` backslashes injected into JSON tool args (`Invalid \escape` — the `find_path` cluster plus ~11 others, ~24 full-suite failures at exit); temp-dir/disallowed-path gates fail there; 5 source-grepping tests need `PYTHONUTF8=1` in the CI pytest step. THEN stabilise the nondeterministic families (failure set swings 7↔22) and refresh `scripts/pytest-baseline.txt` as a ratchet, not a mask. |
| B-2026-10-31-9 | Learning transfer: lessons persisted by the reflection loop must be RECALLED by relevance at decision time — a stable key-namespace in `vector_facts` plus recall on matching trigger patterns. Storage is not application. |
| B-2026-10-31-10 | Anti-sycophancy guard: agreement re-reasoned, never performed — concede only with evidence, defend when the user is wrong; prompt + Thinker contract, possibly a pre-concession check. Live-verify by replaying challenge turns. |
| B-2026-10-31-13 | Goal-rounds continuation beyond the open request: the driver queues `<goal_round>` rounds inside the chat SSE request, so a dropped connection or restart ends the deep dive while the goal stays `active`. Add a resume/idle path (queue the next round on reconnect or an idle tick, honouring the round cap, human-steer and ADR-67 gates) plus a resume affordance for a disarmed/blocked goal. |
| B-2026-10-31-14 | Turn economy for verification-heavy tasks: resumable per-phase checkpoints, adaptive time/tool budgets, background continuation, tool batching, and a graceful completed/stopped-at/what-continues report at the cap instead of dying mid-sentence. |
| B-2026-10-31-15 | Association-level grounding judge: the deterministic figure-presence check (`core/agent/evidence_grounding.py`) catches invented figures but not wrong-row attribution. Add a bounded read-only judge lane (same shape as the reply-is-pending judge) that verifies each measured figure's SUBJECT association against the turn's evidence; verdict drives one corrective nudge. Live-verify per `system/live-testing.md`. |
| B-2026-10-31-16 | Feedback-turn routing: a dissatisfaction-shaped follow-up ("you can't even archie your goal" after a bad turn) takes the clarification lane instead of surfacing the prior turn's evidence/tools and retrying the failed part. Fix the pre-init classifier / trivial-input lane decision; live-verify with a two-turn replay. |
| B-2026-10-31-18 | Finish the trajectory projection: `message.toolCalls` is still built live by `useLocalMind.ts` (friendly label + input preview) while reload uses `_collect_tool_calls` (raw args, so `input`/`duration` read undefined). Route the flat timeline through `turnProjection.projectTrajectory` and align `_collect_tool_calls` to the `_tool_call_dict` shape; extend the contract fixtures to cover the flat list. |
| B-2026-10-31-19 | Mode-gate the mixed-intent effecting tools: git (commit vs status), process (start/stop vs logs), browse (click/fill vs read) are effect-capable but not yet gated by file-effect mode — only the five unambiguous effecting intents are (`core/permission_mode.FILE_EFFECTING_INTENTS`). Add sub-command classification so `read_only` blocks their writes while allowing reads. |
| B-2026-10-31-22 | Reflective/identity turns must not reach for meta-tools (audit §1.2): "assess yourself" produced an elaborate plan and one irrelevant `get_goal` ({goal: null, activation: disarmed}) that contributed nothing, then answered anyway. Build the replay set of reflective/identity turns asserting which tools are acceptable (ideally none) and that a null meta-tool result is not leaned on; tighten dispatcher/answer-only guidance until the set is green. The task-type machinery exists (Intent/Capability, tool-schema withholding) — this verifies it on the failing class. Context: `office/reviews/2026-10-31-external-audit-intake.md` §1.2. |
| B-2026-10-31-23 | Standing eval harness (audit §1.7, its strongest structural ask): a scenario suite run against the live app per `system/live-testing.md` — ambiguous request, long conversation, preference recall, file analysis, dependent multi-step, failed tool, contradiction, user correction, unfamiliar problem, complex objective — scored on task completion, factual accuracy, tool success, recovery rate, unnecessary questions, latency. Absorbs B-2026-10-31-21/22 cases as they land; results feed re-prioritization of the whole backlog. Context: `office/reviews/2026-10-31-external-audit-intake.md` §1.7. |

### Low Priority

| ID | Summary |
|----|---------|
| B-2026-10-31-20 | LocalMind becomes a CONSUMER of the engine instead of its home: the engine lives in the public MIT repo `ti-matrix` (GitHub `TisoneK/ti-matrix`, local `~/Code/ti-matrix`). Pin it or vendor it and write LocalMind's own adapter on this side; the in-app State Explorer becomes the engine's Studio UI. `backend/src/state_agent/` stays a frozen prototype until the switch. GitHub-side steps need the owner (`gh` is unauthenticated). |

<!-- TEMPLATE — add one ACTIONABLE row to the matching priority table
     (a finding, question, or someday idea goes in parking-lot.md instead):
| B-<YYYY-MM-DD>-<n> | <what to DO, one line, pointing at the issue/PR/
      parking-lot finding for detail — not the full context> |
-->
