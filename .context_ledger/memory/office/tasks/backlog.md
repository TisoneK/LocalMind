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
| B-2026-11-03-1 | The zero-tool forced-replan storm (found live by S025's markdown harness): an analyze-intent turn WITH a drawn plan whose model persistently answers in prose (no tool call) triggers the gate's zero-tool force EVERY iteration — the probe measured 20 forced-provider calls (each carrying the full system prompt) before the honest stop, for one knowledge-comparison question a fake could only answer in text. A real model usually calls a tool or the turn classifies chat, so the storm is rare — but on the owner's pay-per-token key the cost is real. Design a bound: a distinct cap for consecutive zero-tool forces (distinct from `effective_max_iter`), or a classify re-check after the first force (is this turn actually a task?), or an honest-stop after N forces that names the mismatch on the record. Reproduce first with `scripts/live_test_markdown_render.py` probe B pre-fix shape (plan row + zero-tool fake). |
| B-2026-11-02-2 | Adaptive plan revision & objective fidelity (owner 2026-11-02 advisor exchange — follow-on to B-2026-11-02-1): the todo list must EVOLVE when execution evidence changes the work — a discovery that moots a todo retires it (explicit `retired` status carrying the discovery in its result) instead of silently vanishing in a full-replace; mid-turn rewrites surface as a revision diff (`todo_revised`: added/retired/kept) in the Todos panel; and the close gains an objective-fidelity judge (bounded read-only lane, completion-judge shape): does the reply address the ORIGINAL request, not merely the todos — one drift nudge, on the record, never blocks. The benchmark: the agent "knows where it is coming from and where it is going". SHIPPED 2026-11-02 (S023): the gate's replan diffs into the live todo list (`retired` status carrying the discovery, appended rows, `todo_revised {added, retired, kept}` once per turn, closed rows never churn, the finalize sweep leaves retired closed) and the objective-fidelity judge runs at the close (bounded read-only lane, `post_answer_lanes.objective_fidelity` + `objective_drift`, one nudge, never blocks). SHIPPED 2026-11-03 (S024) — the REMAINDER closed: a mid-turn `todo_write` call now DIFFS against the live panel rows (the model's own last-written list, else the planner rows, else the syn- fallbacks) instead of silently full-replacing — dropped open rows retire with the reason, new work appends with fresh ids, closed rows never churn, `todo_revised` lands once per actual rewrite, a retired row takes no more tool lifecycle — and revised steps carry outcomes: model-supplied `expected_outcome` joins the acceptance contract, the gate's replan prompt asks for per-step done-when contracts and the parser carries them into the added rows (backward-compatible), and `todo_write` is excluded from the gate's evidence (a checklist cannot verify itself). ITEM CLOSED. |

### Medium Priority

