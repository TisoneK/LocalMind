# Feature: system-search-tool — Local Search Intelligence (Phase 1)

**Started:** 2026-08-25 · **Status:** active · **Sessions:** 400+

## What this feature is

A unified **Local Search capability** for the Parent agent — the front door for
"help me find / know my computer" questions. Instead of the model choosing
among `find_path` / `sysinfo` / `observe` / `grep_search` / `shell` for local
discovery questions, ONE tool (`system_search`) routes the query to the right
sub-capability and returns NORMALIZED results the Parent reasons over and
presents.

User pitch (chat, 2026-08-25): "Where is my LocalMind project?" · "Find all
PDFs related to Wangari Maathai." · "Where did I save that CV I edited last
week?" · "Do I have multiple copies of this document?" · "Where is the program
I use to edit PDFs?" · "Find the largest files on my computer."

## Architecture (aligned with ADR-53 Parent-only scope)

This is a **tool capability of the Parent agent** — NOT a specialist agent, no
delegation, no child agents. Deterministic search primitives do the FINDING;
the Parent model does the UNDERSTANDING + presenting.

```
system_search (Intent.SYSTEM_SEARCH, core tool)
├── operation=files       — name/pattern file+folder discovery (reuses
│                          find_path walk machinery + catalog cache)
├── operation=recent      — files modified in last N days (multi-root,
│                          name/ext filter, mtime-ranked)
├── operation=largest     — size-ranked top-N files (disk usage questions)
├── operation=duplicates  — same name+size in multiple locations
├── operation=apps        — installed-application discovery (registry/brew/
│                          dpkg + PATH executables)
└── operation=open_with   — which installed app handles a file extension
```

Phase 2 (content/semantic search) and Phase 3 (AI ranking) are explicitly
out of scope for the first cut — `grep_search` already covers literal content
search; semantic ranking is a later feature.

## Implementation map

| Piece | Location |
|---|---|
| Intent enum entry | `backend/src/core/models.py` (`SYSTEM_SEARCH`) |
| Tool module | `backend/src/tools/system_search.py` |
| Registry import | `backend/src/tools/__init__.py` |
| Model-facing schema | `backend/src/core/agent/tool_schemas.py` (CORE_TOOL_NAMES + TOOL_DEFINITIONS) |
| Tests | `tests/tools/test_system_search.py` |
| Live-test harness | `scripts/live_test_system_search.py` (adapted cybercafé pattern) |

## Contracts

- **Security:** every root passes `settings.is_path_allowed`; symlinks never
  followed; heavy dirs skipped (node_modules/.git/etc.); no content leaves
  allowed roots.
- **Bounded:** time-budgeted walks (default 2.5s, hard 10s), entry cap 250k,
  result page cap (default 10, max 25). Output bounded BY CONSTRUCTION.
- **Honest:** `walk_complete` / `scanned` in metadata + content; partial scans
  say so; never claim "no results" from a partial scan without the caveat.
- **Normalized:** every result row is `{type, path|name, size, modified,
  detail}` so the Parent presents instead of parsing prose.
- **Never raises:** all failures degrade to ToolResult with success=False.

## Verification bar

Per `system/live-testing.md`: unit tests pin structure; the feature is only
"done" after a live trace on a free provider (primary: zen/deepseek-v4-flash-
free; weak-model check: zai/glm-4.5-flash) shows the model SELECTING
system_search for the pitch questions and presenting normalized results.
Tool-selection schema change (new core tool) MUST be live-verified on the weak
model per ADR-40.

## Session log

- **Session 400 (2026-08-25):** feature started. Implementation + tests + live
  test. (details in session entry)

## Session 400 outcome — IMPLEMENTED, live-verified on 2 free providers

**Commits:** `8e0e177` (product, pushed to main) + this context commit.

**What shipped:**
- `backend/src/tools/system_search.py` — the tool (6 ops, normalized results,
  bounded, security-gated, input_optional, weak-model plain-string + token
  relaxation fallbacks). Reuses `find_path` walk machinery for the files op.
- `Intent.SYSTEM_SEARCH` + registry import + CORE_TOOL_NAMES (front position —
  weak-model position bias) + scope wiring (`AGENT_ALLOWED_TOOLS`,
  `_INTENT_CORE_LOCAL_TOOLS`, `INTENT_TOOL_SCOPES`, routing map, goal
  template).
- **Routing fix** (`core/trivial_input.py`): `_LOCAL_DISCOVERY_RE` — first-
  person local-discovery questions route to the agent loop instead of the
  conversational fast path. Live-caught: "Where is my LocalMind project?"
  answered with ZERO tools ("check your terminal with pwd") at baseline.
- **find_path retired from the model-facing surface** → LONG_TAIL (on-demand
  via describe_tool). Registry + `core/file_ops.py` internal dispatch
  unchanged. Live-caught: zai picked find_path by name-affinity 4/4 when both
  search tools were visible.
- Steering: shell + sysinfo descriptions + agent-prompt strategy lines direct
  find/locate/discover intents to system_search.
- Tests: 24 tool tests, 36 routing tests, updated pins (schema count 33,
  budget 19,500, core 16 / long-tail 17). Backend **2586 passed / 2 skipped**,
  ruff clean on changed files. Frontend untouched.
- Harness: `scripts/live_test_system_search.py` (env-keyed, no keys on disk;
  provider via LOCALMIND_ADAPTER + <PROV>_API_KEY env).

**Live evidence (artifacts in `scratch/`, gitignored):**
| trace | provider | routed | tool selected | grounded |
|---|---|---|---|---|
| find_project baseline | zen/hy3-free | ✗ direct-chat (BUG) | — | ✗ |
| find_project fix-1 | zen/hy3-free | ✓ | shell ×2 | ✓ |
| find_project fix-2 | zai/glm-4.5-flash | ✓ | find_path ×4 (collision) | ✓ |
| **find_project final** | **zai** | ✓ | **system_search ×2 + token relaxation** | **✓** |
| apps_python final | zai | ✓ | sysinfo bare-call (Session 399 path; correct answer) | ✓ |
| largest_files final | zai | ✓ | shell `find /` (see open item) | ✓ |
| largest_files | zai | 429 rate limit — env failure, evidence preserved | — | — |

**Honest limits / open items:**
1. **"Find the largest files" phrasing still selects shell on glm-4.5-flash**
   — even after the model read shell's steering text via describe_tool.
   Model-conditioning limit, not a steering-text gap. Stronger models
   (deepseek-v4-flash, gemini) should follow the steering — user should
   re-verify on their usual provider. Backlogged as B-2026-08-25-1.
2. hy3-free (zen) ignored steering on all prompts (shell-happy weak model);
   zai followed it once find_path was retired. Provider quality matters more
   than steering text on the weakest tier.
3. zen/deepseek-v4-flash-free upstream-unavailable this session
   ("Model is unavailable", 400) — the documented primary provider could not
   be used; hy3-free + zai were the live providers. zen paid models 401
   ("No payment method").
4. zai rate limits (429, code 1302) after ~2 back-to-back turns — 45s+
   cooldowns needed; one largest_files trace lost to it (evidence kept).

**Next-session candidates:**
- B-2026-08-25-1: largest-files tool selection on weak models (deterministic
  pre-init nudge? or accept + document per-model behavior).
- Phase 2 content search wiring (grep_search visibility / semantic ranking)
  per the original feature pitch.
- open_with native macOS/Linux association checks on real OSes (sandbox
  container has no desktop associations — hint-map path only was live-testable).
