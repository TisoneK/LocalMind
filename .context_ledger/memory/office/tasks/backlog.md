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
| B-2026-09-21-2 | In-app State Explorer + engine selector (the state-driven engine, ADR-71 in `history/office-002/plans/decisions.md`): port the explorer into the app as its own interface (a game tree, move list, eval bar, inspector, meters, rewindable timeline — the owner's "geeky, not a chat" direction) and add the Classic/State engine setting so the engine becomes selectable in Settings. Reference implementations: the self-contained prototype `docs/prototypes/state-explorer/` and the backend-served page in `backend/src/api/static/state-explorer/`; engine package `backend/src/state_agent/` (adapter: `state_agent/adapters/localmind.py`); the `EngineEvent` record is the UI contract. In flight when office-002 closed — check whether it landed before starting. |
| B-2026-09-21-3 | State engine slice 2 (ADR-71, partly done — the Simulator ships: an action that must not be performed is predicted, labelled, never a fact, never settling, and a run that needs one stops `needs_action`): NEXT here is EXECUTING a confirmed action behind the ADR-67 flag and verifying it by a read-back probe, a SECOND `Environment` adapter as the proof the engine's boundary holds (a CLI or filesystem env with its own CLI), beam > 1, and persisted state so a turn can resume. Original text: engine slice 2: write-capable moves — mark tools `read_only=False`, PREDICT their outcome with the model (labelled `predicted`, never learned as a fact), execute only after the ADR-67 confirmation flag, then verify by a read-back probe; beam > 1; persist the state so a turn can resume; per-provider concurrency budget before widening parallel probes. Extends `backend/src/state_agent/` (the engine itself; the simulator is a `Simulator` implementation). |
| B-2026-09-21-4 | Benchmark the state engine against Classic (ADR-71 §8): both engines selectable and observable, same tasks, measurable comparison, only then a decision about an `Auto` engine. Ties to B-2026-09-21-2. |
| B-2026-09-21-5 | Confirmable-refusal rollout (ADR-67): convert every tool that refuses or guesses to "refuse only on a verified fact, name the fact and the confirming flag" — start with delete (`confirm_delete`), the shell tool's destructive/mass-touch commands (replace the substring blocklist), and installs (`scope=system`); record confirming flags in the run trace. Composes with the consequence-tiered ladder work (resolve → verify → assess → confirm → execute → verify → reflect). |

### Medium Priority

| ID | Summary |
|----|---------|
| B-2026-09-21-6 | Turn-bus follow-ons (ADR-66b): post-turn services (reflection, fact extraction, title) as lanes behind `gate()` with the existing post-turn budget; silent READ-ONLY grounding `system_tool` lanes (path state before a write, read-back verify, git state) whose verdicts gate irreversible steps; a Decider lane (safety classification replacing the shell substring blocklist, tier/routing verdicts); independent read-only tool calls as parallel lanes. FIRST: a per-provider concurrency budget (a provider rejected 3 parallel workers). Related: a very slow reflection still holds the trailing SSE connection open after `done` — consider a dedicated post-turn phase. |
| B-2026-09-21-7 | Provider failover follow-ups (ADR-69): show cooldown/health per provider in the Providers page; a per-provider concurrency budget; extend the failed-source memory to `browse`/`web_research` and scope it per session; budget the fallback chain (a slower fallback model can hit the per-call timeout). |
| B-2026-09-21-8 | Windows test portability + exit-gate reliability: raw Windows `tmp_path` backslashes are f-string-injected into JSON tool args (`Invalid \escape` — the 13-test `find_path` cluster plus ~11 others, ~24 full-suite failures at exit); temp-dir/disallowed-path gates fail on that box; and 5 source-grepping tests need `PYTHONUTF8=1` on the CI pytest step (~line 79 of `scripts/ci-check.sh`). THEN stabilise the nondeterministic families (failure set swings 7↔22) and refresh `scripts/pytest-baseline.txt` — it is a ratchet, not a mask. |
| B-2026-09-21-9 | Windows verification of the state engine: the State Explorer page and the live SSE run route (`GET /state-explorer`, `POST /api/state-engine/run`) were verified on macOS only. Run them on the owner's Windows box (build-free by design) and fix whatever the platform surfaces. |
| B-2026-09-21-10 | Pre-action recall (ADR-62 gap 4): inject recalled stable facts into the turn context BEFORE answering identity/location/preference questions — reads are ~16ms. The passive-context profile (ADR-66a) is the source. Live-verify. |
| B-2026-09-21-11 | Multi-step planning wiring: route genuinely-complex requests through plan → execute → reflect at the tier-3 triage — the planner/`todo_write`/checklist machinery exists; the gap is routing. Ties to per-phase budgets (B-2026-09-21-17). |
| B-2026-09-21-12 | Learning transfer: lessons persisted by the reflection loop must be RECALLED by relevance at decision time — a stable key-namespace in `vector_facts` plus recall on matching trigger patterns. Storage is not application. |
| B-2026-09-21-14 | Anti-sycophancy guard: agreement re-reasoned, never performed — concede only with evidence, defend when the user is wrong; prompt + Thinker contract, possibly a pre-concession check. Live-verify by replaying challenge turns. |
| B-2026-09-21-15 | Memory edit path tolerance: `PATCH /api/memory/{id}` (behind `VectorStore.update_content`) needs the embedding index, so an edit against a store built by the plain-text fallback rolls back and answers 404. Mirror the delete half's best-effort behaviour, or refuse with the reason instead of "not found". |
| B-2026-09-21-16 | "Conversation too long" false positive: the raw provider error behind a ~3K-token chat on a 1M-token model was never captured. Reproduce on the owner's setup with the failure card's Technical details open, log the raw error server-side, find why the card said `Provider: unknown`, and add the missing provider label. |
| B-2026-10-26-3 | Goal-rounds follow-up — continuation beyond the open request: the driver currently queues `<goal_round>` rounds *inside* the chat SSE request, so a dropped connection or an app restart ends the deep dive while the goal stays `active` (process-local activation also dies with the server process). Add a resume/idle path: for an active+armed goal with no turn running, queue the next round on reconnect or on a server-side idle tick, honouring the same round cap, human-steer and ADR-67 gates; plus a resume affordance in the composer meter for a disarmed/blocked goal. |
| B-2026-09-21-17 | Turn economy for verification-heavy tasks: resumable per-phase checkpoints, adaptive time/tool budgets, background continuation, tool batching, and a graceful completed/stopped-at/what-continues report at the cap instead of dying mid-sentence. |
| B-2026-10-27-1 | Association-level grounding judge: the deterministic figure-presence check (`core/agent/evidence_grounding.py`, wired into the acceptance gate) catches invented figures but not wrong-row attribution — "Kitengela 26/17" assembled from Nairobi's row passes. Add a bounded read-only judge lane (same shape as the reply-is-pending judge on the turn bus) for answers asserting several measured figures: verify each figure's SUBJECT association against the turn's evidence, verdict drives one corrective nudge. Live-verify per `system/live-testing.md`. Context: `office/reviews/2026-10-27-review-s6-evidence-grounding.md`. |
| B-2026-10-27-2 | Feedback-turn routing: a complaint about the previous answer ("you can't even archie your goal" after a bad weather turn) takes the clarification lane and asks what the user means. A dissatisfaction-shaped follow-up — typo-tolerant, "archie" ≈ "achieve" — should surface the prior turn's evidence and tools, retry the failed part or answer with what the evidence actually supported. Root surface: the pre-init classifier / trivial_input lane decision. Live-verify with a two-turn replay. |

### Low Priority

| ID | Summary |
|----|---------|
| B-2026-10-26-2 | Harness shell parity (optional): the Harness app's information architecture — brand rail + nav + workspaces, the `Chat / Trajectory` tab strip, right-side `Start` cards. Deliberately deferred in the 2026-10-26 skin slice, which changed surfaces and tokens only. Reference: `office/reviews/2026-10-26-review-s2-harness-skin.md`. |
| B-2026-09-21-21 | Settings/architecture tidy: give memory settings (embedding model) their own page; extract `useChat`'s ~1,900-line SSE switch into a reducer with per-event handlers; find the ~1s gap between the finished-turn header time and the measured latency. |
| B-2026-09-21-25 | LocalMind becomes a CONSUMER of the engine instead of its home. The engine now lives in its own PUBLIC MIT repository `ti-matrix` (GitHub `TisoneK/ti-matrix`, local `~/Code/ti-matrix`, import package `ti_matrix`, distribution `ti-matrix`, no runtime dependencies, 34 tests): pin it as a dependency or vendor it, and **write LocalMind's own engine adapter on this side** — the engine repo deliberately ships no host integration any more. The in-app State Explorer becomes the engine's Studio UI. This repo's `backend/src/state_agent/` copy is a FROZEN prototype (no further engine work there; the API route and the Explorer keep working against it until the switch). Remaining remote-side step: creating/editing anything on GitHub needs the owner — `gh` is installed user-locally but unauthenticated. |

<!-- TEMPLATE — add one ACTIONABLE row to the matching priority table
     (a finding, question, or someday idea goes in parking-lot.md instead):
| B-<YYYY-MM-DD>-<n> | <what to DO, one line, pointing at the issue/PR/
      parking-lot finding for detail — not the full context> |
-->