| ID | Summary |
|----|---------|
| B-2026-10-31-5 | Turn-bus follow-ons (ADR-66b): post-turn services as lanes behind `gate()` with the post-turn budget; silent read-only grounding lanes whose verdicts gate irreversible steps; a Decider lane (safety classification replacing the shell blocklist); independent read-only tool calls as parallel lanes. FIRST: a per-provider concurrency budget. Owner-observed 2026-10-31: the reply completes on screen while the turn still reports Working (screenshot: 23.9s, Stop live) — the user-visible face of this note. SHIPPED 2026-10-31: per-stage attribution (turn_stages + post_answer_lanes on the wire, in metrics and persisted) and the honest completion contract (response_ready event; "Answer ready · finishing up" strip/turn-view; Stop disabled once the reply is final). RESOLVED 2026-11-02 (e893aced): the dedicated post-turn phase question — the bounded services (fact extraction + reflection, the 90s class) run DETACHED from the transport (`_spawn_post_turn_services`; `drain_post_turn_services` is the drain seam); the acceptance gate + judge stay pre-done BY DESIGN (the withhold contract decides what the answer is) and are now bounded (~judge 5s thinking-off). What remains here is the lane expansion itself (Decider, parallel read-only lanes, per-provider concurrency budget). |
| B-2026-10-31-6 | Provider failover follow-ups (ADR-69): show cooldown/health per provider in the Providers page; per-provider concurrency budget; extend failed-source memory to `browse`/`web_research` and scope it per session. NOTE 2026-11-02 (e893aced): deterministic provider management shipped — the implicit "any keyed provider" tail is retired (explicit `fallback_to` only, destination's own model), the switch records {from, code, to}, and the turn's persisted identity stamps report the actual server; the old "budget the fallback chain" item is moot under the explicit-only chain (a chain is at most one explicit hop). |
| B-2026-10-31-9 | Learning transfer: lessons persisted by the reflection loop must be RECALLED by relevance at decision time — a stable key-namespace in `vector_facts` plus recall on matching trigger patterns. Storage is not application. |
| B-2026-10-31-10 | Anti-sycophancy guard: agreement re-reasoned, never performed — concede only with evidence, defend when the user is wrong; prompt + Thinker contract, possibly a pre-concession check. Live-verify by replaying challenge turns. |
| B-2026-10-31-14 | Turn economy for verification-heavy tasks: resumable per-phase checkpoints, adaptive time/tool budgets, background continuation, tool batching, and a graceful completed/stopped-at/what-continues report at the cap instead of dying mid-sentence. |
| B-2026-10-31-15 | Association-level grounding judge: the deterministic figure-presence check (`core/agent/evidence_grounding.py`) catches invented figures but not wrong-row attribution. Add a bounded read-only judge lane (same shape as the reply-is-pending judge) that verifies each measured figure's SUBJECT association against the turn's evidence; verdict drives one corrective nudge. Live-verify per `system/live-testing.md`. |
| B-2026-10-31-16 | Feedback-turn routing: a dissatisfaction-shaped follow-up ("you can't even archie your goal" after a bad turn) takes the clarification lane instead of surfacing the prior turn's evidence/tools and retrying the failed part. Fix the pre-init classifier / trivial-input lane decision; live-verify with a two-turn replay. |
| B-2026-10-31-18 | Finish the trajectory projection: `message.toolCalls` is still built live by `useLocalMind.ts` (friendly label + input preview) while reload uses `_collect_tool_calls` (raw args, so `input`/`duration` read undefined). Route the flat timeline through `turnProjection.projectTrajectory` and align `_collect_tool_calls` to the `_tool_call_dict` shape; extend the contract fixtures to cover the flat list. |
| B-2026-10-31-19 | Mode-gate the mixed-intent effecting tools: git (commit vs status), process (start/stop vs logs), browse (click/fill vs read) are effect-capable but not yet gated by file-effect mode — only the five unambiguous effecting intents are (`core/permission_mode.FILE_EFFECTING_INTENTS`). Add sub-command classification so `read_only` blocks their writes while allowing reads. |
| B-2026-10-31-22 | Reflective/identity turns must not reach for meta-tools (audit §1.2): "assess yourself" produced an elaborate plan and one irrelevant `get_goal` ({goal: null, activation: disarmed}) that contributed nothing, then answered anyway. Build the replay set of reflective/identity turns asserting which tools are acceptable (ideally none) and that a null meta-tool result is not leaned on; tighten dispatcher/answer-only guidance until the set is green. The task-type machinery exists (Intent/Capability, tool-schema withholding) — this verifies it on the failing class. Context: `office/reviews/2026-10-31-external-audit-intake.md` §1.2. |

### Low Priority

| ID | Summary |
|----|---------|
| B-2026-10-31-20 | LocalMind becomes a CONSUMER of the engine instead of its home: the engine lives in the public MIT repo `ti-matrix` (GitHub `TisoneK/ti-matrix`, local `~/Code/ti-matrix`). Pin it or vendor it and write LocalMind's own adapter on this side; the in-app State Explorer becomes the engine's Studio UI. `backend/src/state_agent/` stays a frozen prototype until the switch. GitHub-side steps need the owner (`gh` is unauthenticated). |

<!-- TEMPLATE — add one ACTIONABLE row to the matching priority table
     (a finding, question, or someday idea goes in parking-lot.md instead):
| B-<YYYY-MM-DD>-<n> | <what to DO, one line, pointing at the issue/PR/
      parking-lot finding for detail — not the full context> |
-->
