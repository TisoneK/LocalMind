# ruff: noqa: E501 — long tool-description strings (schema data, like prompts.py)

"""Lean tool schemas for the native ``tools`` parameter (ADR-40).

ADR-40 / review-40 (Session 250): the model received ALL 30 kitchen-sink
schemas on EVERY call — ~24,230 chars (~6,057 tokens) — re-sent every
iteration, for every provider. The schemas were self-manuals ("the tool
feeding itself"): `browse` enumerated 10 modes with per-param tutorials,
`git` spelled out every flag, `delegate` described 7 agents inline.

This module is the SINGLE SOURCE OF TRUTH for the model-facing tool
catalog. Two surfaces derive from it:

1. **The native ``tools`` parameter** — composed per iteration by
   ``tool_defs_for_call()``: scoped CORE_TOOL_NAMES + ``describe_tool`` +
   loaded long-tail schemas (ADR-40 option C on-demand loading).
2. **The in-prompt "Available tools" list** — ``render_tool_list()``
   renders `- <name>: <description>` lines from the SAME definitions
   (see ``prompts.build_agent_system_prompt``/``build_planning_prompt``
   ``tool_defs`` parameter), so the prompt list and the native parameter
   can never drift apart again.

What the cut KEPT vs REMOVED (per ADR-40 guardrails):
- KEPT: every structural element — parameter names, JSON types, enums,
  ``required`` lists, array item schemas, ``additionalProperties``.
  The provider + ``_extract_tool_input`` depend on these to validate and
  parse model calls, and the tests pin them (git ops, browse actions,
  delegate contract, create_plan criteria, ...).
- KEPT: guardrails + weak-model disambiguation — "reset --hard is
  BLOCKED", "ALWAYS read the file with file_task before editing",
  "file_task reads FILES, shell lists directories", "use web_fetch AFTER
  web_search when snippets lack detail", and per-param descriptions ONLY
  for params that are not self-evident from their name (browse @e1 refs,
  network filters, edit_file action pairing, git stash/reset modes,
  delegate agent mapping, ...).
- REMOVED: tutorial prose and redundant per-param descriptions for
  self-evident params (path, query, content, message, operation, ...).
  The optional `description` label param is dropped from most tools — the
  loop already builds structured action labels from path/command/query
  when the model omits it (loop.py `action_label` fallback).

Measured (Session 251): the native `tools` param went from ~24,230 chars
(~6,057 tok) to ~15,981 chars (~3,995 tok) — a ~34% cut (~2,062 tok/call,
~36% of ADR-40's ~5.7k theoretical reclaimable). The remaining weight is
structural (names, types, enums, required) plus the guardrail/disambiguation
prose the ADR says to KEEP. The in-prompt tool list also shrank:
9,832 chars (~2,458 tok) -> ~5,929 chars (~1,482 tok) via the single-source
collapse.

ADR-40 option C (Session 252): the long tail now loads ON DEMAND via the
`describe_tool` meta-tool (the `skill`-loader pattern). The 14 CORE_TOOL_NAMES
(shell/file_task/file_write/edit_file/find_path/web_search/web_fetch/code_exec
+ git/process/memory_op/sysinfo/observe/calculator) are always present lean;
the 16 LONG_TAIL_TOOL_NAMES are NOT in the native `tools` param until the
model calls describe_tool(name) — tool_defs_for_call() composes the
per-iteration param (scoped core + describe_tool + loaded full schemas).
Measured (Session 252): the full-catalog per-iteration param dropped from
~16,937 chars (~4,234 tok) to ~7,851 chars (~1,962 tok) — a ~54% cut
(~2,272 tok/call); cumulative vs pre-ADR-40 that is ~68% (~5,095 tok/call).
The default SHELL intent scope went ~9,866 -> ~7,178 chars (~27%). The
remaining ~9.1k chars of long-tail schemas are paid only when a tool is
actually loaded (e.g. browse: 7,851 -> 9,624 chars for the full catalog).
LIVE-VERIFIED tool selection (Session 251 option B; Session 252 option C) on
the active weak model (zai/glm-4.5-flash) AND on cerebras. Do not ship a
further cut without a fresh live trace — trimming schemas can regress weak
models' tool choice.
"""

