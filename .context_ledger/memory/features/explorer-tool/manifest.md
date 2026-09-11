# Feature: explorer-tool — Local file/folder inspection tool (Parent)

**Started:** 2026-09-10 · **Status:** COMPLETE (2026-09-10 — implementation +
weak-model live gate green on zai AND on the protocol's primary provider
bankofai/qwen3.8-flash; the carried re-verify closed in S464) ·
**Sessions:** 459 (design), 462 (implementation), 464 (primary-provider re-verify)

## What this feature is

A **bounded, normalized, read-only local directory-inspection tool** for the
Parent agent — the "look around a folder / sketch a project's structure / check
a path before writing" verb that LocalMind currently lacks (it only has
`system_search` = find, and `file_task` = read a file). One tool named
**`dir_explorer`** (owner-named 2026-09-10 to avoid the `browse` web-tool
collision), three operations: `list` (one level + metadata), `tree` (bounded
subtree sketch, plain-text output), `stat` (one path's metadata). NOT a find
tool (that's `system_search`), NOT a file reader (that's `file_task`).

Design doc (the authority for this feature): `docs/explorer_tool_design.md`.

## Architecture (aligned with ADR-53 Parent-only scope)

A **tool of the Parent agent** — not a specialist agent, no delegation.
Deterministic `os.scandir`/`os.stat` walks do the INSPECTING; the Parent model
does the UNDERSTANDING + presenting (same split as `system_search`).

```
dir_explorer (Intent.DIR_EXPLORER, CORE — owner-accepted default, gated on the
             ADR-40 weak-model live trace; position after system_search)
├── operation=list   — one directory level: typed entries + size + mtime
├── operation=tree   — bounded subtree sketch (depth + entry caps, plain text)
└── operation=stat   — one path's metadata
```

Reuses `tools/find_path.py` `_HEAVY_DIR_NAMES` + `_walk_catalog` for bounded
traversal. Positioned after `system_search` because both are "know your
computer" local tools.

## Implementation map (next session)

| Piece | Location |
|---|---|
| Intent enum entry | `backend/src/core/models.py` (`DIR_EXPLORER`) |
| Tool module | `backend/src/tools/dir_explorer.py` |
| Registry import | `backend/src/tools/__init__.py` |
| Model-facing schema | `backend/src/core/agent/tool_schemas.py` (`TOOL_DEFINITIONS`, tier in `CORE_TOOL_NAMES`) |
| Allowed + per-intent scopes | `backend/src/core/agent/constants.py` (`AGENT_ALLOWED_TOOLS`, `INTENT_TOOL_SCOPES`) |
| Routing | `backend/src/core/trivial_input.py` — extend `_LOCAL_DISCOVERY_RE` |
| Steering | `file_task`/`shell` descriptions + agent-prompt strategy lines |
| Tests | `tests/tools/test_dir_explorer.py` |
| Live harness | `scripts/live_test_dir_explorer.py` |

## Contracts (inherit from system_search hard lessons)

- **Security:** every `path` passes `settings.is_path_allowed`; symlinks never
  followed; heavy dirs (`node_modules`, `.git`, …) skipped + marked `skipped`;
  out-of-root → `ToolResult(success=False)`, no prompt.
- **Bounded:** time-budgeted walk (default 2.5 s, hard 10 s), entry cap
  (default 200, hard 500), `depth` hard cap 4.
- **Honest:** `walk_complete` / `scanned` in metadata + content; partial scans
  say so. Explorer returns only names+metadata — NEVER file bytes, so no secret
  value can leak.
- **Normalized:** every row `{type, path, name, size, modified, detail}` in
  `metadata["results"]`.
- **Never raises:** all failures degrade to `ToolResult(success=False)`.
- **Read-only by construction:** only `os.scandir`/`os.stat`; `RiskLevel.LOW`,
  `requires_confirmation=False`.

## Verification bar (next session — Session 274 mandate)

- Unit: `tests/tools/test_dir_explorer.py` pins structure, bounds, honesty flags,
  security deny, symlink/heavy-dir skip, never-raises.
- **Live (ADR-40, mandatory for tool-selection schema change):** trace on a free
  provider (zen/deepseek-v4-flash-free primary; zai/glm-4.5-flash weak-model
  check) showing the model SELECTS `dir_explorer` for "what's in `~/Projects/X`" and
  "sketch this repo's structure", PRESENTS bounded output, and does NOT regress
  `system_search`/`grep_search`/`shell ls` selection. Plus update the
  `tools_architecture_proposal.md` schema-count/budget pins.

## Session log

- **Session 459 (2026-09-10):** design-only session. Wrote
  `docs/explorer_tool_design.md`; registered feature; corrected the brief's
  "multi-agent" framing to Parent-only (ADR-53). No code. Open owner decisions
  in the doc §9 (name vs `browse`, core vs long-tail, routing phrasing, tree
  format).

## Owner decisions (2026-09-10) — RESOLVED, build unblocked

- **Tool name: `dir_explorer`** (owner) — avoids the `browse` web-tool name
  collision entirely.
- **`tree` output: plain text** (owner) — indented text in `content`; rows in
  `metadata["results"]`.
- **Tier: CORE** (owner accepted the default) — still gated on the ADR-40
  weak-model live trace; regression → LONG_TAIL + `describe_tool`.
- **Routing: extend `_LOCAL_DISCOVERY_RE`** (owner accepted the default) —
  phrasings tuned live in the implementation session.

Implementation session must also update the schema-count/budget pins —
CORRECTED during implementation: `tools_architecture_proposal.md` (a July
proposal) holds NO pins; the live pins are the lean-surface assertions in
`tests/core/test_tool_schemas_lean.py` (size budget + tool count) — both
updated in S462's feature commit.

## Session log

- **Session 462 (2026-09-10, Njeri / qwen3.8-flash, Windows):** implemented
  the full map (backend commits `9d85df0f`..`d1b88465`): tool module, Intent,
  registry, lean schema after system_search + CORE tier, scopes, grounded
  `_SIG_INSPECT` routing, steering (file_task/shell descriptions, planning
  templates, safety workflow), Exploring breadcrumbs on all three loop label
  dicts, "Explorer" alias in both frontend copies, 22 unit tests, live
  harness `scripts/live_test_dir_explorer.py`, pin updates, changelog.
  Weak-model gate on zai/glm-4.5-flash: list/tree/stat selection PASS
  (bounded + grounded presentation, plain-string args absorbed);
  system_search + shell regressions PASS; grep_search regression UNRESOLVED
  (provider rate limits killed all three attempts mid-chain) →
  B-2026-09-10-7. zen upstream DOWN all session ("Model is unavailable");
  bankofai account empty (balance=0) — owner action. Evidence + full
  verification split: `memory/reviews/2026-09-10-review-s462.md`.
- **Session 464 (2026-09-10, Elena / deepseek-v4-flash, macOS):** closed the
  carried gate on the protocol's PRIMARY provider. bankofai is reachable again
  but its configured default `deepseek-v4-flash` is no longer served, so the
  harness first gained a per-adapter model pin (`aa08cd5`; bankofai →
  `qwen3.8-flash`). Live run on bankofai/qwen3.8-flash: list/tree/stat
  selection **3/3 PASS** with grounded bounded output, `system_search` and
  `shell` non-regression **PASS**. The open content-search question is now
  ANSWERED: `dir_explorer` does not bleed into it — the model chose `shell`
  with a bounded `grep -rniE`, so the design's LONG_TAIL + `describe_tool`
  fallback is **not** required. That run's `grep_search` expectation turned out
  to be unsatisfiable: `grep_search` sits in no model-facing tier at all and
  never has, so the model cannot select it — a pre-existing wiring gap logged
  as **B-2026-09-10-8** (expose or retire), NOT a regression from this
  feature. Two follow-on fixes: the phantom `grep_search` pointer was removed
  from the description the model actually sees (`ef1c7cd`), and the stale CORE
  tool-count pin this feature left behind was corrected (`e61fd9f`).
  Evidence: `scratch/sse-direxplore-bankofai-*.sse` + `results-*.json`;
  report `memory/reviews/2026-09-10-review-s464.md`.
