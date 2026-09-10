# Feature: explorer-tool — Local file/folder inspection tool (Parent)

**Started:** 2026-09-10 · **Status:** active (design doc shipped, awaiting owner
approval; implementation is the next session) · **Sessions:** 459 (design)

## What this feature is

A **bounded, normalized, read-only local directory-inspection tool** for the
Parent agent — the "look around a folder / sketch a project's structure / check
a path before writing" verb that LocalMind currently lacks (it only has
`system_search` = find, and `file_task` = read a file). One tool, three
operations: `list` (one level + metadata), `tree` (bounded subtree sketch),
`stat` (one path's metadata). NOT a find tool (that's `system_search`), NOT a
file reader (that's `file_task`).

Design doc (the authority for this feature): `docs/explorer_tool_design.md`.

## Architecture (aligned with ADR-53 Parent-only scope)

A **tool of the Parent agent** — not a specialist agent, no delegation.
Deterministic `os.scandir`/`os.stat` walks do the INSPECTING; the Parent model
does the UNDERSTANDING + presenting (same split as `system_search`).

```
explorer (Intent.EXPLORER, proposed CORE — position after system_search)
├── operation=list   — one directory level: typed entries + size + mtime
├── operation=tree   — bounded subtree sketch (depth + entry caps)
└── operation=stat   — one path's metadata
```

Reuses `tools/find_path.py` `_HEAVY_DIR_NAMES` + `_walk_catalog` for bounded
traversal. Positioned after `system_search` because both are "know your
computer" local tools.

## Implementation map (next session)

| Piece | Location |
|---|---|
| Intent enum entry | `backend/src/core/models.py` (`EXPLORER`) |
| Tool module | `backend/src/tools/explorer.py` |
| Registry import | `backend/src/tools/__init__.py` |
| Model-facing schema | `backend/src/core/agent/tool_schemas.py` (`TOOL_DEFINITIONS`, tier in `CORE_TOOL_NAMES`) |
| Allowed + per-intent scopes | `backend/src/core/agent/constants.py` (`AGENT_ALLOWED_TOOLS`, `INTENT_TOOL_SCOPES`) |
| Routing | `backend/src/core/trivial_input.py` — extend `_LOCAL_DISCOVERY_RE` |
| Steering | `file_task`/`shell` descriptions + agent-prompt strategy lines |
| Tests | `tests/tools/test_explorer.py` |
| Live harness | `scripts/live_test_explorer.py` |

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

- Unit: `tests/tools/test_explorer.py` pins structure, bounds, honesty flags,
  security deny, symlink/heavy-dir skip, never-raises.
- **Live (ADR-40, mandatory for tool-selection schema change):** trace on a free
  provider (zen/deepseek-v4-flash-free primary; zai/glm-4.5-flash weak-model
  check) showing the model SELECTS `explorer` for "what's in `~/Projects/X`" and
  "sketch this repo's structure", PRESENTS bounded output, and does NOT regress
  `system_search`/`grep_search`/`shell ls` selection. Plus update the
  `tools_architecture_proposal.md` schema-count/budget pins.

## Session log

- **Session 459 (2026-09-10):** design-only session. Wrote
  `docs/explorer_tool_design.md`; registered feature; corrected the brief's
  "multi-agent" framing to Parent-only (ADR-53). No code. Open owner decisions
  in the doc §9 (name vs `browse`, core vs long-tail, routing phrasing, tree
  format).

## Open items for the owner (blocking build)

- Tool name `explorer` vs `browse` collision → steer, or rename `dir_browse`.
- Core vs long-tail tier (gated on ADR-40 live trace).
- `trivial_input.py` routing phrasing extension.
- `tree` output format (plain text vs JSON).