from core.skills import available_skills_summary

# ── Tier split (ADR-40 option C): always-present vs on-demand ──────────────
# Core tools stay in the native `tools` param on EVERY call, lean. Long-tail
# tools are NOT loaded by default — the model calls `describe_tool(name)` to
# pull a specific tool's FULL schema into the `tools` param for the rest of
# the run (the `skill`-loader pattern, per ADR-40 option C).
CORE_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "shell",
        "file_task",
        "file_write",
        "edit_file",
        # Session 400: find_path retired from the always-present surface —
        # system_search (operation=files) is the single search front door
        # (weak models split traffic between two name-search tools; zai trace
        # picked find_path by name-affinity 4/4). find_path's schema stays in
        # TOOL_DEFINITIONS (registry + internal file-ops dispatch intact).
        "system_search",
        "web_search",
        "web_fetch",
        "web_research",  # Session 340: adaptive web acquisition — always loaded
        "code_exec",
        "git",  # coding agent's #1 companion — keep always-present
        "process",
        "memory_op",
        "sysinfo",
        "observe",
        "calculator",
        "todo_write",  # ADR-43: agent-driven live UI todo checklist — always available
        # B-2026-08-30-13 (ADR-40 amendment): browse promoted from the long tail
        # to CORE. The describe_tool round-trip loaded ~3k chars of browse schema
        # EVERY turn a browse task ran — it blew the context window and timed the
        # turn out, and cost an extra iteration. The browser is now a first-class
        # capability (see B-2026-08-30-3 revert / -10 / -11) meant to become the
        # primary web tool, so its lean schema is always present, no docs load.
        "browse",
    }
)

LONG_TAIL_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "find_path",  # Session 400: retired from the always-present surface (system_search is the front door) — kept on-demand for compatibility
        "delegate",
        "delegate_parallel",
        "delegate_inline",
        "sql",
        "csv",
        "json",
        "best_of_n_edit",
        "propose_str_replace",
        "propose_write_file",
        "apply_proposed_edit",
        "add_subgoal",
        "update_subgoal",
        "create_plan",
        "skill",
        "diagnostics",
    }
)


# ── Tool Definitions (OpenAI function-calling format) ────────────────────────

