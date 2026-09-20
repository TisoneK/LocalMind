# Backlog (live queue — open work only)

Open items for future sessions, **arranged by priority so the shape of
the work is visible the moment the file opens**: one row per item, in
its priority table. When an item is finished, **delete its row** — the
backlog holds only open work, never completed rows. The completion
record is the finishing session's `agents/sessions.md` entry and the
commit itself; git history keeps every removed row, so deleting loses
nothing. Never delete a row whose item is still open — a row vanishing
from the diff without a matching session entry is a dropped handoff,
not cleanup. (Legacy checkbox-format backlogs: `ledger-mem closeout`
sweeps checked-off `- [x]` tombstones a session left behind — dry run
by default; `--confirm` deletes.)

Every row gets a stable **ID** — `B-<added YYYY-MM-DD>-<n>`, n = that
date's next sequence in the file — and a **Summary** cell with enough
context that a fresh agent can act on the item without any chat
history; keep status qualifiers in the summary text ("partial",
"done, pending sign-off", "deferred by owner", "advisory"). Priority
is the table an item sits in — when unsure, Medium.

This backlog belongs to the **current office**. When the office closes,
open items do not carry over implicitly — the closing session re-seeds
into the new office's backlog only what still matters, and records the
rest in the permanent record (`history/office-<NNN>.md`, "Open threads").

Full spec: `.context_ledger/core/schemas/ledger-schema.md` →
"The backlog: arrangement + workstream view".

