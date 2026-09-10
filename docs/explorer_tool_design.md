# Explorer tool `dir_explorer` — Design (LocalMind Parent)

**Status:** SHIPPED (2026-09-10). `backend/src/tools/dir_explorer.py` plus the
full §7 wiring landed with `tests/tools/test_dir_explorer.py`; the §10
live plan ran on the weak model (zai/glm-4.5-flash): all three inspection
prompts selected `dir_explorer` with the right operation and grounded,
bounded presentation, and `system_search`/`shell` selection did not
regress. One carried gap: the `grep_search` non-regression prompt never
completed on any healthy provider (repeated rate limits mid-chain) —
listed as a follow-up, not evidence of a regression.

**Session:** 459 (Amara) · **Date:** 2026-09-10 · **Feature:** `explorer-tool`
(implementation shipped next session) · **Scope:** Parent-only (exactly one
active agent — the Parent).

---

## 0. A correction to the brief

The brief you pasted describes LocalMind as "orchestrating multi-agent tasks"
with "child-agent, specialist, delegation" architecture. That is **not** the
current architecture. Per **ADR-53** (Session 303) and the standing Target,
LocalMind is **Parent-only**: exactly one active agent (the Parent) owns the
kernel, session, tools, planning, execution, and final answer. Existing
multi-agent code is parked compatibility residue, not current scope
(`memory/plans/decisions.md`, ADR-53). This design is therefore a **tool of the
Parent**, exactly like `system_search` and `file_task` — not a new agent.

The brief's API also proposes five separate functions
(`list_directory`, `read_file`, `search_files`, `get_metadata`, `read_tree`).
Three of those already exist in LocalMind under other names (see §2). Adding
five parallel tools would re-introduce the exact failure **Sessions 124/125** and
**Session 400** cured: a bloated schema that floods the context window
(~6k tokens/call before ADR-40) and, worse, **weak-model name-affinity
splitting** (zai picked `find_path` by name 4/4 when both a search tool and a
find tool were visible). So the design below collapses the brief's functions
into **one bounded tool with three operations**, following the `system_search`
pattern.

---

## 1. Goal and the gap

LocalMind can *find* files (`system_search`), *read* file contents
(`file_task`), and *search file content* (`grep_search`), but it has **no
first-class way to *look around* a folder**:

- "**What's in this folder?**" → today the model falls back to `shell ls` /
  `dir`, which returns unbracketed, non-normalized text with no metadata and no
  bounds, and on Windows/PowerShell is a different shape than `ls` (the
  `shell` steering text itself says *"file_task reads FILES, shell lists
  directories"* — so shell is the de-facto directory lister).
- "**Show me the shape of this project / what does this repo look like?**" →
  today the model improvises `tree`, `find -maxdepth`, or `ls -R` — the precise
  context-flood pattern **Sessions 124/125** fixed. The shell guard does
  redirect *broad recursive* scans to `system_search`, but a *bounded subtree
  sketch* has no home.
- "**Before I write here, does this path exist / what's already in it?**" →
  today the check-before-acting safety rule (`backend/data/workflows/safety.md`)
  is satisfied by shell `ls` or a `file_task` error. There is no cheap,
  bounded, normalized *pre-flight inspection* call.

That bounded, normalized, metadata-rich **directory inspection** verb is the
Explorer tool. It is distinct from `system_search` (*find by query → ranked
page*) and from `file_task` (*read a file's bytes*).

---

## 2. Current tool surface (what already exists — do not duplicate)

| Brief's function        | Already in LocalMind                                | Notes |
|-------------------------|-----------------------------------------------------|-------|
| `read_file`             | `file_task` (`backend/src/tools/file_reader.py`)     | Plain text 100 KB cap, line-numbered, chunked; PDF/DOCX/CSV/XLSX/OCR; cloud-placeholder handling (S422). |
| `search_files`          | `system_search` op `files` (`tools/system_search.py`)| Name/pattern over allowed roots; reuses `find_path` walk machinery (`_walk_catalog`, `_HEAVY_DIR_NAMES`, `_matches`). |
| `list_directory` / `get_metadata` | *(only via `shell ls`)*                    | Unbounded, un-normalized. **This is the gap.** |
| `read_tree`             | *(none)*                                            | The genuinely new capability. |

Schema surface context (ADR-40): the model gets ~15 `CORE_TOOL_NAMES` always,
plus on-demand long-tail via `describe_tool`. Each added core tool costs
per-call token budget and must be **live-verified** so weak models still pick
the right tool (ADR-40 / Session 251–252). `find_path` was *demoted* to
long-tail for exactly this reason (S400). That history is the central design
constraint: the Explorer must not create a second "find/locate" tool.

---

## 3. Design decision: ONE tool, three operations

```
dir_explorer (Intent.DIR_EXPLORER, core tool — position right after system_search)
├── operation=list   — one directory level: typed entries + size + mtime
├── operation=tree   — bounded subtree sketch (depth + entry caps)
└── operation=stat   — one path's metadata (the brief's get_metadata)
```

Rationale (why one tool, not three, and not three new tools):

1. **`system_search` precedent (S400).** One front door, sub-operations,
   normalized results. The model reasons over the op enum; deterministic code
   does the work. This keeps the schema surface small.
2. **Avoid the `find_path` lesson.** Three separate `list_*`/`read_*` tools
   invite weak-model name-affinity collisions with `system_search`/`grep_search`
   /`shell`. One tool with a clear verb ("explore/inspect this folder") is
   distinguishable from "find files by name".
3. **ADR-40 lean schemas / ADR-43 bounded helpers.** One schema, three ops;
   each op has self-evident params. The op enum is the only non-trivial field.
4. **ADR-53 Parent-only.** A tool, not an agent. Deterministic primitives
   inspect; the Parent understands and presents.

**Tier placement (decided — see §9):** **CORE**, positioned
immediately after `system_search`, because directory inspection is as frequent
as search in coding/file tasks. Per ADR-40 this stays contingent on a
weak-model live trace showing no regression in `system_search`/`grep_search`/
`shell`-ls selection; if selection is confused, drop to LONG_TAIL with a
`describe_tool` path.

---

## 4. API surface (model-facing schema)

Single OpenAI-function tool `dir_explorer`, mirroring `system_search`'s structure
(lean params, guardrail prose kept, tutorial prose dropped per ADR-40):

```json
{
            "name": "dir_explorer",
  "description": "Inspect LOCAL files/folders — use to look around a directory, sketch a project's structure, or check a path before writing. LOCAL disks only (NOT the web — that is 'browse'). For finding files by name/content use system_search/grep_search; for reading a file's contents use file_task.",
  "parameters": {
    "type": "object",
    "properties": {
      "operation": {"type": "string", "enum": ["list", "tree", "stat"],
        "description": "list=one folder's entries; tree=bounded subtree sketch; stat=one path's metadata"},
      "path": {"type": "string", "description": "Absolute or ~/ path inside an allowed folder"},
      "depth": {"type": "integer", "description": "tree only: max descent (default 2, max 4)", "default": 2},
      "max_entries": {"type": "integer", "description": "list/tree entry cap (default 200, max 500)"},
      "dirs_first": {"type": "boolean", "description": "list only: sort folders before files", "default": true}
    },
    "required": ["operation", "path"]
  }
}
```

**Return contract** (inherits `system_search` conventions): a `ToolResult`
whose `metadata["results"]` is a list of normalized rows
`{type, path, name, size, modified, detail}`, plus `walk_complete` /
`scanned` honesty flags in metadata. `content` is a compact human string — for `tree`, indented plain text
(decided, §9: token-cheap and human-readable); for `list`, a bounded table —
while `metadata["results"]` carries the structured rows either way. `success=False` + `requires_confirmation=False` on any error (read-only
→ never prompts the user). All failures degrade to `ToolResult(success=False)`
— **never raises**.

Bounds (by construction, copied from `system_search`):
time-budgeted walk (default 2.5 s, hard 10 s), entry cap (default 200, hard
500), `depth` hard cap 4, heavy dirs (`node_modules`, `.git`, …) marked
`skipped` and not descended, symlinks never followed (same `_HEAVY_DIR_NAMES`
allow-list reuse as `system_search`).

---

## 5. Security & guardrails (brief §2 → LocalMind reality)

| Brief proposal | LocalMind reality / design |
|---|---|
| Root Directory Jail (`BASE_DIR`) | **No bespoke jail.** Reuse `settings.is_path_allowed` (`core/config.py`) — the same allowed-roots the user already configured. Every `path` is resolved + `relative_to()`-checked; out-of-root → `success=False`, no prompt. This is *better* than a fixed `~/LocalMindWorkspace` because it respects the user's real machine layout. |
| Ignore / hidden lists (`.git`, `node_modules`, `.env`) | Reuse `_HEAVY_DIR_NAMES` for the "skip + mark `skipped`" behavior. **Crucially, secrets are not *hidden* — they are *out of scope*: `is_path_allowed` already gates the roots, and `dir_explorer` is read-only so it can never *exfiltrate* by writing. It must still not *print* `.env` contents — but `list`/`stat`/`tree` only emit names+metadata, never bytes, so no secret value is ever returned. |
| File size limits | N/A to `list`/`tree`/`stat` (they return metadata, not file bytes). The **bytes** cap already lives in `file_task` (`FILE_READ_MAX_BYTES`) — Explorer never reads bytes, so there is nothing to cap here. (If a future `preview` op is added, it reuses `file_task`'s cap.) |
| Read-only by default | **Hard read-only by construction.** Only `os.scandir` / `os.stat` — no write path exists. `RiskLevel.LOW`, `requires_confirmation=False`. Permission prompts (brief §3) are unnecessary for normal paths; an out-of-root attempt is a flat deny, not a prompt. |

The product/memory two-surface rule still applies: Explorer is product code; any
note about it goes in the project's agent-memory directory, never cited from
product docstrings.

---

## 6. UX mapping (brief §3 → existing mechanisms)

LocalMind already has every UX primitive the brief asks for — no new UI
surface is required (consistent with the S400 precedent: "Frontend untouched").

| Brief UX idea | Already exists in LocalMind |
|---|---|
| **Breadcrumbs** ("AI is looking at `<dir>`") | `loop.py` `action_label` builds a structured label from `path`/`command`/`query`; rendered in `frontend/src/components/chat/ToolSteps.tsx` (the Actions timeline, S210). `dir_explorer: list ~/Projects` shows automatically. |
| **Action chips** ("Read index.js (45 lines)") | Same `ToolSteps.tsx` step pill + `metadata` (entry count, `walk_complete`). No bespoke chip component needed. |
| **Permission prompts** | `ToolResult.requires_confirmation` + `RiskLevel` gate in the engine. Explorer is read-only → never triggers them. The *brief's* prompt scenario (accessing a protected folder) is handled as a silent deny, not an interrupt. |
| **Display name ("Explorer")** | The UI shows human aliases, not raw function names: this tool displays as **"Explorer"** while the web `browse` tool displays as **"Browser"**. Today that mapping lives in two ad-hoc copies (`toolLabels` in `ToolSteps.tsx`, `toolLabel()` in `AgentWorkspace.tsx`) with a capitalize-the-words fallback; the implementation session adds the `dir_explorer → "Explorer"` entry, and consolidating the copies into one shared alias module is proposed and backlogged (B-2026-09-10-6). The model-facing name stays `dir_explorer` — aliases are display-only and never shown to the model. |

Optional follow-up (NOT in this design): a collapsible "folder preview" panel
in `ToolSteps` rendering the `tree` output as an interactive outline. Defer —
it's polish, not core.

---

## 7. Wiring / integration checklist

The same checklist `system_search` followed (from its feature manifest), so the
implementation session reuses a known path:

| Piece | Location |
|---|---|
| Intent enum entry | `backend/src/core/models.py` (`EXPLORER`) |
| Tool module | `backend/src/tools/dir_explorer.py` |
| Registry import | `backend/src/tools/__init__.py` |
| Model-facing schema | `backend/src/core/agent/tool_schemas.py` (`TOOL_DEFINITIONS`, tier in `CORE_TOOL_NAMES`) |
| Allowed + per-intent scopes | `backend/src/core/agent/constants.py` (`AGENT_ALLOWED_TOOLS`, `INTENT_TOOL_SCOPES` — add to `_INTENT_CORE_LOCAL_TOOLS` and the `FILE_TASK`/`SYSTEM_SEARCH` intents) |
| Routing | `backend/src/core/trivial_input.py` — extend `_LOCAL_DISCOVERY_RE` so "show me / look at / what's in this folder / structure of" route to the agent loop, where the Parent picks `dir_explorer` (find-by-query stays `system_search`). |
| Steering | `file_task`/`shell` descriptions + agent-prompt strategy lines direct "list / inspect / tree" intents to `dir_explorer` instead of `shell ls`/`tree`. |
| Reuse | `tools/find_path.py` `_HEAVY_DIR_NAMES`, `_walk_catalog` for bounded traversal. |
| Tests | `tests/tools/test_dir_explorer.py` (unit: structure, bounds, honesty flags, security deny, never-raises). |
| Live harness | `scripts/live_test_dir_explorer.py` (env-keyed, no keys on disk; provider via `LOCALMIND_ADAPTER` + `<PROV>_API_KEY`, per S400). |

Schema-budget accounting: adding a core tool shifts the pinned counts
(`tools_architecture_proposal.md` pins: schema count, token budget, core /
long-tail split). The next session must update those pins and **live-verify
weak-model selection** (ADR-40) — see §10.

---

## 8. Relationship to the safety "check-before-acting" workflow

`backend/data/workflows/safety.md` mandates that every create/write/edit first
*verify the target's actual state*. Today that check is shell `ls` or a
`file_task` failure. Explorer makes the check **first-class and bounded**: when
the Parent is about to write to `path`, it can call `dir_explorer stat/list` first
to learn whether `path` exists, what's already there, and adapt — exactly the
workflow's intent — without spending a shell call or risking an unbounded
`ls`. This is a natural steering addition to `safety.md` and the agent system
prompt (the rule is already injected for all intents via
`build_agent_system_prompt`).

---

## 9. Owner decisions (2026-09-10)

1. **Tool name: `dir_explorer`** — decided. Sidesteps the `browse` (web
   browser) name collision entirely; no steering-only mitigation needed.
2. **`tree` output format: plain text** — decided. Indented plain text in
   `content` (token-cheap, human-readable); the normalized rows stay in
   `metadata["results"]` for the Parent to reason over.
3. **Tier: CORE** — proposed default accepted; positioned after
   `system_search`. Still gated on the ADR-40 weak-model live trace: if
   selection regresses on `system_search`/`grep_search`/`shell ls`, drop to
   LONG_TAIL + `describe_tool`.
4. **Routing: extend `_LOCAL_DISCOVERY_RE`** — proposed default accepted.
   "show me / look at / what's in / structure of" → agent loop (the Parent
   picks `dir_explorer`); find-by-query stays `system_search`. Phrasings are
   tuned live in the implementation session.

---

## 10. Verification plan (Session 274 bar + ADR-40)

This is a **design-only** session: no product code changed, so **no live test
is claimed**. The *implementation* session must satisfy:

- **Unit (structure):** `tests/tools/test_dir_explorer.py` pins the normalized row
  shape, depth/entry caps, `walk_complete`/`scanned` honesty, out-of-root deny,
  heavy-dir skip, symlink non-follow, and **never-raises**.
- **Live (mandatory, ADR-40):** a trace on a free provider
  (zen/deepseek-v4-flash-free primary; zai/glm-4.5-flash weak-model check)
  showing the model SELECTING `dir_explorer` for "what's in `~/Projects/LocalMind`"
  and "sketch the structure of this repo", and PRESENTING bounded output — and
  **not** regressing `system_search`/`grep_search`/`shell ls` selection. Tool-
  selection schema changes MUST be live-verified on the weak model before the
  next merge (echoing the `system_search` S400 bar). Report what was
  live-verified vs unit-tested vs assumed, per `system/live-testing.md`.

---

## 11. Out of scope (this design)

- Reading file *bytes* (owned by `file_task`; wire a `preview` op later, reusing
  its byte cap).
- Content/semantic search (owned by `grep_search` / `system_search` Phase 2).
- Any write/move/delete (separate, confirmation-gated tools; Explorer stays
  read-only).
- A new frontend panel (optional polish, §6).

---

## 12. References

- `backend/src/tools/system_search.py` — the front-door pattern Explorer mimics.
- `backend/src/tools/file_reader.py` — read capability Explorer must NOT duplicate.
- `backend/src/tools/find_path.py` — `_HEAVY_DIR_NAMES`, `_walk_catalog` reuse.
- `backend/src/core/agent/tool_schemas.py` — `CORE_TOOL_NAMES`, `LONG_TAIL`, `TOOL_DEFINITIONS` (ADR-40).
- `backend/src/core/agent/constants.py` — `AGENT_ALLOWED_TOOLS`, `INTENT_TOOL_SCOPES`.
- `backend/src/core/config.py` — `is_path_allowed`, `allowed_read_paths`.
- `backend/src/core/models.py` — `Intent`, `RiskLevel`, `ToolResult`.
- `backend/data/workflows/safety.md` — check-before-acting (§8).
- `frontend/src/components/chat/ToolSteps.tsx` — existing tool-step UI (§6).
- ADR-40 (lean schemas), ADR-43 (tools as bounded helpers), ADR-53 (Parent-only).
- `docs/tools_architecture_proposal.md`, `docs/parent-agent-spec.md`.