TOOL_DEFINITIONS: list[dict] = [
    # Session 400: system_search FIRST — weak models have position
    # bias toward the first tools in the native param + prompt list; the
    # search front door leads the catalog.

    {
        "type": "function",
        "function": {
            "name": "system_search",
            "description": "Unified LOCAL SEARCH over this computer — use FIRST for any find/locate/discover question: files by name, recent files, largest files, duplicate copies, installed apps (+PATH executables), or which program opens a file type. Returns a small ranked page. Do NOT hunt with ls/dir/du/find in shell for these.",  # noqa: E501
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {"type": "string", "enum": ["files", "recent", "largest", "duplicates", "apps", "open_with"], "description": "files=name search; recent=modified last N days; largest=size-ranked; duplicates=same name+size; apps=installed programs; open_with=which app opens an ext"},  # noqa: E501
                    "query": {"type": "string", "description": "Name pattern / app name (required for files+apps)"},  # noqa: E501
                    "root": {"type": "string"},
                    "ext": {"type": "string"},
                    "kind": {"type": "string", "enum": ["file", "dir"]},
                    "days": {"type": "integer"},
                    "minutes": {"type": "integer", "description": "Recency window in minutes for operation=recent (wins over days)"},  # noqa: E501
                    "limit": {"type": "integer"},
                    "offset": {"type": "integer"},
                    "path": {"type": "string", "description": "File path for open_with"},
                },
                "required": ["operation"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for current information, news, prices, weather. Returns URLs + snippets; if snippets lack detail, use web_fetch to read the page.",  # noqa: E501
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch and extract readable text from a web page URL. Use AFTER web_search when the snippets are link-only and you need the actual page content (weather, prices, article facts).",  # noqa: E501
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_research",  # Session 340: adaptive web acquisition
            "description": "Research a topic on the web and return the most relevant, current content. Automatically searches for sources, fetches the best one (with JavaScript rendering if needed), validates the result, and falls back to alternative sources. Use this for ANY request needing current web information (weather, news, scores, standings, prices, etc.) — it handles search + fetch + browser escalation internally.",  # noqa: E501
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What information to find on the web."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browse",
            "description": "Real browser for JS/interactive pages. 'open'/'read' navigate AND return the page text in one step. 'batch' runs a whole flow in ONE call (steps=[open,click,read]) — prefer it over many browse calls. 'extract' → JSON array for a CSS selector (attr=text|href|src|value); 'links' all links; 'snapshot' @e refs for click/fill; 'dom' HTML. For a plain text/JSON GET prefer web_fetch. May expose page data.",  # noqa: E501
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "batch",
                            "open",
                            "read",
                            "extract",
                            "links",
                            "snapshot",
                            "click",
                            "fill",
                            "type",
                            "press",
                            "scroll",
                            "scrollintoview",
                            "screenshot",
                            "text",
                            "dom",
                            "network",
                            "console",
                            "url",
                            "title",
                            "eval",
                            "back",
                            "forward",
                            "reload",
                            "close",
                            "wait",
                        ],
                    },
                    "url": {"type": "string", "description": "For open/read: URL to navigate to"},
                    "steps": {"type": "array", "items": {"type": "object"}, "description": "For batch: action objects to run in order"},  # noqa: E501
                    "ref": {"type": "string", "description": "Element reference such as @e1 (from snapshot)"},
                    "selector": {"type": "string", "description": "For extract/dom: CSS selector"},
                    "attr": {"type": "string", "description": "For extract: text|href|src|value|<attribute>"},
                    "value": {"type": "string", "description": "Text, key, script, or wait target depending on action"},
                    "script": {"type": "string", "description": "For eval: JavaScript to execute"},
                    "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
                    "amount": {"type": "integer"},
                    "limit": {"type": "integer", "description": "For extract/links: max matches"},
                    "path": {"type": "string"},
                    "full": {"type": "boolean"},
                    "filter": {"type": "string", "description": "For network: URL pattern filter"},
                    "type": {"type": "string", "description": "For network: resource type filter, e.g. xhr,fetch"},
                    "method": {"type": "string", "description": "For network: HTTP method filter"},
                    "status": {"type": "string", "description": "For network: status filter, e.g. 2xx"},
                    "clear": {"type": "boolean", "description": "For network/console: clear captured entries after reading"},  # noqa: E501
                    "json": {"type": "boolean"},
                    "interactive": {"type": "boolean", "description": "For snapshot: interactive elements only (default true)"},  # noqa: E501
                    "stop_on_error": {"type": "boolean", "description": "For batch: stop at first failed step (default true)"},  # noqa: E501
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "code_exec",
            "description": "Run inline Python. To run a .py file, use shell.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code, inside a ```python``` block",
                    },
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_write",
            "description": "Write or save content to a file (creates parent directories). Use ONLY to CREATE or OVERWRITE — to modify an existing file use edit_file; to read use file_task. When creating a file in a folder you just listed with shell, use the exact folder path from that listing (check-before-acting).",  # noqa: E501
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Edit an existing file in-place: rewrite (full content), replace, regex_replace, insert, delete, append, prepend. Prefer over file_write for existing files. ALWAYS read the file with file_task before editing.",  # noqa: E501
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "action": {
                        "type": "string",
                        "enum": [
                            "rewrite",
                            "replace",
                            "regex_replace",
                            "insert",
                            "delete",
                            "append",
                            "prepend",
                        ],
                    },
                    "content": {"type": "string", "description": "For rewrite: the new full file content (omit action and pass only path + content for a full rewrite)"},
                    "search": {"type": "string", "description": "For replace/regex_replace/delete actions"},
                    "replace": {"type": "string", "description": "For replace/regex_replace actions"},
                    "insert_text": {"type": "string", "description": "For insert/append/prepend actions"},
                    "line": {"type": "integer"},
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"},
                    "pattern": {"type": "string", "description": "Regex pattern for regex_replace action"},
                    "all": {"type": "boolean", "description": "Replace all occurrences (default: false, first only)"},
                },
                "required": ["path", "action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_task",
            "description": "READ an existing FILE's contents (PDF, DOCX, XLSX, code, text/binary). READ-ONLY (to create/write a file use file_write). NOT for directory listings — use shell. Do NOT use shell 'cat'/'type' to read files.",  # noqa: E501
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_path",
            "description": "Find files/folders whose NAME matches (substring, glob, {a,b}, or keywords = AND any order) under a root; returns matching paths only, capped (10, max 25, depth 4). Use to LOCATE by name — never ls/dir to hunt.",  # noqa: E501
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Substring, glob, {a,b}, or keywords (ALL match, any order), case-insensitive"},
                    "root": {"type": "string"},
                    "max_depth": {"type": "integer"},
                    "max_results": {"type": "integer"},
                },
                "required": ["name"],
            },
        },
    },    {
        "type": "function",
        "function": {
            "name": "shell",
            "description": "Run a system command — but for FINDING things (files, folders, recent work, largest files, duplicates, installed programs) ALWAYS use system_search instead; never find/ls/du/dir hunts. Shell is for: folder listings, git, disk checks, OS commands. To READ file contents use file_task — NOT shell. To CREATE a file use file_write. Commands MUST match the current OS (Windows=PowerShell: Get-ChildItem, New-Item -ItemType Directory -Force; Unix=bash: ls, mkdir -p, cat, grep, find). NEVER use Unix syntax on Windows.",  # noqa: E501
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command — MUST match the OS (check env). Windows: Get-ChildItem, New-Item -ItemType Directory -Force. Unix: ls, mkdir -p, cat."},  # noqa: E501
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_op",
            "description": "Store, recall, or delete persistent facts about the user",
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["store", "recall", "forget", "list"],
                    },
                    "content": {"type": "string"},
                },
                "required": ["operation", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sysinfo",
            "description": "Get system info: time, date, OS, CPU, RAM, disk, network (IP/MAC/interfaces), GPU, top processes, environment, uptime, users, services/ports. Offline, instant. For INSTALLED PROGRAMS / 'do I have X installed?' / 'where is python?' use system_search (operation=apps) instead.",  # noqa: E501
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "observe",
            "description": "Observe the desktop right now (offline, instant, bounded): active window, clipboard, running apps, CPU/RAM/disk/battery state, recently modified files. Use for 'what's happening right now?' without shell.",  # noqa: E501
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to observe: window, clipboard, apps, cpu/ram, recent files"},  # noqa: E501
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "Evaluate a safe arithmetic expression exactly, offline: + - * / // % **, parentheses, pi/e/tau, abs/round/min/max/pow/sqrt/floor/ceil/exp/log/sin/cos/tan, and '15% of 80'. Use for precise numeric answers instead of shell.",  # noqa: E501
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string"},
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "csv",
            "description": "Read a CSV file as a compact bounded table (default 20 rows x 20 cols, max 50) — never the raw file. Use for 'what's in this CSV' without flooding context.",  # noqa: E501
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_rows": {"type": "integer"},
                    "max_cols": {"type": "integer"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "json",
            "description": "Parse and summarize JSON — from a file path (allowed folders) or inline JSON text. Optional dot-path query to drill in (e.g. a.b[0].c). Output is bounded: large collections are summarized, never dumped.",  # noqa: E501
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "query": {"type": "string", "description": "Optional dot-path to extract, e.g. 'a.b[0].c'"},
                    "max_items": {"type": "integer"},
                },
                "required": ["source"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sql",
            "description": "Run a READ-ONLY SQLite SELECT against a local .db/.sqlite file (path in allowed folders). Writes fail safely. Output is bounded (row cap 20, max 50). Use for 'what's in this database'.",  # noqa: E501
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "query": {"type": "string"},
                    "max_rows": {"type": "integer"},
                },
                "required": ["path", "query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delegate",
            "description": "Delegate a sub-task to a specialized agent: research (web), coding (shell+file+code), browser (headless), verifier (tests/reproduce), reviewer (code quality), debugger (root-cause), analyst (clarify), direct (single call, no tools). Costs an extra loop — prefer your own tools when they suffice.",  # noqa: E501
            "parameters": {
                "type": "object",
                "properties": {
                    "target_agent": {
                        "type": "string",
                        "enum": ["research", "coding", "browser", "direct", "verifier", "reviewer", "debugger", "analyst"],  # noqa: E501
                        "description": "'research' for web, 'coding' for shell+file+code, 'browser' for headless, 'direct' for a single call",
                    },
                    "task": {"type": "string"},
                    "scope": {"type": "array", "items": {"type": "string"}},
                    "constraints": {"type": "array", "items": {"type": "string"}},
                    "forbidden_tools": {"type": "array", "items": {"type": "string"}},
                    "input_evidence": {"type": "string"},
                    "output_contract": {"type": "object", "additionalProperties": {"type": "string"}},
                },
                "required": ["target_agent", "task"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delegate_parallel",
            "description": "Delegate MULTIPLE independent sub-tasks to agents IN PARALLEL (up to 5 targets, each {agent, task}). Returns a summary of every output. For a single dependent sub-task use 'delegate' instead.",  # noqa: E501
            "parameters": {
                "type": "object",
                "properties": {
                    "targets": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "agent": {
                                    "type": "string",
                                    "enum": ["research", "coding", "browser", "direct", "verifier", "reviewer", "debugger", "analyst"],  # noqa: E501
                                },
                                "task": {"type": "string"},
                            },
                            "required": ["agent", "task"],
                        },
                    }
                },
                "required": ["targets"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delegate_inline",
            "description": "Delegate an INLINE transformation to an inline-capable agent that REWRITES this conversation's history in place (currently only 'context_pruner', which compacts history when it grows too long). Use sparingly — it changes what you see next.",  # noqa: E501
            "parameters": {
                "type": "object",
                "properties": {
                    "target_agent": {"type": "string"},
                    "task": {"type": "string"},
                },
                "required": ["target_agent", "task"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_str_replace",
            "description": "Stage a search/replace edit as a PROPOSAL without touching disk (same args as edit_file). Returns a diff preview stored in a per-run registry; apply the winner with apply_proposed_edit. Nothing is written until you apply.",  # noqa: E501
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "action": {
                        "type": "string",
                        "enum": [
                            "replace",
                            "regex_replace",
                            "insert",
                            "delete",
                            "append",
                            "prepend",
                        ],
                    },
                    "search": {"type": "string", "description": "For replace/regex_replace/delete actions"},
                    "replace": {"type": "string", "description": "For replace/regex_replace actions"},
                    "insert_text": {"type": "string", "description": "For insert/append/prepend actions"},
                    "line": {"type": "integer"},
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"},
                    "pattern": {"type": "string", "description": "Regex pattern for regex_replace action"},
                    "all": {"type": "boolean"},
                },
                "required": ["path", "search", "replace"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_write_file",
            "description": "Stage a full-file write as a PROPOSAL without touching disk (path+content). Stored in a per-run registry; call apply_proposed_edit to write it. Use with propose_str_replace for best-of-N editing.",  # noqa: E501
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_proposed_edit",
            "description": "Write a staged proposal to disk (staged by propose_str_replace or propose_write_file). Same permission gating as file_write.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "best_of_n_edit",
            "description": "Produce N candidate edits for one file, pick the best via a selector agent, and apply it. Expensive (spawns N+1 sub-agents) — use sparingly for high-stakes edits.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "instruction": {"type": "string"},
                    "n": {"type": "integer"},
                    "strategies": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["file_path", "instruction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "todo_write",
            "description": "Write/update the live task checklist in the user's Todos panel. Pass the FULL list every call as todos:[{text,status}] with status 'pending'|'in_progress'|'completed'|'blocked'. Use for any multi-step task: create it up front, then call again to mark the current step in_progress and finished steps completed so the user sees live progress.",
            "parameters": {
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "completed", "blocked"],
                                },
                            },
                            "required": ["text"],
                        },
                    },
                },
                "required": ["todos"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_subgoal",
            "description": "Record a single subgoal in the run's subgoal scratchpad to track progress across iterations of a multi-step task. Prefer create_plan when you know several steps up front.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                },
                "required": ["description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_subgoal",
            "description": "Update a subgoal's status ('pending' | 'in_progress' | 'completed' | 'blocked') and/or attach notes. Ids come from add_subgoal / create_plan (e.g. 'sg-1').",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "completed", "blocked"],
                    },
                    "notes": {"type": "string"},
                },
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_plan",
            "description": "Create multiple subgoals for a multi-step task; optionally add success_criteria (the acceptance gate verifies them). Returns the scratchpad.",
            "parameters": {
                "type": "object",
                "properties": {
                    "steps": {"type": "array", "items": {"type": "string"}},
                    "success_criteria": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "2-4 concrete checkable statements proving success",
                    },
                },
                "required": ["steps"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "skill",
            "description": (
                "Load a specialized playbook (a 'skill' — markdown instructions) into your "
                "context when the task matches its domain (e.g. Python testing, git "
                "workflows, code review). Skills are read-only prompt fragments. "
                f"Available skills: {available_skills_summary()}."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_name": {"type": "string"},
                },
                "required": ["skill_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git",
            "description": "Structured Git operations (prefer over shell for git): status, diff, log, branch, checkout, commit, merge, stash, reset. reset --hard is BLOCKED. Check git status before committing and git log before resetting.",  # noqa: E501
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["status", "diff", "log", "branch", "checkout", "commit", "merge", "stash", "reset"],  # noqa: E501
                    },
                    "staged": {"type": "boolean", "description": "For 'diff': show staged changes (default: unstaged)"},
                    "count": {"type": "integer"},
                    "name": {"type": "string"},
                    "branch": {"type": "string"},
                    "message": {"type": "string"},
                    "add_all": {"type": "boolean", "description": "For 'commit': stage all changes first (git add -A); default: staged only"},  # noqa: E501
                    "action": {"type": "string", "enum": ["push", "pop", "list"], "description": "For 'stash': push (save), pop (restore+remove), or list; default push"},  # noqa: E501
                    "mode": {
                        "type": "string",
                        "enum": ["--soft", "--mixed", "--hard"],
                        "description": "For 'reset': --soft/--mixed keep changes; --hard is BLOCKED; default --mixed",
                    },
                    "ref": {"type": "string"},
                },
                "required": ["operation"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "process",
            "description": "Manage long-running processes: start (background, returns PID), stop (SIGTERM; force=true for SIGKILL), restart, status, logs (last 200 lines), wait (default 30s). Use for commands running >20s — shell kills commands after 20s.",  # noqa: E501
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["start", "stop", "restart", "status", "logs", "wait"],
                    },
                    "name": {"type": "string", "description": "Short identifier for the process (e.g. 'dev-server')"},
                    "command": {"type": "string"},
                    "force": {"type": "boolean"},
                    "timeout": {"type": "number"},
                },
                "required": ["operation"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "diagnostics",
            "description": "Structured analysis of errors, tracebacks, logs, and test failures: inspect_error, analyze_traceback, inspect_logs, inspect_test_failure. Returns severity + suggested next actions.",  # noqa: E501
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["inspect_error", "analyze_traceback", "inspect_logs", "inspect_test_failure"],  # noqa: E501
                    },
                    "text": {"type": "string"},
                    "path": {"type": "string", "description": "For inspect_logs: file to read; if omitted, 'text' is analyzed"},
                },
                "required": ["operation"],
            },
        },
    },
]