Provenance: re-rowed in place on 2026-09-12 by the session that closed
office-001, per core 1.0.5 (this office's Session 1; the same session's
pre-close record is frozen at `history/office-001/agents/sessions.md`) —
existing B-IDs kept; the three legacy items that never had IDs got
`B-2026-07-11-1`, `B-2026-07-11-2`, and `B-2026-08-31-1` (their dates' next
sequences in the file). Finished rows deleted during the re-row are
enumerated in that session's entry; the pre-re-row file remains in git
history and in the closed office's frozen copy
(`history/office-001/tasks/backlog.md`). Re-seeded into this office's
backlog IN FULL at the close — owner directive 2026-09-12 ("keep the
backlog copy to the new office"); the next office is free to prune rows
whose items no longer matter, but nothing was culled at the re-seed.
Note on references: Summary cells cite sessions by their office-001
numbers — those records live in `history/office-001/agents/sessions.md`;
this office's own records start at Session 1.

Re-triaged 2026-09-16 by Chemi (S013) per the supervisor's directive:
84 rows → the 20 actionable rows below + 59 knowledge/deferred/advisory
rows moved to `tasks/parking-lot.md` as `P-2026-09-16-1`…`P-2026-09-16-59`
(each tagged with its former `B-` ID; `B-2026-08-25-2` +
`B-2026-08-25-10` merged into one row, `P-2026-09-16-26`). 5 rows
deleted as done/stale: `B-2026-08-24-13`, `B-2026-08-24-14`,
`B-2026-08-25-6` (shipped — commits `1b15c2f`, `6cc1aa7`, `3072074`;
session entries on file); `B-2026-08-24-8` (a standing practice, not a
task — codified in `workflows/active.md`'s verification bar);
`B-2026-08-30-8` (the over-thinker half shipped `bd0641d`; the remaining
detector gap — "remember <url>" lead-ins defeating the start-anchored
write cues — is noted here rather than parked as a row). The full
pre-triage text of every row (kept, moved, and deleted) remains in this
file's git history.

## Open Items

### High Priority

| ID | Summary |
|----|---------|

### Medium Priority

| ID | Summary |
|----|---------|
| B-2026-09-19-6 | Stage-aware, compact strict structured model input (feature `stage-prompts`) — RESUMED 2026-09-20 on DeepSeek (Imani/S024). SHIPPED `6155cb7c` (stale delegation text etc.; A/B 30/30 vs 28/30). Remaining levers + why each was held back: see manifest 'Decision + what shipped'. ROUND 2 (rule-preserving compression, 135 runs): NO quality loss (A 45/45, C 43/45, D 44/45); compact schemas (D) cut input 8-17% (p<=0.056); system prompt + schemas are 83% of all input (re-sent every act call). Remaining before shipping D: ADR-40 second-model check (Cerebras out of quota, 402) then productize prompts.py/tool_schemas.py edits. ROUND 1: FIRST ROUND: the trimmed compact prompt FAILS multi-part lookups (0/15 vs 13/15, p<0.001 — it narrates and stops; it dropped the load-bearing multi-part/act-not-announce rule) and is neutral on a write task (24% fewer input chars with compact schemas). Compaction must preserve every rule; rebuild and re-test (see manifest 'Next (revised)'). Byproduct fixed `28c7eaae`: older tool results were cut mid-list, final answers 5/15 -> 14/15. Original note: Idea: the full system prompt only on the cold-start act call; every later stage (continue / recover / answer) gets a small structured card (Stage, Goal, Done so far, one positive Decision, only the tools that decision needs). Groundwork shipped (stage cards `6899023a`; input-quality fixes; adapter empty-response root cause `d61d1d12`). Measured on glm-4.5-flash: system prompt -60%, tool schemas -31%, prompt tokens -32% to -39% per run, NO detectable quality change at n=4/5/5 — quality benefit UNPROVEN and not built (variants were emulated in a harness). Resume: rerun `features/stage-prompts/harness/` with N>=10 per variant on a non-throttled provider, clean finals only, more than one task shape; then build a stage-aware assembler behind a setting and live-verify tool selection (ADR-40) on two models. Constraints: ADR-41, ADR-46, ADR-53, ADR-61, ADR-64 (no silent prompt swaps). See `features/stage-prompts/manifest.md` + `office/reviews/2026-09-19-review-s024-decision-core-survey.md`. (filed by Imani/S024, 2026-09-19) |
| B-2026-09-19-5 | PARTIAL (Imani/S024, `2a5b3877`): the hang half is DONE and live-verified — fact extraction + reflection now share `POST_TURN_LLM_BUDGET_S` (90 s, env `LOCALMIND_POST_TURN_BUDGET_S`), an exhausted service is cut off and reported as a `post_turn_timeout` obs event (injected hang: done at exactly the budget after the answer; normal run unchanged). NOT done, deliberately: delivering `done` BEFORE reflection — reflection emits the ADR-64 visible lesson events on the same stream and `done` order is the ADR-34 guardrail, so that needs an owner call (e.g. a dedicated post-turn SSE phase). Original finding: a post-answer LLM call (reflection or title refinement) can hang the turn for minutes: live glm-4.5-flash trace F1r1 — loop and final synthesis done at 12:21:11, then a z.ai request opened at 12:21:21 never returned until the server was killed at 12:30:25 (663 s total), and `done` waits on reflection (`agent_runtime.py` ~2121; measured 3.3 s on gemini, 31 s on glm even when healthy). Give post-answer calls a hard timeout and move reflection/title off the critical path (deliver `done` first, surface the lesson afterwards, ADR-64 visibility intact). Live-verify with the S024 trace harness (capture per-call timings). (found by Imani/S024, 2026-09-19) |
| B-2026-09-15-6 | Pre-action recall: inject recalled stable facts into the turn context before answering fact questions (identity/location/preferences) — reads are ~16ms; ADR-62 gap 4. Live-verify. |
| B-2026-09-15-9 | Consequence-tiered verification ladder for destructive/mutating requests: resolve-target → verify state → assess risk → CONFIRM → execute → verify → reflect; low-risk reads skip ceremony. Owner principles: "No action without verification. No destructive action without confirmation." Extends B-2026-08-25-12. |
| B-2026-09-15-7 | Turn economy for verification-heavy tasks: resumable per-phase checkpoints, adaptive time/tool budgets, background continuation, tool batching, graceful completed/stopped-at/what-continues report at cap (not dying mid-sentence). Research doc §2 Arc E. |
| B-2026-09-09-7 | Stabilise the tests/tools + acceptance-gate nondeterminism (failure set 7↔22 per run, blocks a reliable exit gate): make `verify.py:195` honor cwd injection (it stats repo-root `hello.py` residue today), hunt the cross-file state leak, THEN refresh `scripts/pytest-baseline.txt`. |
| B-2026-09-15-19 | One-line CI fix: export `PYTHONUTF8=1` on the pytest step in `scripts/ci-check.sh` (~line 79) — five source-grepping tests UnicodeDecodeError on cp1252 Windows boxes otherwise (exit gate fails for environmental reasons). |
| B-2026-09-19-1 | tests/tools Windows portability: raw Windows `tmp_path` backslashes are f-string-injected into JSON tool args (`Invalid \escape` on every such test) and temp-dir/disallowed-path gates fail on this box — the 13-test `test_find_path.py` cluster plus 11 others reproduce at every revision (24 full-suite failures at exit, S018 provenance-checked node-for-node against `d9751086`); blocks a clean exit gate alongside `B-2026-09-09-7`. |
| B-2026-08-17-9 | OUTPUT tokens (partial): cut `FILE_READ_MAX_BYTES` 512KB → ~16-32KB for loop injection, add ONE per-tool cap at the `loop.py` ~2580 choke point, truncate re-injected cached obs on dedup hits. ADR-43 L4. |
| B-2026-09-19-2 | `core/filters.py:138` `_filter_tool_injection`'s `is_code_output` flag is never read in the function body — `_filter_code_output()` (what `loop.py` actually calls for code-exec stdout/stderr) passes `is_code_output=True` for nothing, so code output gets the exact same filtering as everything else despite the docstring's claim it should skip code-pattern filters. Either implement the skip logic or remove the flag. Full detail: `reviews/2026-09-19-review-s021-dead-code-scan.md`. |
| B-2026-09-19-3 | `api/routes/terminal.py:78` `TerminalSessionBridge` (bridges agent shell/code_exec calls into terminal sessions so CWD/history/tool-log are shared) is fully built but never called from anywhere — decide whether to wire `execute_in_session` into the agent loop's tool-dispatch path or remove the class. Full detail: `reviews/2026-09-19-review-s021-dead-code-scan.md`. |
| B-2026-09-19-4 | `_tilde_display` (`core/context_builder.py`, shipped S023 / `8b892284`) joins the `~`-relative remainder with `os.sep`, so on Windows it renders `~\Dev\LocalMind`; its test `test_context_builder.py::test_tilde_display_normalizes_home_and_nested_paths` hardcodes the Unix `~/Dev/LocalMind` and fails on this box (1 of the 6 un-baselined full-suite failures at exit, alongside `B-2026-09-15-19`'s five). Decide the intended display separator (forward-slash for a stable prompt string vs. native) and make the function + test agree cross-platform. Found by S025; pre-existing on `origin/main`, not a regression. |

### Low Priority

| ID | Summary |
|----|---------|
| B-2026-09-15-1 | Ledger-vocabulary strip remainder (in progress — Baraka S005 released the claim 2026-09-16; runtime surface done): ~540 lines left in tests/, docs/, live-test script headers; method + state in `reviews/2026-09-16-review-s5-vocab-strip.md`. |
| B-2026-09-15-17 | Multi-step planning WIRING: route genuinely-complex requests through plan → execute → reflect at the tier-3 triage (planner/todo_write/checklist machinery exists; the gap is routing). Ties -7 (per-phase budgets = checkpoint structure). |
| B-2026-09-15-18 | Learning transfer: lessons persisted by -14 must be RECALLED by relevance at decision time — stable key-namespace in vector_facts + -6 recall on matching trigger patterns. Storage ≠ application. |
| B-2026-09-15-16 | Skill-gap detection: diagnose repeated failure CATEGORIES and self-generate backlog rows (promotes -14's lessons into named capability gaps). Shape TBD at design time. Research doc §6.3. |
| B-2026-09-15-10 | Anti-sycophancy guard: agreement re-reasoned, never performed — concede only with evidence, defend when the user is wrong; prompt + Thinker contract, possibly a pre-concession check. Live-verify by replaying challenge turns. |
| B-2026-09-07-1 | Fast-path/conversational turns persist no workspace artifacts → Agent Workspace panel empty after reload. Either build minimal turn-shell artifacts on the fast-path epilog (`agent_runtime.py` ~1300) or render a "direct-answer turn" card frontend-only. Coordinate: shared surface with metrics work. |
| B-2026-09-09-9 | Isolated server dies SILENTLY under provider 429 storms (no traceback, client sees "connection refused"): add a last-gasp crash surface (faulthandler wrapper), repro under a MOCKED 429 storm + client-abort, define the SSE contract for process death. Evidence: `scratch/server-death-evidence-s449.log`. |
