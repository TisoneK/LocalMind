# Current Task

**Status:** DESIGN FINALIZED — **Session 459 (Amara / glm-5.3-flash, ZCode
local, Windows).** Owner decisions applied; implementation session is next.

Owner directive: "design Explorer tool for LocalMind." Design doc at
`docs/explorer_tool_design.md`: ONE bounded read-only tool = {list, tree,
stat} for the Parent, mirroring the `system_search` front-door pattern; NOT a
find tool (`system_search`) or file reader (`file_task`); reuses `find_path`
walk machinery; security via `settings.is_path_allowed`; names+metadata only
(never bytes → no secret leak); UX = existing `ToolSteps`/`action_label`/
`RiskLevel` mechanisms.

**Owner decisions applied (2026-09-10):**
- Tool name **`dir_explorer`** (Intent.DIR_EXPLORER) — sidesteps the `browse`
  collision; UI displays it as "Explorer" (browse → "Browser").
- `tree` output = **plain text** in `content`; rows in `metadata["results"]`.
- The S458 sweep incident is logged as a **protocol flaw**
  (`memory/flaws/log.md`, 2026-09-10 Amara entry, with the gate-teeth
  proposal: a `chore(ledger):` commit carrying product paths should fail
  pre-commit).
- Tool display-alias consolidation proposed + backlogged **B-2026-09-10-6**
  (two ad-hoc copies today: `toolLabels` in ToolSteps.tsx, `toolLabel()` in
  AgentWorkspace.tsx → one shared `frontend/src/lib/toolDisplay.ts`).
- Tier CORE + routing `_LOCAL_DISCOVERY_RE` extension accepted as defaults,
  gated on the ADR-40 weak-model live trace.

**Next session (feature `explorer-tool` manifest has the map + verification
bar):** implement `backend/src/tools/dir_explorer.py` + wiring + unit pins +
`scripts/live_test_dir_explorer.py`; ADR-40 weak-model live trace; schema-
budget pin updates; add the `dir_explorer → "Explorer"` UI alias entry.

**Carried next-up (not this session's scope):** P0 Step 5 — Checkpoint
Compaction; B-2026-09-10-1/2/3/4/5/6; OTT-26/27/29 clean rerun;
B-2026-09-09-2/3/6 peer claims.