# ── describe_tool meta-tool (ADR-40 option C) ────────────────────────────────
# The on-demand loader, mirroring the `skill` tool: a tiny always-present
# index (the description below) plus load-a-specific-tool's-full-schema when
# selected. Kept OUT of TOOL_DEFINITIONS so the 30-tool catalog stays the
# backward-compatible module constant; it is appended by tool_defs_for_call().


def long_tail_tool_summary() -> str:
    """Comma-separated on-demand tool names (for the describe_tool hint)."""
    return ", ".join(sorted(LONG_TAIL_TOOL_NAMES))


def get_full_tool_def(name: str) -> dict | None:
    """Return the full tool definition for `name`, or None if unknown."""
    for td in TOOL_DEFINITIONS:
        if td.get("function", {}).get("name") == name:
            return td
    return None


DESCRIBE_TOOL_DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "describe_tool",
        "description": (
            "Load the FULL usage schema for an ON-DEMAND tool before using it. "
            "The schema is loaded for the NEXT native step and persists for "
            "the rest of this run. "
            "ONLY for the on-demand tools listed below. NEVER call this for a core "
            "tool (" + ", ".join(sorted(CORE_TOOL_NAMES)) + ") — including browse — "
            "they are already loaded; calling describe_tool on one wastes a step. "
            f"On-demand tools: {long_tail_tool_summary()}."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": "Name of the on-demand tool to load, e.g. 'sql'",
                },
            },
            "required": ["tool_name"],
        },
    },
}


