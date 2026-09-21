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
| B-2026-09-21-1 | EXIT GATE BLOCKED: `scripts/ci-check.sh`'s frontend leg fails on `eslint . --max-warnings 53` — the recent UI work added React-effect warnings ("Calling setState synchronously within an effect", missing hook deps) so the count exceeds the budget (0 errors). Fix the warnings (preferred) or consciously raise `--max-warnings`; do not let a red exit gate become normal. Surfaces: `frontend/src/hooks/useLocalMind.ts`, `hooks/useWorkspaceData.ts`, `hooks/use-mobile.ts`, `components/chat/` (ChatInput, ChatMessage, TurnView, FilePreviewDialog, WelcomeScreen), `components/ui/` (sidebar, toggle, navigation-menu, form). Exact command: `sh .context_ledger/core/bin/ledger-gates run exit`. |
| B-2026-09-21-2 | In-app State Explorer + engine selector (the state-driven engine, ADR-71 in `history/office-002/plans/decisions.md`): port the explorer into the app as its own interface (a game tree, move list, eval bar, inspector, meters, rewindable timeline — the owner's "geeky, not a chat" direction) and add the Classic/State engine setting so the engine becomes selectable in Settings. Reference implementations: the self-contained prototype `docs/prototypes/state-explorer/` and the backend-served page in `backend/src/api/static/state-explorer/`; engine package `backend/src/state_agent/` (adapter: `state_agent/adapters/localmind.py`); the `EngineEvent` record is the UI contract. In flight when office-002 closed — check whether it landed before starting. |
| B-2026-09-21-3 | State engine slice 2 (ADR-71): write-capable moves — mark tools `read_only=False`, PREDICT their outcome with the model (labelled `predicted`, never learned as a fact), execute only after the ADR-67 confirmation flag, then verify by a read-back probe; beam > 1; persist the state so a turn can resume; per-provider concurrency budget before widening parallel probes. Extends `backend/src/state_agent/` (the engine itself; the simulator is a `Simulator` implementation). |
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
| B-2026-09-21-13 | Skill-gap detection: diagnose repeated failure CATEGORIES and self-generate backlog rows (promotes lessons into named capability gaps). Shape to be settled at design time. |
| B-2026-09-21-14 | Anti-sycophancy guard: agreement re-reasoned, never performed — concede only with evidence, defend when the user is wrong; prompt + Thinker contract, possibly a pre-concession check. Live-verify by replaying challenge turns. |
| B-2026-09-21-15 | Memory edit path tolerance: `PATCH /api/memory/{id}` (behind `VectorStore.update_content`) needs the embedding index, so an edit against a store built by the plain-text fallback rolls back and answers 404. Mirror the delete half's best-effort behaviour, or refuse with the reason instead of "not found". |
| B-2026-09-21-16 | "Conversation too long" false positive: the raw provider error behind a ~3K-token chat on a 1M-token model was never captured. Reproduce on the owner's setup with the failure card's Technical details open, log the raw error server-side, find why the card said `Provider: unknown`, and add the missing provider label. |
| B-2026-09-21-17 | Turn economy for verification-heavy tasks: resumable per-phase checkpoints, adaptive time/tool budgets, background continuation, tool batching, and a graceful completed/stopped-at/what-continues report at the cap instead of dying mid-sentence. |

### Low Priority

| ID | Summary |
|----|---------|
| B-2026-09-21-18 | Memory junk-row sweep: find rows whose whole content is an operation word (`list`, `store`, `recall`, `forget`, `facts`, `memory`) written by the bare-operation bug, report them, delete only on approval; `scripts/janitor.py` is the natural home. |
| B-2026-09-21-19 | Ledger-vocabulary strip remainder: ~540 citation lines left in `tests/` (~384), `docs/` (~95) and live-test script headers (~50) — the runtime surface is already clean. Method and exact state: `history/office-002/reviews/2026-09-16-review-s5-vocab-strip.md`; hand-strip per line, never a blind script. |
| B-2026-09-21-20 | Two dead-code decisions with evidence already gathered: `core/filters.py`'s `is_code_output` flag is never read in `_filter_tool_injection`'s body, so code output gets the same filtering as everything else despite the docstring (implement the skip or remove the flag); `api/routes/terminal.py`'s `TerminalSessionBridge` is fully built but never called — wire `execute_in_session` into the agent's tool dispatch or remove the class. Detail: `history/office-002/reviews/2026-09-19-review-s021-dead-code-scan.md`. |
| B-2026-09-21-21 | Settings/architecture tidy: give memory settings (embedding model) their own page; extract `useChat`'s ~1,900-line SSE switch into a reducer with per-event handlers; find the ~1s gap between the finished-turn header time and the measured latency. |
| B-2026-09-21-22 | Persist per-phase thinking segments so reloaded chats keep the split — store `{text, ms, afterTools}` in message metadata next to `thinking` (only live turns are split today). |
| B-2026-09-21-23 | Frontend test health: 9 context-menu tests fail under jsdom (the Radix menu opens once per file); cause already narrowed — fix or document with the cause. |
| B-2026-09-21-24 | Provider model-switch policy: provider model switches only affect the picker — decide whether hidden models must also be refused by the agent/router, and live-test the add/hide/default/delete flows on a real provider (only the DeepSeek view was clicked through). |

<!-- TEMPLATE — add one ACTIONABLE row to the matching priority table
     (a finding, question, or someday idea goes in parking-lot.md instead):
| B-<YYYY-MM-DD>-<n> | <what to DO, one line, pointing at the issue/PR/
      parking-lot finding for detail — not the full context> |
-->
