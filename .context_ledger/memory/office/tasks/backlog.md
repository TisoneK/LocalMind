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
| B-2026-09-15-3 | Typed memory schema enforced in the WRITE PATH (not prose): PREFERENCE / STABLE_FACT (freshness+confidence tags, boot-refresh) / VOLATILE (never persisted). Gates B-2026-09-15-2/-4c/-14/-15. Files: `backend/src/tools/memory_tool.py`, `backend/src/storage/vector.py`. ADR-62. |
| B-2026-09-15-4 | Memory-tool reliability, implementation order: (1) read-back-after-mutation gate, (2) keyed upsert + volatile stripping on write, (3) forget_by_id + parseable list output (store returns ids). Live-verify per the standing bar. Files: `tools/memory_tool.py`, `storage/vector.py`. |
| B-2026-09-15-13 | Deduction engine: fuse signals already in hand (locale, timezone, ISP, files, prior turns) into ONE conclusion and act — no hedged candidate lists, no waiting to be asked. ADR-62 build order 1-2; research doc `plans/2026-09-15-self-improvement-transcript-research.md` §2 Arc A. |
| B-2026-09-15-14 | Self-reflection loop: post-turn automatic "what did I miss" assessment stored as atomic lessons — capture PATTERNs behind failures, not just instances; batch the ~6.4s embed writes; respects -3/-4 mechanics. Research doc §6.1. |
| B-2026-08-15-12 | Three-tier classification (trivial / needs-thought / needs-tools; only tier 3 boots the workspace): prompt-tune tier-2 → `direct`, make direct-mode reasoning proportionate, regression-test that tiers 1+2 emit zero workspace/loop events. Owner independently diagnosed the uniform ~40s turn. Files: `core/agent/initialization.py`, `loop.py`. |

### Medium Priority

| ID | Summary |
|----|---------|
| B-2026-09-15-15 | Passive context awareness: build the user/environment profile from incidental interaction signals without an explicit "remember this" trigger; the profile is -13's reasoning input. Constraints: -3 policy, -4 mechanics. Research doc §6.2. |
| B-2026-09-15-6 | Pre-action recall: inject recalled stable facts into the turn context before answering fact questions (identity/location/preferences) — reads are ~16ms; ADR-62 gap 4. Live-verify. |
| B-2026-09-15-8 | Intent-aware "criteria unmet" replan: suppress the zero-tool-commitment gate on conversational tiers, escalate on approval tokens ("Go ahead"); live-verify both directions. `loop.py` ~7385. |
| B-2026-09-15-9 | Consequence-tiered verification ladder for destructive/mutating requests: resolve-target → verify state → assess risk → CONFIRM → execute → verify → reflect; low-risk reads skip ceremony. Owner principles: "No action without verification. No destructive action without confirmation." Extends B-2026-08-25-12. |
| B-2026-09-15-7 | Turn economy for verification-heavy tasks: resumable per-phase checkpoints, adaptive time/tool budgets, background continuation, tool batching, graceful completed/stopped-at/what-continues report at cap (not dying mid-sentence). Research doc §2 Arc E. |
| B-2026-09-09-7 | Stabilise the tests/tools + acceptance-gate nondeterminism (failure set 7↔22 per run, blocks a reliable exit gate): make `verify.py:195` honor cwd injection (it stats repo-root `hello.py` residue today), hunt the cross-file state leak, THEN refresh `scripts/pytest-baseline.txt`. |
| B-2026-09-15-19 | One-line CI fix: export `PYTHONUTF8=1` on the pytest step in `scripts/ci-check.sh` (~line 79) — five source-grepping tests UnicodeDecodeError on cp1252 Windows boxes otherwise (exit gate fails for environmental reasons). |
| B-2026-08-17-9 | OUTPUT tokens (partial): cut `FILE_READ_MAX_BYTES` 512KB → ~16-32KB for loop injection, add ONE per-tool cap at the `loop.py` ~2580 choke point, truncate re-injected cached obs on dedup hits. ADR-43 L4. |

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