def tool_defs_for_call(
    filtered_defs: list[dict],
    scoped_allowed: frozenset[str] | set[str],
    loaded_tools: set[str] | None = None,
    *,
    bootstrap_only: bool = False,
) -> list[dict]:
    """Compose the per-iteration native ``tools`` parameter (ADR-40 option C).

    ``filtered_defs`` is the scoped catalog (``_filtered_tool_defs``) which
    still contains ALL scoped tools incl. the long tail. This returns the
    reduced always-present surface: scoped CORE tools + ``describe_tool`` +
    the FULL schemas of any long-tail tools loaded this run (via
    ``describe_tool``), each gated by the scope so scoped agents never gain
    tools outside their allowed set.

    Args:
        filtered_defs: scoped tool defs from ``_filtered_tool_defs``.
        scoped_allowed: the effective allowed-name set (never None — callers
            pass ``AGENT_ALLOWED_TOOLS`` when no explicit scope).
        loaded_tools: names loaded this run via ``describe_tool``.

    Returns:
        The per-iteration ``tools`` param: core defs (catalog order) +
        ``describe_tool`` + loaded full defs (sorted by name). In bootstrap
        mode, only ``describe_tool`` and explicitly loaded tools are sent so
        direct conversation does not pay the full tool-schema cost.
    """
    if bootstrap_only:
        defs = [DESCRIBE_TOOL_DEFINITION]
        for name in sorted(loaded_tools or ()):
            if name in scoped_allowed:
                td = get_full_tool_def(name)
                if td is not None:
                    defs.append(td)
        return defs

    defs = [td for td in filtered_defs if td["function"]["name"] in CORE_TOOL_NAMES]
    defs.append(DESCRIBE_TOOL_DEFINITION)
    # Only LONG-TAIL names can be loaded — core tools are already in the base
    # set above, so appending them again would duplicate the schema.
    # NOTE: no dependency-gating here — composition just reflects what was
    # explicitly loaded via describe_tool. The gating lives in the model-facing
    # roster (long_tail_tool_summary / available_long_tail_tools), so the model
    # never LOADS an unavailable tool in the first place; if a caller loads one
    # directly, composing it is harmless.
    for name in sorted(loaded_tools or ()):
        if name in LONG_TAIL_TOOL_NAMES and name in scoped_allowed:
            td = get_full_tool_def(name)
            if td is not None:
                defs.append(td)
    return defs


def render_tool_list(tool_defs: list[dict] | None = None) -> list[str]:
    """Render the always-present "Available tools" lines for the system prompt.

    Renders `- <name>: <description>` from the tool definitions themselves so
    the in-prompt list and the native ``tools`` parameter share ONE source of
    truth (ADR-40 collapse of the 3 copies). The descriptions are already the
    lean Tier-1 form (one-liner + guardrails + disambiguation), so the full
    description is shown — trimming to the first sentence would drop the
    guardrail sentences ("reset --hard is BLOCKED") that this surface exists
    to carry for weak models.

    Args:
        tool_defs: scoped subset of TOOL_DEFINITIONS (e.g. from
            ``_filtered_tool_defs``). Defaults to the full catalog.

    Returns:
        List of `- name: description` lines, one per tool, in catalog order.
    """
    defs = tool_defs if tool_defs is not None else TOOL_DEFINITIONS
    return [
        f"  - {td.get('function', {}).get('name', '?')}: "
        f"{str(td.get('function', {}).get('description', '')).strip()}"
        for td in defs
    ]
