# Current Task

**Status:** IDLE — Session 395 closed (bulk backlog sprint: B-25 through B-37).

## Session 395 outcome (Sessions 384-395 bulk sprint)

Completed 10 backlog items across 12 sessions (384-395):

| Session | Item | Commit | Summary |
|---------|------|--------|---------|
| 384 | B-25 Agent `.tmp` folder | `41f2ff3` | Per-session `.tmp/` subfolder for scratch work |
| 385 | B-26 Three-dot menu | `504db33` | Left panel ⋮ overflow menu (Terminal, Agents, Memory, Settings) |
| 386 | B-27 Startup session | `cf6a6c2` | Resume-last vs new-chat setting + boot logic |
| 387 | B-28 Embed download | `0e81e95` | One-click Ollama embed pull with SSE progress |
| 388 | B-31 grep tool | `f632ca6` | `grep_search` tool for shell-off text search |
| 389 | B-34 Chat modes | `dcd301a` | Auto / Agent / Direct (no-tools) mode picker |
| 390 | B-35 Never rude | `00aa6c2` | Politeness rule + softened safety gate |
| 391 | B-36 Efficient read | `23c2fbd` | Line numbers, line-aware truncation, CRLF preservation |
| 392 | B-37 Write stats | `2050882` | `session_writes` table + logging + API |
| 395 | B-33 Op permissions | `d876703` | 8 tool-family permission toggles |
| 394 | B-29 Package UI | `e904686` | PackageInstaller in Terminal panel (pip/npm/ollama) |

**Test results:** 2425 backend passed (excluding 3 pre-existing failures: sqlite_vec, trivial_input, vector_store_busy); tsc clean; all pushed.

**Remaining unchecked backlog items:** B-30 (advisory/scoping only — do NOT build), B-9 (action-pill tooltips), B-12 (clickable filenames), B-20 (code block rewrite), B-21 (time formatting), B-22 (token K/M format), B-23 (advanced image viewer).
