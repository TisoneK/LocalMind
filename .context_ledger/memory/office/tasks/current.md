# Current Task

**Status:** IDLE — **Session 467 (Asha / qwen3.8-flash, ZCode local, Windows)
COMPLETE (2026-09-11), in two bursts: context sync + core 1.0.0 adoption.**

**Burst 2 — core 1.0.0 (MAJOR, owner go-ahead):** `ledger-sync.cmd update
-Major` ran clean (rc=0): core replaced 0.22.0→1.0.0, the office migration
grouped the flat memory layout into `memory/office/` (durable files stayed at
the memory root; `agents/GROUP` retired; `group_size`→`office_size`; missing
office dirs backfilled). Three commits: core `fbe59fa2`, regroup `ddc9843b`
(owner's prescribed message), entry-point refresh `58690ba0` (AGENTS.md /
CLAUDE.md / kickoff.md regenerated from the new templates, facts refilled,
placeholder scan clean; `active.md` version line bumped). `ledger-sync
verify` OK on 1.0.0; `ledger-mem check` OK on the office paths.

**Carried finding:** the gate-teeth flaw (Windows `ledger-gates` prints
`GATE PASSED` + rc=0 after a configured command's `FAILED (1)` line when the
command writes to stdout) was RE-VERIFIED against 1.0.0 and is STILL OPEN —
the 1.0.0 rewrite applied the script-scoped-exit pattern only to
`Invoke-ChildScript` call sites, not to `Run-One`/`Run-ProjectCommands`.
**Until fixed upstream: read gate stdout for `FAILED (N)` lines; never trust
the exit code on Windows.**

**Next up:** B-2026-09-10-4 (date bombs — sole exit-gate red; its fix should
ride along with an upstream gate fix), B-2026-09-11-1 (usage → SSE `done`),
owner calls on thinking-exposure policy + B-2026-09-10-8 (`grep_search`
expose-or-retire), B-2026-09-10-5/6, OTT reruns, B-2026-09-11-2
(design-first), the legacy Session-double-entry WARNs (S405/S421/S431/S439/
S442 — owner call), and the first `ledger-history close` under the new
office lifecycle (office_size=20 will be crossed soon — the nudge is
warn-only).
