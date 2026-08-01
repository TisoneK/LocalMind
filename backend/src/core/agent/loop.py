"""
AgentLoop — native tool/function calling via Ollama's API.

The main orchestration class for agent-mode responses.  Instead of forcing
the model to output fragile JSON like {"finish": {"answer": "..."}}, we use
Ollama's native tool calling API (chat_with_tools) which handles the
structured interaction for us.

v0.9 changes vs v0.8:
- Feature: Plan→Execute→Verify workflow — a planning LLM call runs before
  the main loop, producing a step-by-step plan that gets injected into the
  execution-phase system prompt. This eliminates trial-and-error iterations
  where the model fumbles with incomplete tool args.
- Feature: Post-execution verification — after file_write, the file is read
  back to confirm it was written correctly. After code_exec, the output is
  checked for common error indicators.
- Raised MAX_ITERATIONS to 8 (from 5) to accommodate the new phases.
- System prompt now includes plan context from the planning phase.
- Reduced wasted iterations: typical "Create X" tasks now complete in 2-3
  iterations instead of 5.

v0.8 changes vs v0.7:
- Fix: Duplicate tool entries — emit single tool_call obs event per iteration
  with a stable ID (tool_name + iteration), so frontend can match started/done
- Fix: Empty labels — build labels from structured tool_args (path, command,
  query) instead of raw concatenated tool_input string
- Fix: OS/shell awareness — inject _build_environment_context() into the
  agent system prompt so the model knows it's on Windows/Linux/macOS
- Feature: Tool arg validation — reject tool calls with missing required args
  before dispatching, giving the model a clear error message to self-correct

v0.7 changes vs v0.6:
- Bug A fix: file_write called without content now yields StreamChunk
  informing user about redirect to file_task (previously silent redirect)
- Bug B fix: Enhanced dedup cache works at tool_name level for file_write
- New tool: edit_file — in-place file editing

v0.6 changes vs v0.5 (JSON-parsing loop):
- Uses adapter.chat_with_tools() for native tool calling
- MAX_ITERATIONS raised to 5 (from 3)
- Deduplication and allowlist validation preserved
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from typing import AsyncIterator, Optional

from adapters.ollama import MultiToolCallResult, ToolCallResult
from core.agent.agent_filters import (
    _filter_code_output,
    _filter_system_leaks,
    _filter_tool_injection,
)
from core.agent.constants import (
    AGENT_ALLOWED_TOOLS,
    AGENT_INTENTS,
    CLARIFICATION_THRESHOLD,
    MAX_ITERATIONS,
    MAX_WALL_CLOCK_SECS,
    OBS_LOG_MAX_CHARS,
    PER_CALL_TIMEOUT_SECS,
    PLAN_ENABLED,
    PLAN_ITERATION_COST,
    PLAN_TIMEOUT_SECS,
    SYNTHESIS_ENABLED,
    SYNTHESIS_TIMEOUT_SECS,
    VERIFY_CODE_EXEC,
    VERIFY_ENABLED,
    VERIFY_FILE_WRITE,
    WORKSPACE_STATE_ENABLED,
)
from core.agent.models import AgentStep, AgentTrace
from core.models import Intent, StreamChunk, ToolResult


def _parse_plan_steps(plan_text: str) -> list[str]:
    """Parse the UNDERSTANDING/WHAT I KNOW/WHAT I'LL VERIFY/STEPS/ARGS_PRECHECK plan format.

    The planning prompt asks the model to respond with:
        UNDERSTANDING: [what the user needs]
        WHAT I KNOW: [relevant context]
        WHAT I'LL VERIFY: [verification plan]
        STEPS:
        1. [step description]
        2. [next step]
        ARGS_PRECHECK: [verification]

    This extracts the numbered steps so they can be shown as todos.
    """
    steps: list[str] = []
    in_steps = False
    for line in plan_text.split("\n"):
        stripped = line.strip()
        if stripped.upper().startswith("STEPS"):
            in_steps = True
            continue
        if stripped.upper().startswith("ARGS_PRECHECK"):
            in_steps = False
            continue
        if in_steps and stripped:
            # Match numbered steps: "1. Do something" or "1) Do something"
            match = re.match(r"^\d+[\.\)]\s*(.+)", stripped)
            if match:
                steps.append(match.group(1).strip())
    return steps


# ── Text-level tool call interception (MiniMax XML) ───────────────────────────
# MiniMax M2.5 and similar models sometimes generate tool calls as inline XML
# in the text content instead of using the structured tool_calls API format.
# Patterns like:
#   minimax:tool_call <invoke name="web_search"><parameter name="text">query</parameter></invoke></minimax:tool_call>
#   <invoke name="web_search"><parameter name="query">query</parameter></invoke>
# These must be intercepted, parsed, and actually EXECUTED — not just stripped.
# Without interception, the tool never runs and the model fabricates results.

_MINIMAX_TOOL_CALL_RE = re.compile(
    r"minimax:tool_call\s*"
    r"<invoke\s+name=[\"']([^\"']+)[\"']\s*>"
    r"(.*?)"
    r"</invoke>"
    r"\s*</minimax:tool_call>",
    re.DOTALL | re.IGNORECASE,
)

_STANDALONE_INVOKE_RE = re.compile(
    r"<invoke\s+name=[\"']([^\"']+)[\"']\s*>"
    r"(.*?)"
    r"</invoke>",
    re.DOTALL | re.IGNORECASE,
)

_PARAM_RE = re.compile(
    r"<parameter\s+name=[\"']([^\"']+)[\"']\s*>"
    r"(.*?)"
    r"</parameter>",
    re.DOTALL | re.IGNORECASE,
)

# Partial/streaming tool call patterns — catches incomplete XML that arrives
# across multiple streaming chunks
_MINIMAX_PARTIAL_RE = re.compile(
    r"minimax:tool_call\s*<invoke[^>]*>.*",
    re.DOTALL | re.IGNORECASE,
)

_STANDALONE_PARTIAL_RE = re.compile(
    r"<invoke\s+name=[\"'][^\"']+[\"'][^>]*>.*",
    re.DOTALL | re.IGNORECASE,
)


def _parse_minimax_tool_call(text: str) -> list[tuple[str, dict, str]]:
    """
    Parse MiniMax-style tool call XML from text content.

    Returns a list of (tool_name, tool_args, raw_xml) tuples.
    Each tuple represents one tool call found in the text.
    The raw_xml is the full XML string that should be removed from the text.

    Handles two formats:
    1. minimax:tool_call <invoke name="TOOL"><parameter name="ARG">VALUE</parameter></invoke></minimax:tool_call>
    2. <invoke name="TOOL"><parameter name="ARG">VALUE</parameter></invoke>
    """
    calls = []

    # Format 1: Full minimax:tool_call wrapper
    for m in _MINIMAX_TOOL_CALL_RE.finditer(text):
        tool_name = m.group(1).strip()
        params_xml = m.group(2)
        raw_xml = m.group(0)
        args = {}
        for pm in _PARAM_RE.finditer(params_xml):
            args[pm.group(1).strip()] = pm.group(2).strip()
        calls.append((tool_name, args, raw_xml))

    # Format 2: Standalone <invoke> without minimax:tool_call wrapper
    if not calls:
        for m in _STANDALONE_INVOKE_RE.finditer(text):
            tool_name = m.group(1).strip()
            params_xml = m.group(2)
            raw_xml = m.group(0)
            args = {}
            for pm in _PARAM_RE.finditer(params_xml):
                args[pm.group(1).strip()] = pm.group(2).strip()
            calls.append((tool_name, args, raw_xml))

    return calls


def _strip_minimax_tool_calls(text: str) -> str:
    """Remove all MiniMax tool call XML from text, leaving clean content."""
    cleaned = _MINIMAX_TOOL_CALL_RE.sub("", text)
    cleaned = _STANDALONE_INVOKE_RE.sub("", cleaned)
    cleaned = _MINIMAX_PARTIAL_RE.sub("", cleaned)
    cleaned = _STANDALONE_PARTIAL_RE.sub("", cleaned)
    # Also strip bare minimax:tool_call keyword
    cleaned = re.sub(r"minimax:tool_call\b", "", cleaned, flags=re.IGNORECASE)
    # Collapse runs of blank lines
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _has_minimax_tool_call(text: str) -> bool:
    """Quick check if text contains a MiniMax-style tool call pattern."""
    return bool(_MINIMAX_TOOL_CALL_RE.search(text) or _STANDALONE_INVOKE_RE.search(text))


from core.agent.prompts import build_agent_system_prompt, build_planning_prompt
from core.agent.synthesizer import AnswerSynthesizer
from core.agent.tool_dispatch import dispatch_with_retry
from core.context_builder import _build_environment_context
from core.workspace_state import format_snapshot, mark_turn_start
from core.workspace_state import snapshot as workspace_snapshot

logger = logging.getLogger(__name__)

# ── Tool Definitions (OpenAI function-calling format) ──────────────────────────

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for current information, news, prices, weather. Returns URLs and short snippets. If snippets don't contain enough detail to answer the question, use web_fetch to read the actual page content from the most relevant URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"},
                    "description": {
                        "type": "string",
                        "description": "Brief description of task (e.g., 'Finding Python async tutorials')",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch and extract readable text content from a web page URL. Use this AFTER web_search when the search results are link-only (URLs without substantive content in the snippets). This reads the actual page so you can extract specific facts like weather, prices, or article content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to fetch and read (from a web_search result)",
                    },
                    "description": {
                        "type": "string",
                        "description": "Brief description of what you're looking for on this page (e.g., 'Current weather conditions for Cheptais')",
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browse",
            "description": (
                "Drive a real headless browser. Navigate, inspect interactive elements, "
                "click, fill forms, scroll, take screenshots, read text or HTML, "
                "inspect network requests, read console messages, and execute JavaScript. "
                "Use DOM/network/console inspection only when needed; page output may "
                "contain sensitive user or session data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "open",
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
                        "description": "The browser action to perform",
                    },
                    "url": {"type": "string", "description": "For open: URL to navigate to"},
                    "ref": {"type": "string", "description": "Element reference such as @e1"},
                    "selector": {"type": "string", "description": "For dom: CSS selector or element reference; defaults to html"},
                    "value": {"type": "string", "description": "Text, key, script, or wait target depending on action"},
                    "script": {"type": "string", "description": "For eval: JavaScript to execute"},
                    "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
                    "amount": {"type": "integer", "description": "For scroll: pixel amount"},
                    "path": {"type": "string", "description": "For screenshot: optional output path"},
                    "full": {"type": "boolean", "description": "For screenshot: capture the full page"},
                    "filter": {"type": "string", "description": "For network: URL pattern filter"},
                    "type": {"type": "string", "description": "For network: resource type filter, such as xhr,fetch"},
                    "method": {"type": "string", "description": "For network: HTTP method filter"},
                    "status": {"type": "string", "description": "For network: status filter, such as 2xx"},
                    "clear": {"type": "boolean", "description": "For network/console: clear captured entries after reading"},
                    "json": {"type": "boolean", "description": "For console: return structured JSON output"},
                    "interactive": {"type": "boolean", "description": "For snapshot: limit output to interactive elements (default true)"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "code_exec",
            "description": "Execute Python code and return the output",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to execute (must be in a ```python``` block)",
                    },
                    "description": {
                        "type": "string",
                        "description": "Brief description of task (e.g., 'Testing sorting algorithm')",
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
            "description": "Write or save content to a file on disk. Creates parent directories automatically. Only use this when you need to CREATE or OVERWRITE a file — do NOT use this to check if a file exists or read its contents (use file_task instead).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path to write to (directories are auto-created)",
                    },
                    "content": {"type": "string", "description": "Content to write"},
                    "description": {
                        "type": "string",
                        "description": "Brief description of task (e.g., 'Creating hello world script')",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Edit an existing file in-place using search/replace, insert, delete, append, or prepend operations. Prefer this over file_write when modifying an existing file — it preserves the rest of the file and creates backups automatically. ALWAYS read the file with file_task before editing it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file to edit"},
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
                        "description": "The edit action to perform",
                    },
                    "search": {
                        "type": "string",
                        "description": "Text to search for (for replace/regex_replace/delete actions)",
                    },
                    "replace": {
                        "type": "string",
                        "description": "Replacement text (for replace/regex_replace actions)",
                    },
                    "insert_text": {
                        "type": "string",
                        "description": "Text to insert (for insert/append/prepend actions)",
                    },
                    "line": {
                        "type": "integer",
                        "description": "Line number for insert action (1-based)",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "Start line for delete action (1-based, inclusive)",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "End line for delete action (1-based, inclusive)",
                    },
                    "pattern": {
                        "type": "string",
                        "description": "Regex pattern for regex_replace action",
                    },
                    "all": {
                        "type": "boolean",
                        "description": "If true, replace all occurrences (default: false, replace first only)",
                    },
                },
                "required": ["path", "action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_task",
            "description": "Read the CONTENTS of a single FILE. Supports both text and binary formats: PDF, DOCX, XLSX, TXT, MD, CSV, JSON, YAML, HTML, XML, and code files. Automatically detects and parses file format. Use this to read any file — NOT for directories/folder listings. Do NOT use shell commands like 'type' or 'cat' for reading files — they only work for plain text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to a single FILE to read (NOT a directory)",
                    },
                    "description": {
                        "type": "string",
                        "description": "Brief description of task (e.g., 'Reading PDF document')",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shell",
            "description": "Run a system command or list directory contents. Use shell for: listing folders (dir/ls), finding files, git operations, disk checks, and OS commands. Use file_task to READ file contents — NOT shell commands. Shell commands like 'type' or 'cat' only work for plain text files and will fail on PDFs/DOCX/XLSX. Commands must match the current OS (Windows: dir/mkdir | Unix: ls/mkdir).",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute. For directory listings use 'dir <path>' (Windows) or 'ls <path>' (Unix). DO NOT use 'type' or 'cat' to read files — use file_task instead.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Brief description of task (e.g., 'Listing project files')",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_op",
            "description": "Store, recall, or delete persistent facts",
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["store", "recall", "forget", "list"],
                        "description": "The memory operation",
                    },
                    "content": {"type": "string", "description": "The fact or query"},
                },
                "required": ["operation", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sysinfo",
            "description": "Get current system info: time, date, hardware specs, installed programs",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "What system info to retrieve"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delegate",
            "description": (
                "Delegate a sub-task to another specialized agent. Use this when "
                "the current task requires a different domain of expertise (e.g., "
                "a coding task that needs web research, or a research task that "
                "needs file analysis). The sub-agent runs with its own scoped tools "
                "and returns its result; you continue with that result in your "
                "context. Available target agents: 'research' (web search + fetch), "
                "'coding' (shell + file tools + code exec), 'browser' (headless "
                "browser), 'verifier' (run tests, reproduce bugs, validate "
                "behavior), 'reviewer' (assess code quality and spec "
                "conformance), 'debugger' (isolate failures and find "
                "root causes of bugs), 'analyst' (understand requirements and "
                "clarify what to build), 'direct' (single model call, no tools). Use 'delegate' "
                "sparingly — it costs an extra agent loop. If you can handle the "
                "task with your own tools, do that instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target_agent": {
                        "type": "string",
                        "enum": ["research", "coding", "browser", "direct", "verifier", "reviewer", "debugger", "analyst"],
                        "description": (
                            "The agent to delegate to. 'research' for web search "
                            "+ fetch; 'coding' for shell + file tools + code exec; "
                            "'browser' for headless browser; 'direct' for a "
                            "single model call (no tools)."
                        ),
                    },
                    "task": {
                        "type": "string",
                        "description": (
                            "A clear, self-contained sub-task description that the "
                            "target agent can execute without further context. "
                            "Example: 'Find the current weather in Nairobi and "
                            "return the temperature + conditions.'"
                        ),
                    },
                    "scope": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of exactly what the child should investigate or change.",
                    },
                    "constraints": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional literal constraints such as 'Do not modify files'.",
                    },
                    "forbidden_tools": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional tools the child must not use, in addition to its agent allowlist.",
                    },
                    "input_evidence": {
                        "type": "string",
                        "description": "Optional selected evidence from the parent run; the child does not inherit parent history.",
                    },
                    "output_contract": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                        "description": "Optional named report requirements, for example {\"format\": \"structured report\"}.",
                    },
                },
                "required": ["target_agent", "task"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git",
            "description": (
                "Structured Git version control operations. Use this instead of "
                "shell for git commands — it provides semantic, structured output "
                "that's easier to reason about. Operations: status (working tree "
                "state — what's staged and unstaged), diff (show unstaged or staged "
                "changes), log (recent commit history), branch (list all branches "
                "or create a new one), checkout (switch to a different branch), "
                "commit (commit staged changes or stage-all-and-commit), merge "
                "(merge a branch into current), stash (push/pop/list stashed "
                "changes), reset (--soft/--mixed to undo commits — --hard is "
                "blocked for safety). ALWAYS check git status before committing. "
                "ALWAYS check git log before resetting to understand what you're "
                "undoing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["status", "diff", "log", "branch", "checkout", "commit", "merge", "stash", "reset"],
                        "description": "The git operation to perform",
                    },
                    "staged": {
                        "type": "boolean",
                        "description": "For 'diff': show staged changes instead of unstaged (default: false)",
                    },
                    "count": {
                        "type": "integer",
                        "description": "For 'log': number of recent commits to show (default: 10, max: 50)",
                    },
                    "name": {
                        "type": "string",
                        "description": "For 'branch': name of new branch to create",
                    },
                    "branch": {
                        "type": "string",
                        "description": "For 'checkout'/'merge': branch name to switch to or merge",
                    },
                    "message": {
                        "type": "string",
                        "description": "For 'commit': commit message. For 'stash': stash description",
                    },
                    "add_all": {
                        "type": "boolean",
                        "description": "For 'commit': stage all changes before committing (git add -A && git commit). Default: false (commit only staged changes)",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["push", "pop", "list"],
                        "description": "For 'stash': push (save changes), pop (restore and remove), or list (show all stashes). Default: push",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["--soft", "--mixed", "--hard"],
                        "description": "For 'reset': reset mode. --soft keeps changes staged; --mixed keeps changes unstaged; --hard is BLOCKED for safety (use shell if absolutely needed). Default: --mixed",
                    },
                    "ref": {
                        "type": "string",
                        "description": "For 'reset': ref to reset to (default: HEAD, which undoes the last commit)",
                    },
                },
                "required": ["operation"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "process",
            "description": (
                "Manage long-running processes — start, stop, restart, check status, "
                "read logs, and wait for completion. Use this for commands that run "
                "for more than a few seconds: dev servers (npm run dev, uvicorn), "
                "test runners (pytest, npm test), builds, docker containers. "
                "Operations: start (provide name + command → the process runs in "
                "background and you get its PID), stop (graceful SIGTERM by default, "
                "or force=true for SIGKILL), restart (stop + start), status (list "
                "all tracked processes or check a specific one), logs (read captured "
                "stdout/stderr — last 200 lines), wait (block until process finishes "
                "or timeout, default 30s). ALWAYS start long-running commands with "
                "this tool instead of shell — shell kills commands after 20s timeout."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["start", "stop", "restart", "status", "logs", "wait"],
                        "description": "The process operation to perform",
                    },
                    "name": {
                        "type": "string",
                        "description": "Process name — a short identifier you'll use to refer to this process in subsequent calls (e.g., 'dev-server', 'pytest-run')",
                    },
                    "command": {
                        "type": "string",
                        "description": "For 'start'/'restart': the shell command to run (e.g., 'npm run dev', 'uvicorn main:app'). Supports shell syntax like && and pipes.",
                    },
                    "force": {
                        "type": "boolean",
                        "description": "For 'stop': force-kill with SIGKILL instead of graceful SIGTERM. Default: false",
                    },
                    "timeout": {
                        "type": "number",
                        "description": "For 'wait': maximum seconds to wait (default: 30, max: 300)",
                    },
                },
                "required": ["operation"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "diagnostics",
            "description": (
                "Analyze errors, tracebacks, logs, and test failures to provide "
                "structured diagnostic output. Use this instead of raw shell or "
                "file_task when you need to understand WHY something failed. "
                "Operations: inspect_error (analyze an error message — extracts "
                "error type, message, stack frames, and likely origin), "
                "analyze_traceback (parse a Python traceback into call stack and "
                "immediate cause with file paths and line numbers), inspect_logs "
                "(scan log text or log file for error/warning patterns with counts), "
                "inspect_test_failure (parse pytest/unittest failure output into "
                "expected vs actual values, diff, and source location). All "
                "operations return structured output with severity classification "
                "and suggested next actions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["inspect_error", "analyze_traceback", "inspect_logs", "inspect_test_failure"],
                        "description": "The diagnostic operation to perform",
                    },
                    "text": {
                        "type": "string",
                        "description": "The error, traceback, log, or failure text to analyze",
                    },
                    "path": {
                        "type": "string",
                        "description": "For inspect_logs: optional file path to read logs from. If omitted, the 'text' parameter is analyzed directly.",
                    },
                },
                "required": ["operation"],
            },
        },
    },
]


# ── Helpers ────────────────────────────────────────────────────────────────────


def _truncate_observation(obs: str, max_chars: int = OBS_LOG_MAX_CHARS) -> str:
    """Trim a single observation entry for the running context log."""
    if len(obs) <= max_chars:
        return obs
    half = max_chars // 2
    return obs[:half] + f"\n… [{len(obs) - max_chars} chars truncated] …\n" + obs[-half:]


def _filtered_tool_defs(allowed_tools: Optional[frozenset[str]] = None) -> list[dict]:
    """Return TOOL_DEFINITIONS filtered to the allowed tool set.

    Args:
        allowed_tools: optional scoped toolset (from an AgentConfig). When
            provided, only tools whose name is in this set are returned.
            When None (the default), filters to AGENT_ALLOWED_TOOLS (the
            global allowlist) — preserving the pre-ADR-6 behavior.
    """
    allowed_names = allowed_tools if allowed_tools is not None else AGENT_ALLOWED_TOOLS
    return [td for td in TOOL_DEFINITIONS if td["function"]["name"] in allowed_names]


# ── Tool-talk detection ────────────────────────────────────────────────────────
# Small models (≤3B) sometimes narrate their intent to use a tool instead of
# actually invoking it.  These patterns detect that failure mode so we can
# suppress the leaked text and retry with a corrective hint.

_TOOL_TALK_PATTERNS = [
    re.compile(r"please provide (me with |the )?tool results?", re.IGNORECASE),
    re.compile(r"i need (you to |the )?tool results?", re.IGNORECASE),
    re.compile(r"provide (me with |the )?results? of (the )?tool", re.IGNORECASE),
    re.compile(r"i (will|would|need to|am going to) (use|call|invoke|run) (the )?(\w+) tool", re.IGNORECASE),
    re.compile(r"let me (use|call|invoke|run) (the )?(\w+) tool", re.IGNORECASE),
    re.compile(r"i('ll| will) (need to |try to )?(search|look up|execute|run|query)", re.IGNORECASE),
    re.compile(r"to answer (this|your) (question|request),? i (will|would|need to)", re.IGNORECASE),
    re.compile(r"<tool>|<action>|<function>", re.IGNORECASE),
    re.compile(r"tool_call|function_call|invoke_tool", re.IGNORECASE),
    # MiniMax-style: "I will call the web_search tool" followed by XML
    re.compile(r"i('ll| will) (now |then )?(call|use|invoke) (the )?\w+ (tool|function)", re.IGNORECASE),
    # v0.7: Additional plain-text tool narration patterns — models like MiniMax M2.5
    # sometimes describe what they would do instead of actually doing it.
    # These catch "I'm searching for...", "Let me look that up...", "Searching..."
    # followed by fabricated results from training data.
    re.compile(r"(i'm|i am) (now )?(searching|looking up|fetching|checking|finding)", re.IGNORECASE),
    re.compile(r"(searching|fetching|looking up|checking).{0,30}(for|on|in|about)\b", re.IGNORECASE),
    re.compile(r"let me (search|look|check|find|fetch|browse)", re.IGNORECASE),
    re.compile(r"i('ll| will) (search|look|check|find|fetch) (the |online |the web |on )?", re.IGNORECASE),
    re.compile(r"\[tool_call\]|\[search\]|\[tool\]", re.IGNORECASE),
    re.compile(r"\bsearching\.{3,}\b", re.IGNORECASE),  # "Searching..." theatrical animation
    re.compile(r"\bfetching\.{3,}\b", re.IGNORECASE),
    re.compile(r"\blooking up\.{3,}\b", re.IGNORECASE),
]

_MAX_TOOL_TALK_RECOVERIES = 2


def _is_tool_talk(text: str) -> bool:
    """Return True if the model is narrating tool intent instead of calling tools."""
    if not text or len(text.strip()) < 10:
        return False
    return any(p.search(text) for p in _TOOL_TALK_PATTERNS)


def _extract_tool_input(tool_name: str, tool_args: dict) -> str:
    """
    Extract a single string 'input' from the tool's arguments.

    Different tools structure their arguments differently.  The dispatch
    system expects a single string input.  This function normalises the
    dict returned by Ollama's tool calling into that string.

    For tools with a single required parameter, we use that value.
    For tools with multiple parameters, we join them into a
    semi-structured string that the tool dispatcher can parse.
    """
    if tool_name == "web_search":
        return tool_args.get("query", "")
    elif tool_name == "web_fetch":
        return tool_args.get("url", "")
    elif tool_name == "code_exec":
        return tool_args.get("code", "")
    elif tool_name == "file_write":
        # file_write dispatcher expects "path:\n\ncontent" format
        path = tool_args.get("path", "")
        content = tool_args.get("content", "")
        return f"{path}:\n\n{content}"
    elif tool_name == "edit_file":
        # edit_file: serialise args as JSON for the dispatch layer
        return json.dumps(tool_args, ensure_ascii=False)
    elif tool_name == "file_task":
        return tool_args.get("path", "")
    elif tool_name == "shell":
        return tool_args.get("command", "")
    elif tool_name == "memory_op":
        operation = tool_args.get("operation", "recall")
        content = tool_args.get("content", "")
        return f"{operation} {content}".strip()
    elif tool_name == "sysinfo":
        return tool_args.get("query", "")
    elif tool_name == "delegate":
        # delegate dispatcher expects JSON-encoded args (target_agent + task)
        # — same pattern as edit_file. The delegate tool parses it back.
        return json.dumps(tool_args, ensure_ascii=False)
    elif tool_name == "git":
        # git dispatcher expects JSON-encoded args (operation + params)
        # — same pattern as delegate/edit_file. The git tool parses it back.
        return json.dumps(tool_args, ensure_ascii=False)
    elif tool_name == "process":
        # process dispatcher expects JSON-encoded args (operation + params)
        # — same pattern as git/delegate. The process tool parses it back.
        return json.dumps(tool_args, ensure_ascii=False)
    elif tool_name == "diagnostics":
        # diagnostics dispatcher expects JSON-encoded args (operation + text/path)
        return json.dumps(tool_args, ensure_ascii=False)
    elif tool_name == "browse":
        # browse dispatcher expects JSON-encoded args so action-specific
        # options (selector, filters, clear/json flags) survive dispatch.
        return json.dumps(tool_args, ensure_ascii=False)
    else:
        # Fallback: join all values
        return " ".join(str(v) for v in tool_args.values() if v)


# ── AgentLoop ──────────────────────────────────────────────────────────────────


class AgentLoop:
    """
    Runs the think → act → observe cycle for a single user turn using
    Ollama's native tool calling API.

    Usage (called by Engine.stream()):
        async for chunk in agent_loop.run(messages, intent, ...):
            yield chunk

    Note: CHAT intent should NOT be routed here — engine.py handles CHAT
    by streaming directly via adapter.chat().
    """

    def __init__(self, adapter):
        self._adapter = adapter
        self._synthesizer = AnswerSynthesizer(
            enabled=SYNTHESIS_ENABLED,
            timeout_secs=SYNTHESIS_TIMEOUT_SECS,
        )

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(
        self,
        messages: list[dict],
        intent: Intent,
        initial_tool_result: Optional[ToolResult],
        available_tools: list[dict],
        confidence: float = 1.0,
        adapter=None,
        intent_history: Optional[list[str]] = None,
        obs=None,
        memory_facts: Optional[list[str]] = None,
        orchestrator_context: Optional[str] = None,
        skip_planning: bool = False,
        agent_config=None,
        agent_context: Optional[str] = None,
        allowed_tool_names: Optional[frozenset[str]] = None,
    ) -> AsyncIterator[StreamChunk]:
        """
        Run the agent loop with the Plan→Execute→Verify workflow.

        Flow:
        0. [Plan] If PLAN_ENABLED, run a planning LLM call (no tools) to
           produce a step-by-step plan. Inject it into the execution prompt.
        1. Build filtered tool definitions
        2. Loop up to MAX_ITERATIONS:
           a. Call adapter.chat_with_tools() with tool definitions
           b. If ToolCallResult → validate, dispatch, verify, add to context, continue
           c. If AsyncIterator[StreamChunk] → stream to user, return
        3. If max iterations hit, force a final answer

        Args:
            orchestrator_context: Optional context from the Orchestrator layer
                (three-layer pipeline). Contains the structured execution plan
                and confidence assessment. When present, the Execution Agent
                should follow this plan rather than planning independently.
            agent_config: Optional AgentConfig from the selected BaseAgent
                subclass (ADR-6). When provided, its `max_iterations` and
                `max_wall_clock_secs` override the module-level defaults
                (ADR-8 Phase 2 — was dead code before; now honored).
            agent_context: Optional agent-specific context string from the
                selected BaseAgent's build_context() method (ADR-8 Phase 2).
                When the CodingAgent is selected for SHELL/FILE_*/CODE_EXEC
                intents, this contains the coding playbook loaded from
                agents/coding/playbook.md. Passed through to
                build_agent_system_prompt() and injected as the
                `agent_context_section` in the system prompt.
        """
        active_adapter = adapter or self._adapter
        trace = AgentTrace()
        _obs = obs  # may be None — all obs.emit() calls guarded below
        _loop_start_time = time.monotonic()  # ADR-5: wall-clock cap baseline

        # ADR-8 Phase 2 (Session 34): honor agent_config.max_iterations
        # and agent_config.max_wall_clock_secs when provided. Previously
        # these were dead code — the loop used module-level MAX_ITERATIONS
        # and MAX_WALL_CLOCK_SECS regardless of which agent was selected.
        # Now the CodingAgent can have more headroom (20 iterations / 10
        # minutes) than the generic loop (8 iterations / 3 minutes),
        # appropriate for coding tasks that need more steps. Fall back to
        # the module-level defaults if agent_config is None or its caps
        # are unset/invalid.
        if (
            agent_config is not None
            and getattr(agent_config, "max_iterations", None)
            and isinstance(agent_config.max_iterations, int)
            and agent_config.max_iterations >= 1
        ):
            _effective_max_iter = agent_config.max_iterations
        else:
            _effective_max_iter = MAX_ITERATIONS
        if (
            agent_config is not None
            and getattr(agent_config, "max_wall_clock_secs", None)
            and isinstance(agent_config.max_wall_clock_secs, (int, float))
            and agent_config.max_wall_clock_secs >= 1
        ):
            _effective_max_wall = agent_config.max_wall_clock_secs
        else:
            _effective_max_wall = MAX_WALL_CLOCK_SECS

        if _obs:
            _obs.emit("agent_loop_start", intent=intent.value)

        # ── Clarification gate ─────────────────────────────────────────
        if confidence < CLARIFICATION_THRESHOLD and intent in AGENT_INTENTS:
            clarification = (
                f"I want to make sure I understand — it looks like you want me to "
                f"use the **{intent.value.replace('_', ' ')}** tool, but I'm not very confident. "
                f"Could you confirm, or rephrase what you'd like me to do?"
            )
            trace.clarification_issued = True
            yield StreamChunk(text=clarification, done=False)
            yield StreamChunk(text="", done=True)
            if _obs:
                _obs.emit("agent_loop_done", intent=intent.value, clarification=True)
            return

        # ── Build tool definitions filtered by allowlist ───────────────
        # ADR-6: when an agent_config is provided, use its scoped
        # allowed_tools instead of the global AGENT_ALLOWED_TOOLS. This
        # is the ADR-6 value — a coding agent sees only 5 tools, a
        # browser agent sees only 1, etc. Smaller surface = more
        # reliable selection on gemma3:1b-class hardware.
        scoped_tools = agent_config.allowed_tools if agent_config is not None else None
        effective_allowed = allowed_tool_names
        if effective_allowed is not None:
            scoped_tools = frozenset(scoped_tools or AGENT_ALLOWED_TOOLS).intersection(effective_allowed)
        filtered_tools = _filtered_tool_defs(scoped_tools)
        env_context = _build_environment_context()

        # ── ADR-5: Workspace state feedback ──────────────────────────────
        # Mark the turn start (records current HEAD for diff tracking),
        # then take a snapshot of git status/diff/build result. The
        # snapshot is injected into the system prompt below — this is the
        # "observations flow back into context every turn" loop from the
        # CODING HARNESS diagram, the literal difference between a harness
        # and a bare API.
        workspace_context = ""
        if WORKSPACE_STATE_ENABLED:
            try:
                mark_turn_start()
                ws_snap = workspace_snapshot()
                workspace_context = format_snapshot(ws_snap)
                if workspace_context:
                    logger.debug(
                        "[agent_loop] workspace_state injected (%d chars)",
                        len(workspace_context),
                    )
            except Exception as ws_exc:
                # Workspace state must never break the agent loop —
                # log and continue with empty context.
                logger.warning("[agent_loop] workspace_state failed: %s", ws_exc)
                workspace_context = ""

        # ── Phase 0: Planning ────────────────────────────────────────────
        # Run a separate LLM call (no tools) to produce a step-by-step plan.
        # The plan is then injected into the execution-phase system prompt
        # so the model knows exactly what to do on its first iteration,
        # eliminating the trial-and-error pattern where it fumbles with
        # incomplete args for 3-5 iterations.
        #
        # v0.11: skip_planning=True when the ThinkingDispatcher already
        # classified intent with high confidence (≥0.7). The dispatcher's
        # reformulation already serves as a "plan" — running another LLM
        # call here just adds 2-6s of latency for no value.
        plan_context = ""
        iteration_offset = 0  # how many iterations the planning phase consumed
        if PLAN_ENABLED and intent in AGENT_INTENTS and not initial_tool_result and not skip_planning:
            # Stream the plan in real-time as thinking tokens so the user
            # sees the model's reasoning (UNDERSTANDING, STEPS, ARGS_PRECHECK)
            # as it happens — not after the full plan is generated.
            yield StreamChunk(text="", done=False, thinking="start")
            if _obs:
                _obs.emit("agent_planning_start", intent=intent.value)

            # Collect plan while streaming thinking tokens to the user
            plan_chunks: list[str] = []
            async for plan_chunk in self._plan_stream(
                active_adapter=active_adapter,
                intent=intent,
                loop_messages=messages,
                available_tools=available_tools,
                env_context=env_context,
                intent_history=intent_history,
            ):
                if plan_chunk:
                    plan_chunks.append(plan_chunk)
                    # Stream as thinking token — the frontend shows this in
                    # the thinking block in real-time
                    yield StreamChunk(text="", done=False, thinking=plan_chunk)

            yield StreamChunk(text="", done=False, thinking="end")
            plan_context = "".join(plan_chunks).strip()

            # Truncate plan to prevent context bloat
            _PLAN_MAX_CHARS = 1500
            if len(plan_context) > _PLAN_MAX_CHARS:
                plan_context = plan_context[:_PLAN_MAX_CHARS] + "\n[... plan truncated]"

            iteration_offset = 1  # PLAN_ITERATION_COST
            trace.plan_text = plan_context
            if _obs:
                _obs.emit(
                    "agent_planning_done",
                    intent=intent.value,
                    plan_len=len(plan_context),
                    iterations_cost=iteration_offset,
                )

            # Parse plan steps and emit as todo items via obs
            # so the frontend's Todos panel shows the execution plan
            _plan_steps = _parse_plan_steps(plan_context)
            if _plan_steps and _obs:
                for i, step in enumerate(_plan_steps):
                    _obs.emit("todo_created", id=f"plan-{i}", text=step, completed=False)
        else:
            _plan_steps = []

        # Track which plan step we're currently executing so we can mark
        # todos as complete when their corresponding tool finishes.
        _plan_step_cursor = 0

        # ── Inject agent system prompt (with plan context) ──────────────
        loop_messages = list(messages)

        # Use the new prompt builder that supports plan context, memory facts,
        # and orchestrator context (three-layer pipeline)
        system_prompt = build_agent_system_prompt(
            intent=intent,
            available_tools=available_tools,
            intent_history=intent_history,
            plan_context=plan_context if plan_context else None,
            memory_facts=memory_facts,
            orchestrator_context=orchestrator_context,
            agent_context=agent_context,
        )

        # ADR-5: append workspace state to the system prompt. This is the
        # feedback loop — git status, diff since last turn, last build
        # result — that turns a bare API call into a real harness.
        if workspace_context:
            system_prompt = system_prompt + "\n\n" + workspace_context

        # Replace or prepend the system message
        if loop_messages and loop_messages[0]["role"] == "system":
            loop_messages[0] = {
                "role": "system",
                "content": loop_messages[0]["content"] + "\n\n" + system_prompt,
            }
        else:
            loop_messages.insert(0, {"role": "system", "content": system_prompt})

        # ── Seed observation log with initial tool result ──────────────
        observation_log = ""
        last_tool_failed = False
        consecutive_failures = 0
        fabrication_risk = 0  # Incremented on tool errors and fabrication-prone patterns

        if initial_tool_result:
            safe_initial = _filter_tool_injection(initial_tool_result.content)
            # Inject as tool messages (proper OpenAI format — the model sees this in context).
            # Do NOT also add to observation_log: the tool messages ARE the observation.
            # Adding to observation_log AND injecting as tool messages triples the context cost.
            tool_call_id = str(uuid.uuid4())
            loop_messages.append(
                {
                    "role": "assistant",
                    "content": "I've already performed an initial action. Let me analyze the result.",
                    "tool_calls": [
                        {
                            "id": tool_call_id,
                            "type": "function",
                            "function": {
                                "name": initial_tool_result.source,
                                "arguments": "{}",
                            },
                        }
                    ],
                }
            )
            loop_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": _truncate_observation(safe_initial),
                }
            )

        # Per-turn tool call cache: (tool_name, normalised_input) → observation text.
        _call_cache: dict[tuple[str, str], str] = {}

        # ── Collected tool results for post-loop synthesis ──────────────
        # Track all ToolResults from this turn so the AnswerSynthesizer
        # can extract and synthesize them into a user-facing answer after
        # the loop completes. Without this, raw search links and HTML
        # content leak directly to the user.
        collected_results: list[ToolResult] = []

        # ── Bug B fix: name-level dedup for file_write ────────────────────
        # Track which file paths have been written to in this turn. If the
        # agent calls file_write on the same path twice (even with different
        # content), the second call is almost always redundant or a mistake.
        # The fingerprint-level dedup above only catches identical inputs,
        # but the model may produce slightly different content strings on
        # retry, defeating the exact-match dedup.
        _file_write_paths: set[str] = set()

        # ── Main loop ──────────────────────────────────────────────────
        # ADR-8 Phase 2: use _effective_max_iter / _effective_max_wall
        # (agent_config overrides when provided; module-level defaults
        # otherwise) instead of the raw MAX_ITERATIONS / MAX_WALL_CLOCK_SECS.
        for iteration in range(_effective_max_iter):
            trace.iterations_used = iteration + 1

            # ADR-5: hard wall-clock cap. The loop terminates on "done,
            # blocked, OR limit" — this is the time-based limit. Prevents
            # a small model from spinning forever on a task it can't solve.
            _elapsed = time.monotonic() - _loop_start_time
            if _elapsed > _effective_max_wall:
                logger.warning(
                    "[agent_loop] wall-clock cap hit after %.1fs (iter %d/%d) — forcing final answer",
                    _elapsed,
                    iteration + 1,
                    _effective_max_iter,
                )
                if _obs:
                    _obs.emit(
                        "agent_loop_wall_clock_cap",
                        intent=intent.value,
                        elapsed_secs=_elapsed,
                        iteration=iteration + 1,
                    )
                break

            # Build iteration-specific context hint
            failure_hint = ""
            if last_tool_failed and consecutive_failures >= 2:
                failure_hint = (
                    "\nWARNING: Multiple tool failures. Consider providing your "
                    "best answer from existing context instead of retrying."
                )

            # Add an observation summary as the latest user context if we have one
            iteration_messages = list(loop_messages)
            if observation_log:
                # Cap observation log to prevent context overflow on later iterations.
                # Keep the tail (most recent observations) — they're most relevant.
                _OBS_LOG_TOTAL_CAP = OBS_LOG_MAX_CHARS * 2  # 1600 chars
                trimmed_log = observation_log
                if len(observation_log) > _OBS_LOG_TOTAL_CAP:
                    trimmed_log = "…[earlier observations truncated]\n" + observation_log[-_OBS_LOG_TOTAL_CAP:]
                context_content = f"{trimmed_log}{failure_hint}\nIteration {iteration + 1}/{_effective_max_iter}. "
                iteration_messages.append({"role": "user", "content": context_content})

            # ── LLM call with tools ───────────────────────────────────
            # Session 25/31: wrap with a hard timeout to prevent "thinking
            # forever" when the model hangs. Uses PER_CALL_TIMEOUT_SECS
            # (45s) — SHORTER than the adapter's 120s HTTP timeout so the
            # user sees a result before the adapter itself times out.
            # The wall-clock cap (90s total) is checked between iterations.
            t_llm = time.monotonic()
            try:
                result = await asyncio.wait_for(
                    active_adapter.chat_with_tools(
                        messages=iteration_messages,
                        tools=filtered_tools,
                        temperature=0.3,
                        intent=intent.value,
                    ),
                    timeout=PER_CALL_TIMEOUT_SECS,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "[agent_loop] model call timed out after %.0fs (iter %d) — breaking with error",
                    PER_CALL_TIMEOUT_SECS,
                    iteration + 1,
                )
                if _obs:
                    _obs.emit(
                        "agent_loop_model_timeout",
                        intent=intent.value,
                        timeout_secs=PER_CALL_TIMEOUT_SECS,
                        iteration=iteration + 1,
                    )
                yield StreamChunk(
                    text=(
                        f"The model is taking too long to respond "
                        f"(timed out after {int(PER_CALL_TIMEOUT_SECS)}s). "
                        f"The free-tier model may be overloaded. "
                        f"Please try again or switch to a faster model."
                    ),
                    done=False,
                )
                yield StreamChunk(text="", done=True)
                return
            llm_ms = round((time.monotonic() - t_llm) * 1000)
            logger.info(f"[agent.loop] iter={iteration + 1} LLM: {llm_ms}ms")

            # ── Handle MultiToolCallResult (model invoked multiple tools) ──
            # When the model returns multiple tool calls in a single response,
            # dispatch independent ones concurrently via asyncio.gather().
            # This is safe because independent tool calls (e.g., file_task + sysinfo)
            # have no side-effect dependencies between them.
            if isinstance(result, MultiToolCallResult):
                # Emit thinking content from the first call
                if result.raw_content:
                    _filtered_thinking = _filter_system_leaks(result.raw_content[:2000])
                    if _filtered_thinking.strip():
                        yield StreamChunk(text="", done=False, thinking="start")
                        yield StreamChunk(text="", done=False, thinking=_filtered_thinking)
                        yield StreamChunk(text="", done=False, thinking="end")
                    if _obs:
                        _obs.emit(
                            "thinking",
                            text=_filter_system_leaks(result.raw_content[:500]),
                            iteration=iteration + 1,
                        )

                logger.info(
                    f"[agent.loop] iter={iteration + 1} multi_tool_call: "
                    f"{len(result.calls)} tools — {[c.tool_name for c in result.calls]}"
                )

                # Validate and filter: separate valid from rejected calls
                valid_calls: list[tuple[ToolCallResult, str]] = []  # (call, tool_input)
                for call in result.calls:
                    _name = call.tool_name
                    _args = call.tool_args
                    _inp = _extract_tool_input(_name, _args)

                    # Apply same validations as single-tool path
                    if effective_allowed is not None and _name not in effective_allowed:
                        logger.warning(f"[agent.loop] parallel: rejected tool {_name!r} by explicit policy")
                        continue
                    if _name not in AGENT_ALLOWED_TOOLS:
                        logger.warning(f"[agent.loop] parallel: rejected tool {_name!r}")
                        continue
                    if not _inp or len(_inp.strip("?. \t")) < 3:
                        logger.warning(f"[agent.loop] parallel: rejected degenerate input for {_name!r}")
                        continue
                    if _name == "file_write":
                        _p = _args.get("path", "").strip()
                        _c = _args.get("content", "").strip()
                        if not _p or not _c:
                            logger.warning("[agent.loop] parallel: file_write missing args, skipping")
                            continue

                    valid_calls.append((call, _inp))

                if not valid_calls:
                    # All calls were rejected — fall through to next iteration
                    last_tool_failed = True
                    consecutive_failures += 1
                    observation_log += "\n[All parallel tool calls rejected]\n"
                    continue

                # Dispatch all valid calls concurrently
                async def _dispatch_single(tc_name: str, tc_input: str, tc_args: dict):
                    """Dispatch a single tool and return (name, observation, failed, latency_ms, result)."""
                    t_start = time.monotonic()
                    tc_result = None
                    try:
                        tc_intent = Intent(tc_name)
                        tc_result, tc_failed, _ = await dispatch_with_retry(
                            tc_intent,
                            tc_input,
                            allowed_tool_names=effective_allowed,
                        )
                        tc_obs = tc_result.content if tc_result else f"[Tool {tc_name} returned no result]"
                        tc_obs = _filter_tool_injection(tc_obs)
                        # Collect result for post-loop synthesis
                        if tc_result:
                            collected_results.append(tc_result)
                        # Bridge diff metadata from edit_file tool results.
                        # When edit_file produces structured diff hunks, emit a
                        # file_diff obs event so the frontend DiffBlock can render
                        # green/red highlighted diffs — like Cursor/Claude.
                        if tc_result and tc_result.metadata and tc_result.source == "edit_file":
                            diff_hunks = tc_result.metadata.get("diff_hunks", [])
                            if diff_hunks and _obs:
                                _obs.emit(
                                    "file_diff",
                                    diff_hunks=diff_hunks,
                                    diff_language=tc_result.metadata.get("diff_language", ""),
                                    path=tc_result.metadata.get("path", ""),
                                    diff_additions=tc_result.metadata.get("diff_additions", 0),
                                    diff_deletions=tc_result.metadata.get("diff_deletions", 0),
                                )
                    except Exception as e:
                        tc_obs = f"[Tool {tc_name} error: {e}]"
                        tc_failed = True
                    tc_lat = round((time.monotonic() - t_start) * 1000)
                    return tc_name, tc_obs, tc_failed, tc_lat

                # Build labels for each tool call
                for call, _inp in valid_calls:
                    _path = call.tool_args.get("path", "")
                    _command = call.tool_args.get("command", "")
                    _query = call.tool_args.get("query", "")
                    _code_preview = call.tool_args.get("code", "")[:40]
                    _label_map = {
                        "file_write": f"Creating file: {_path[:80]}" if _path else "Creating file",
                        "edit_file": f"Editing file: {_path[:80]}" if _path else "Editing file",
                        "code_exec": f"Executing: {_code_preview}..." if _code_preview else "Executing code",
                        "web_search": f"Searching: {_query[:80]}" if _query else "Searching the web",
                        "web_fetch": f"Fetching: {call.tool_args.get('url', '')[:80]}"
                        if call.tool_args.get("url")
                        else "Fetching web page",
                        "file_task": f"Reading: {_path[:80]}" if _path else "Reading file",
                        "shell": f"Running: {_command[:80]}" if _command else "Running command",
                        "memory_op": f"Memory: {call.tool_args.get('operation', '')} {call.tool_args.get('content', '')[:40]}".strip(),
                        "sysinfo": f"System info: {_query[:60]}" if _query else "Getting system info",
                        "git": f"Git: {call.tool_args.get('operation', '')}" if call.tool_args.get('operation') else "Git operation",
                        "process": f"Process: {call.tool_args.get('operation', '')} {call.tool_args.get('name', '')}" if call.tool_args.get('operation') else "Process operation",
                        "diagnostics": f"Diagnostics: {call.tool_args.get('operation', '')}" if call.tool_args.get('operation') else "Analyzing failure",
                        "browse": f"Browser: {call.tool_args.get('action', '')}" if call.tool_args.get('action') else "Using browser",
                    }
                    _label = _label_map.get(call.tool_name, f"Running {call.tool_name}")
                    yield StreamChunk(text="", done=False, status=_label)
                    if _obs:
                        _obs.emit(
                            "tool_call",
                            tool=call.tool_name,
                            label=_label,
                            status="started",
                            iteration=iteration + 1,
                        )

                # Run all dispatches concurrently
                dispatch_tasks = [_dispatch_single(call.tool_name, inp, call.tool_args) for call, inp in valid_calls]
                dispatch_results = await asyncio.gather(*dispatch_tasks)

                # Process all results and add to conversation context
                any_failed = False
                tool_messages: list[dict] = []
                for tc_name, tc_obs, tc_failed, tc_lat in dispatch_results:
                    observation_log += (
                        f"\n[Tool: {tc_name} | Status: {'FAILED' if tc_failed else 'OK'} | Latency: {tc_lat}ms]\n"
                        f"{_truncate_observation(tc_obs)}\n"
                    )
                    trace.steps.append(
                        AgentStep(
                            iteration=iteration + 1,
                            thought=result.raw_content or "",
                            tool_name=tc_name,
                            tool_input="",  # individual inputs not tracked in parallel
                            observation=_truncate_observation(tc_obs),
                            tool_failed=tc_failed,
                            retry_count=0,
                            latency_ms=tc_lat,
                        )
                    )
                    if _obs:
                        _obs.emit(
                            "tool_call",
                            tool=tc_name,
                            label="",
                            status="done",
                            iteration=iteration + 1,
                        )
                    if tc_failed:
                        any_failed = True

                    # Add tool result to context as proper tool messages
                    call_id = str(uuid.uuid4())
                    tool_messages.append(
                        {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": call_id,
                                    "type": "function",
                                    "function": {
                                        "name": tc_name,
                                        "arguments": "{}",
                                    },
                                }
                            ],
                        }
                    )
                    tool_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": _truncate_observation(tc_obs),
                        }
                    )

                loop_messages.extend(tool_messages)

                if any_failed:
                    last_tool_failed = True
                    consecutive_failures += 1
                    fabrication_risk += 1  # Parallel tool failures increase fabrication risk
                    if _obs:
                        _obs.emit(
                            "fabrication_risk",
                            risk=fabrication_risk,
                            tool="multi",
                            iteration=iteration + 1,
                        )
                else:
                    last_tool_failed = False
                    consecutive_failures = 0

                continue

            # ── Handle ToolCallResult (model chose to use a tool) ─────
            if isinstance(result, ToolCallResult):
                tool_name = result.tool_name
                tool_args = result.tool_args
                tool_input = _extract_tool_input(tool_name, tool_args)

                # Debug: log description from LLM
                logger.info(f"[agent.loop] tool_args description: {tool_args.get('description', 'NONE')}")

                # FIX: Yield thinking content as proper SSE events so the
                # frontend ThinkingBlock shows the model's reasoning in real-time.
                # Previously, raw_content was only emitted to obs (invisible to
                # the frontend). Now we emit thinking_start → thinking_token →
                # thinking_end as structured SSE events that the frontend can
                # consume directly.
                # ANTI-FABRICATION: Filter MiniMax proprietary tool_call text
                # from the thinking content — it should never be user-visible.
                if result.raw_content:
                    _filtered_thinking = _filter_system_leaks(result.raw_content[:2000])
                    if _filtered_thinking.strip():
                        yield StreamChunk(text="", done=False, thinking="start")
                        yield StreamChunk(text="", done=False, thinking=_filtered_thinking)
                        yield StreamChunk(text="", done=False, thinking="end")
                    if _obs:
                        _obs.emit(
                            "thinking",
                            text=_filter_system_leaks(result.raw_content[:500]),
                            iteration=iteration + 1,
                        )

                logger.info(
                    f"[agent.loop] iter={iteration + 1} tool_call={tool_name} args={json.dumps(tool_args)[:120]}"
                )

                # Guard: reject tool names outside the explicit objective policy.
                if effective_allowed is not None and tool_name not in effective_allowed:
                    allowed_list = ", ".join(sorted(effective_allowed))
                    observation = f"[Tool '{tool_name}' is not available in this objective policy. Allowed tools: {allowed_list}]"
                    logger.warning(f"[agent.loop] rejected tool name by explicit policy: {tool_name!r}")
                    last_tool_failed = True
                    consecutive_failures += 1
                    observation_log += f"\n[Tool: {tool_name} | Status: BLOCKED (policy)]\n{observation}\n"
                    continue

                if tool_name not in AGENT_ALLOWED_TOOLS:
                    allowed_list = ", ".join(sorted(AGENT_ALLOWED_TOOLS))
                    observation = f"[Tool '{tool_name}' is not available. Available tools: {allowed_list}]"
                    logger.warning(f"[agent.loop] rejected tool name: {tool_name!r}")
                    last_tool_failed = True
                    consecutive_failures += 1
                    observation_log += f"\n[Tool: {tool_name} | Status: BLOCKED (not in allowlist)]\n{observation}\n"
                    trace.steps.append(
                        AgentStep(
                            iteration=iteration + 1,
                            thought=result.raw_content or "",
                            tool_name=tool_name,
                            tool_input=tool_input,
                            observation=observation,
                            tool_failed=True,
                            retry_count=0,
                            latency_ms=llm_ms,
                        )
                    )
                    # Add the failed tool call + result to conversation context
                    # so the model can see its mistake and correct itself.
                    call_id = str(uuid.uuid4())
                    loop_messages.append(
                        {
                            "role": "assistant",
                            "content": result.raw_content or "",
                            "tool_calls": [
                                {
                                    "id": call_id,
                                    "type": "function",
                                    "function": {
                                        "name": tool_name,
                                        "arguments": json.dumps(tool_args),
                                    },
                                }
                            ],
                        }
                    )
                    loop_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": observation,
                        }
                    )
                    continue

                # ── Validate required args before dispatch ──────────────────
                # Reject tool calls missing required parameters (e.g. file_write
                # without 'path' or 'content'). This gives the model a clear
                # error message so it can self-correct instead of dispatching
                # a doomed tool call that wastes an iteration.
                if tool_name == "file_write":
                    _fw_path = tool_args.get("path", "").strip()
                    _fw_content = tool_args.get("content", "").strip()
                    if not _fw_path or not _fw_content:
                        observation = (
                            f"[file_write REJECTED: missing required args. "
                            f"You MUST provide both 'path' (got: {_fw_path!r}) and "
                            f"'content' (got: {_fw_content[:50]!r}...). "
                            f"Call file_write again with BOTH arguments filled in.]"
                        )
                        logger.warning(
                            f"[agent.loop] file_write missing required args: "
                            f"path={_fw_path!r}, content_len={len(_fw_content)}"
                        )
                        last_tool_failed = True
                        consecutive_failures += 1
                        observation_log += (
                            f"\n[Tool: {tool_name} | Status: REJECTED (missing required args)]\n{observation}\n"
                        )
                        trace.steps.append(
                            AgentStep(
                                iteration=iteration + 1,
                                thought=result.raw_content or "",
                                tool_name=tool_name,
                                tool_input=tool_input,
                                observation=observation,
                                tool_failed=True,
                                retry_count=0,
                                latency_ms=llm_ms,
                            )
                        )
                        call_id = str(uuid.uuid4())
                        loop_messages.append(
                            {
                                "role": "assistant",
                                "content": result.raw_content or "",
                                "tool_calls": [
                                    {
                                        "id": call_id,
                                        "type": "function",
                                        "function": {
                                            "name": tool_name,
                                            "arguments": json.dumps(tool_args),
                                        },
                                    }
                                ],
                            }
                        )
                        loop_messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call_id,
                                "content": observation,
                            }
                        )
                        continue

                # Semantic validation: reject empty or degenerate inputs
                if not tool_input or len(tool_input.strip("?. \t")) < 3:
                    observation = (
                        f"[Action rejected: input for '{tool_name}' is empty or too short. "
                        f"Provide a specific, meaningful input and try again.]"
                    )
                    logger.warning(f"[agent.loop] rejected degenerate input for tool={tool_name!r}: {tool_input!r}")
                    last_tool_failed = True
                    consecutive_failures += 1
                    observation_log += f"\n[Tool: {tool_name} | Status: REJECTED (bad input)]\n{observation}\n"
                    trace.steps.append(
                        AgentStep(
                            iteration=iteration + 1,
                            thought=result.raw_content or "",
                            tool_name=tool_name,
                            tool_input=tool_input,
                            observation=observation,
                            tool_failed=True,
                            retry_count=0,
                            latency_ms=llm_ms,
                        )
                    )
                    call_id = str(uuid.uuid4())
                    loop_messages.append(
                        {
                            "role": "assistant",
                            "content": result.raw_content or "",
                            "tool_calls": [
                                {
                                    "id": call_id,
                                    "type": "function",
                                    "function": {
                                        "name": tool_name,
                                        "arguments": json.dumps(tool_args),
                                    },
                                }
                            ],
                        }
                    )
                    loop_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": observation,
                        }
                    )
                    continue

                # Deduplication: skip a tool call we've already made this turn
                call_fingerprint = (tool_name, tool_input.lower().strip())
                if call_fingerprint in _call_cache:
                    cached_obs = _call_cache[call_fingerprint]
                    logger.info(f"[agent.loop] dedup hit for tool={tool_name!r} — returning cached result")
                    observation_log += (
                        f"\n[Tool: {tool_name} | Input: {tool_input[:60]} | Status: CACHED]\n"
                        f"{_truncate_observation(cached_obs)}\n"
                    )
                    trace.steps.append(
                        AgentStep(
                            iteration=iteration + 1,
                            thought=result.raw_content or "",
                            tool_name=tool_name,
                            tool_input=tool_input,
                            observation=f"[cached] {cached_obs[:200]}",
                            tool_failed=False,
                            retry_count=0,
                            latency_ms=llm_ms,
                        )
                    )
                    # Add cached result as tool message
                    call_id = str(uuid.uuid4())
                    loop_messages.append(
                        {
                            "role": "assistant",
                            "content": result.raw_content or "",
                            "tool_calls": [
                                {
                                    "id": call_id,
                                    "type": "function",
                                    "function": {
                                        "name": tool_name,
                                        "arguments": json.dumps(tool_args),
                                    },
                                }
                            ],
                        }
                    )
                    loop_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": cached_obs,
                        }
                    )
                    continue

                # ── Bug B fix: name-level dedup for file_write ──────────
                # If the agent already called file_write for a given path
                # in this turn, reject the duplicate. This prevents double
                # writes where the model calls file_write, sees the result,
                # then calls file_write again on the same path with slightly
                # different content (often due to retrying or re-planning).
                if tool_name == "file_write":
                    _write_path = tool_args.get("path", "").strip().lower()
                    if _write_path and _write_path in _file_write_paths:
                        logger.info(
                            f"[agent.loop] name-level dedup: file_write already "
                            f"called for path={_write_path!r} — returning cached result"
                        )
                        # Use the cached observation if available, otherwise
                        # tell the model it already wrote this file
                        _path_key = (tool_name, tool_input.lower().strip())
                        cached_write_obs = _call_cache.get(
                            _path_key,
                            f"[file_write already executed for '{tool_args.get('path', '')}' "
                            f"in this turn. Do not write the same file again.]",
                        )
                        observation_log += (
                            f"\n[Tool: {tool_name} | Path: {_write_path} | Status: CACHED (name-level dedup)]\n"
                            f"{_truncate_observation(cached_write_obs)}\n"
                        )
                        trace.steps.append(
                            AgentStep(
                                iteration=iteration + 1,
                                thought=result.raw_content or "",
                                tool_name=tool_name,
                                tool_input=tool_input,
                                observation=f"[name-dedup] {cached_write_obs[:200]}",
                                tool_failed=False,
                                retry_count=0,
                                latency_ms=llm_ms,
                            )
                        )
                        call_id = str(uuid.uuid4())
                        loop_messages.append(
                            {
                                "role": "assistant",
                                "content": result.raw_content or "",
                                "tool_calls": [
                                    {
                                        "id": call_id,
                                        "type": "function",
                                        "function": {
                                            "name": tool_name,
                                            "arguments": json.dumps(tool_args),
                                        },
                                    }
                                ],
                            }
                        )
                        loop_messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call_id,
                                "content": cached_write_obs,
                            }
                        )
                        continue

                # ── Dispatch the tool ──────────────────────────────────
                # Use LLM-provided description from tool_args, fallback to
                # structured label built from tool_args fields (path, command,
                # query) — NOT from raw concatenated tool_input which may be
                # empty or malformed when the model sends incomplete args.
                logger.info(f"[agent.loop] full tool_args: {tool_args}")
                action_label = tool_args.get("description")
                logger.info(f"[agent.loop] description from LLM: {action_label}")
                if not action_label:
                    # Build label from structured tool_args, not raw tool_input.
                    # This prevents empty labels like "Creating file: :" when
                    # the model sends empty args — we extract the actual path,
                    # command, or query from the args dict instead.
                    _path = tool_args.get("path", "")
                    _command = tool_args.get("command", "")
                    _query = tool_args.get("query", "")
                    _code_preview = tool_args.get("code", "")[:40]
                    action_labels = {
                        "file_write": f"Creating file: {_path[:80]}" if _path else "Creating file",
                        "edit_file": f"Editing file: {_path[:80]}" if _path else "Editing file",
                        "code_exec": f"Executing: {_code_preview}..." if _code_preview else "Executing code",
                        "web_search": f"Searching: {_query[:80]}" if _query else "Searching the web",
                        "file_task": f"Reading: {_path[:80]}" if _path else "Reading file",
                        "shell": f"Running: {_command[:80]}" if _command else "Running command",
                        "memory_op": f"Memory: {tool_args.get('operation', '')} {tool_args.get('content', '')[:40]}".strip(),
                        "sysinfo": f"System info: {_query[:60]}" if _query else "Getting system info",
                        "git": f"Git: {tool_args.get('operation', '')}" if tool_args.get('operation') else "Git operation",
                        "process": f"Process: {tool_args.get('operation', '')} {tool_args.get('name', '')}" if tool_args.get('operation') else "Process operation",
                        "diagnostics": f"Diagnostics: {tool_args.get('operation', '')}" if tool_args.get('operation') else "Analyzing failure",
                        "browse": f"Browser: {tool_args.get('action', '')}" if tool_args.get('action') else "Using browser",
                    }
                    action_label = action_labels.get(tool_name, f"Running {tool_name}")
                logger.info(
                    f"[agent.loop] iter={iteration + 1} tool={tool_name} input={tool_input[:80]} — {action_label}"
                )
                if _obs:
                    _obs.emit(
                        "tool_call",
                        tool=tool_name,
                        label=action_label,
                        status="started",
                        iteration=iteration + 1,
                    )

                # ── Yield intermediate status to the user so they see real-time ──
                # feedback during tool execution. Without this, the user sees only
                # "Generating response..." until the entire tool call cycle completes.
                # v0.10: Use status field for the thinking area, text field for
                # minimal inline feedback. The status shows in the ThinkingBlock
                # component, while the text appears briefly before the final answer.
                yield StreamChunk(text="", done=False, status=action_label)

                t_tool = time.monotonic()
                tool_failed = False
                retry_count = 0
                observation = ""

                try:
                    tool_intent = Intent(tool_name)

                    # ── file_write: validate and use typed contract ──────────
                    # Guard: if the model calls file_write without a meaningful
                    # content arg (e.g. placeholder like "read", "code", "yes"),
                    # REJECT the call so the model can self-correct.
                    # Previously this redirected to file_task (read), but that
                    # caused "not_found" errors when the file didn't exist yet
                    # (the user wanted to CREATE it, not READ it).
                    if tool_name == "file_write":
                        _content = tool_args.get("content", "")
                        _path = tool_args.get("path", "")
                        if not _content or len(_content.strip()) < 5:
                            logger.info(
                                f"[agent.loop] file_write called without meaningful content "
                                f"(path={_path!r}, content={_content.strip()[:20]!r}) — rejecting"
                            )
                            observation = (
                                f"[file_write REJECTED: content is too short "
                                f"({len(_content.strip())} chars: {_content.strip()[:30]!r}). "
                                f"You MUST provide the actual file content, not a placeholder. "
                                f"Call file_write again with meaningful content in the 'content' field.]"
                            )
                            last_tool_failed = True
                            consecutive_failures += 1
                            observation_log += (
                                f"\n[Tool: {tool_name} | Status: REJECTED (content too short)]\n{observation}\n"
                            )
                            trace.steps.append(
                                AgentStep(
                                    iteration=iteration + 1,
                                    thought=result.raw_content or "",
                                    tool_name=tool_name,
                                    tool_input=tool_input,
                                    observation=observation,
                                    tool_failed=True,
                                    retry_count=0,
                                    latency_ms=llm_ms,
                                )
                            )
                            call_id = str(uuid.uuid4())
                            loop_messages.append(
                                {
                                    "role": "assistant",
                                    "content": result.raw_content or "",
                                    "tool_calls": [
                                        {
                                            "id": call_id,
                                            "type": "function",
                                            "function": {
                                                "name": tool_name,
                                                "arguments": json.dumps(tool_args),
                                            },
                                        }
                                    ],
                                }
                            )
                            loop_messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": call_id,
                                    "content": observation,
                                }
                            )
                            continue

                    if tool_name == "file_write":
                        try:
                            from tools.contracts.base import ToolRegistry

                            contract_cls = ToolRegistry.get("file_write")
                            file_payload = {
                                "path": tool_args.get("path", ""),
                                "content": tool_args.get("content", ""),
                            }
                            tool_result = await contract_cls().execute(file_payload)
                            tool_failed = not tool_result.success if tool_result else True
                            retry_count = 0
                        except KeyError:
                            # Contract not registered — fall back to legacy dispatch
                            logger.warning("[agent.loop] FileWriteContract not in registry, using legacy dispatch")
                            tool_result, tool_failed, retry_count = await dispatch_with_retry(
                                tool_intent,
                                tool_input,
                                allowed_tool_names=effective_allowed,
                            )

                    elif tool_name == "edit_file":
                        # edit_file: use typed contract path (like file_write)
                        try:
                            from tools.contracts.base import ToolRegistry

                            contract_cls = ToolRegistry.get("edit_file")
                            edit_payload = dict(tool_args)  # pass all args as payload
                            tool_result = await contract_cls().execute(edit_payload)
                            tool_failed = not tool_result.success if tool_result else True
                            retry_count = 0
                        except KeyError:
                            # Contract not registered — fall back to legacy dispatch
                            logger.warning("[agent.loop] EditFileContract not in registry, using legacy dispatch")
                            tool_result, tool_failed, retry_count = await dispatch_with_retry(
                                tool_intent,
                                tool_input,
                                allowed_tool_names=effective_allowed,
                            )

                        # Bridge diff metadata from edit_file tool results.
                        # Emit a file_diff obs event so the frontend DiffBlock can
                        # render green/red highlighted diffs — like Cursor/Claude.
                        if tool_result and tool_result.metadata and tool_result.source == "edit_file":
                            diff_hunks = tool_result.metadata.get("diff_hunks", [])
                            if diff_hunks and _obs:
                                _obs.emit(
                                    "file_diff",
                                    diff_hunks=diff_hunks,
                                    diff_language=tool_result.metadata.get("diff_language", ""),
                                    path=tool_result.metadata.get("path", ""),
                                    diff_additions=tool_result.metadata.get("diff_additions", 0),
                                    diff_deletions=tool_result.metadata.get("diff_deletions", 0),
                                )

                    else:
                        tool_result, tool_failed, retry_count = await dispatch_with_retry(
                            tool_intent,
                            tool_input,
                            adapter=active_adapter,
                            allowed_tool_names=effective_allowed,
                        )

                    latency_ms = round((time.monotonic() - t_tool) * 1000)

                    if tool_result:
                        if tool_intent == Intent.CODE_EXEC:
                            safe_obs = _filter_code_output(tool_result.content)
                        else:
                            safe_obs = _filter_tool_injection(tool_result.content)

                        # Prepend structured error context
                        if not tool_result.success and tool_result.error_type:
                            safe_obs = (
                                f"[Tool '{tool_name}' returned error_type={tool_result.error_type!r}]\n" + safe_obs
                            )

                        # Web-search: synthesize results into a user-facing answer.
                        if tool_intent == Intent.WEB_SEARCH:
                            # Extract original user question from messages for synthesis
                            _user_q = ""
                            for m in messages:
                                if m.get("role") == "user":
                                    _user_q = m.get("content", "")
                                    break
                            async for chunk in self._handle_web_search_result(
                                safe_obs=safe_obs,
                                query=tool_input,
                                thought=result.raw_content or "",
                                iteration=iteration,
                                trace=trace,
                                user_question=_user_q,
                                adapter=active_adapter,
                                allowed_tool_names=effective_allowed,
                            ):
                                yield chunk
                            if _obs:
                                _obs.emit(
                                    "tool_call",
                                    tool=tool_name,
                                    label=action_label,
                                    status="done",
                                    latency_ms=latency_ms,
                                    iteration=iteration + 1,
                                )
                                _obs.emit("agent_loop_done", intent=intent.value, iterations=iteration + 1)
                            return  # web search is always terminal in agent loop

                        observation = safe_obs
                        _call_cache[call_fingerprint] = safe_obs

                        # Bug B fix: track file_write paths for name-level dedup
                        if tool_name == "file_write":
                            _written_path = tool_args.get("path", "").strip().lower()
                            if _written_path:
                                _file_write_paths.add(_written_path)

                        # ── Post-execution verification ───────────────────────
                        # After certain tool executions, verify the result to catch
                        # silent failures and give the model feedback for self-correction.
                        if VERIFY_ENABLED and not tool_failed:
                            verify_obs = await self._verify_tool_result(
                                tool_name=tool_name,
                                tool_args=tool_args,
                                observation=safe_obs,
                                allowed_tool_names=effective_allowed,
                            )
                            if verify_obs:
                                observation += f"\n[VERIFICATION]: {verify_obs}"
                                trace.verification_results.append(verify_obs)

                        # ── Grounding verification ───────────────────────────────
                        # After successful file_write, emit a grounding_check obs event
                        # with the result of reading the file back. This makes the
                        # verification observable to the frontend and creates an
                        # explicit audit trail for the grounding check.
                        if tool_name == "file_write" and not tool_failed:
                            _grounding_path = tool_args.get("path", "")
                            if _grounding_path and _obs:
                                try:
                                    # NOTE: dispatch_with_retry is imported at module level (line 177).
                                    # Do NOT re-import it here — that would shadow the module-level
                                    # binding and cause UnboundLocalError in closures like
                                    # _dispatch_single() and _write_files().
                                    (
                                        _grounding_result,
                                        _grounding_failed,
                                        _,
                                    ) = await dispatch_with_retry(
                                        Intent.FILE_TASK,
                                        _grounding_path,
                                        max_retries=0,
                                        allowed_tool_names=effective_allowed,
                                    )
                                    _grounding_ok = (
                                        not _grounding_failed and _grounding_result and _grounding_result.success
                                    )
                                    _grounding_content_len = (
                                        len(_grounding_result.content)
                                        if _grounding_result and _grounding_result.content
                                        else 0
                                    )
                                    _obs.emit(
                                        "grounding_check",
                                        tool="file_write",
                                        path=_grounding_path,
                                        verified=_grounding_ok,
                                        content_length=_grounding_content_len,
                                        iteration=iteration + 1,
                                    )
                                    if not _grounding_ok:
                                        observation += (
                                            f"\n[GROUNDING CHECK FAILED]: file_write for '{_grounding_path}' "
                                            f"could not be verified — the file may not exist or may be empty. "
                                            f"Do NOT claim the file was created successfully."
                                        )
                                        fabrication_risk += 1
                                        logger.warning(
                                            f"[agent.loop] grounding check FAILED for file_write: "
                                            f"path={_grounding_path!r}"
                                        )
                                except Exception as _ge:
                                    logger.warning(f"[agent.loop] grounding check error (non-fatal): {_ge}")

                        # ── Terminal bridge: emit tool output to the terminal panel ──
                        # Forward ALL tool executions to the terminal panel so the user
                        # sees what the AI is doing in real-time. Shell/code_exec show
                        # as command+output. Other tools (file_task, file_write, etc.)
                        # show as labeled operations with their results.
                        if _obs:
                            _term_command = tool_input
                            _term_output = safe_obs
                            _term_success = not tool_failed
                            # Generate a descriptive label for non-shell tools
                            _term_label = action_label
                            _obs.emit(
                                "terminal_output",
                                tool=tool_name,
                                command=_term_command,
                                output=_term_output[:5000],
                                success=str(_term_success),
                                latency_ms=str(latency_ms),
                                label=str(_term_label),
                                tool_args=json.dumps(tool_args)[:500] if tool_args else "",
                            )

                        last_tool_failed = False
                        consecutive_failures = 0

                        # Yield completion status so user sees the tool finished
                        if not tool_failed:
                            yield StreamChunk(
                                text="",
                                done=False,
                                status=f"Done — {action_label} ({latency_ms}ms)",
                            )

                            # Mark the corresponding plan todo as complete.
                            # Each successful tool execution advances the cursor
                            # so the Todos panel shows progress through the plan.
                            if _plan_steps and _plan_step_cursor < len(_plan_steps) and _obs:
                                _obs.emit("todo_completed", id=f"plan-{_plan_step_cursor}", completed=True)
                                _plan_step_cursor += 1

                        if retry_count > 0:
                            yield StreamChunk(
                                text=f"*(succeeded after {retry_count} retr{'y' if retry_count == 1 else 'ies'})*\n",
                                done=False,
                            )
                    else:
                        observation = f"[Tool '{tool_name}' returned no result after {retry_count} retries]"
                        tool_failed = True
                        latency_ms = round((time.monotonic() - t_tool) * 1000)

                except (ValueError, Exception) as exc:
                    observation = f"[Tool '{tool_name}' failed: {exc}]"
                    tool_failed = True
                    retry_count = 0
                    latency_ms = round((time.monotonic() - t_tool) * 1000)

                if tool_failed:
                    last_tool_failed = True
                    consecutive_failures += 1
                    fabrication_risk += 1  # Tool errors increase fabrication risk
                    if _obs:
                        _obs.emit(
                            "tool_call",
                            tool=tool_name,
                            label=action_label,
                            status="failed",
                            latency_ms=latency_ms,
                            iteration=iteration + 1,
                        )
                        _obs.emit(
                            "fabrication_risk",
                            risk=fabrication_risk,
                            tool=tool_name,
                            iteration=iteration + 1,
                        )
                else:
                    if _obs:
                        _obs.emit(
                            "tool_call",
                            tool=tool_name,
                            label=action_label,
                            status="done",
                            latency_ms=latency_ms,
                            iteration=iteration + 1,
                        )

                trace.steps.append(
                    AgentStep(
                        iteration=iteration + 1,
                        thought=result.raw_content or "",
                        tool_name=tool_name,
                        tool_input=tool_input,
                        observation=observation[:500],
                        tool_failed=tool_failed,
                        retry_count=retry_count,
                        latency_ms=latency_ms,
                    )
                )
                # ANTI-FABRICATION: Only append to observation_log for FAILED
                # tool calls. For successful calls, the tool messages below
                # ARE the observation — adding to observation_log too causes
                # dual injection (the same data appears in both a "user" role
                # message via observation_log AND as a "tool" role message),
                # which wastes context tokens and can cause the model to
                # truncate earlier critical context, leading to fabrication.
                if tool_failed:
                    observation_log += (
                        f"\n[Tool: {tool_name} | Input: {tool_input[:60]} | "
                        f"Status: FAILED | {latency_ms}ms]\n"
                        f"{_truncate_observation(observation)}\n"
                    )

                # Add the tool call + result to conversation context
                # so the model can reason about what happened and decide next.
                # ANTI-FABRICATION: Prepend a strong instruction to the tool
                # result telling the model to use ONLY the actual output.
                call_id = str(uuid.uuid4())
                loop_messages.append(
                    {
                        "role": "assistant",
                        "content": result.raw_content or "",
                        "tool_calls": [
                            {
                                "id": call_id,
                                "type": "function",
                                "function": {
                                    "name": tool_name,
                                    "arguments": json.dumps(tool_args),
                                },
                            }
                        ],
                    }
                )
                # Anti-fabrication wrapper: the model MUST base its response
                # on the actual tool output. Without this, models (especially
                # smaller ones like MiniMax M2.5) sometimes ignore the tool
                # result and fabricate plausible-looking but false data.
                if not tool_failed and observation:
                    safe_observation = (
                        f"[ACTUAL TOOL OUTPUT — use ONLY this data in your response]\n"
                        f"{observation}\n"
                        f"[END TOOL OUTPUT — do NOT invent or add items not shown above]"
                    )
                else:
                    safe_observation = observation
                loop_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": safe_observation,
                    }
                )

                # Continue the loop — the model will see the tool result
                # and decide whether to use another tool or answer directly.
                continue

            # ── Handle streaming text (model chose NOT to use tools) ───
            # This is the final answer — OR the model emitted tool-call XML
            # as text content instead of using the structured tool_calls API.
            # We stream it incrementally for real-time feedback, with:
            # 1. Early MiniMax tool-call XML interception (execute the tool!)
            # 2. Tool-talk detection (model narrating intent instead of calling)
            # 3. Fabrication detection (text answer without any tool calls)
            else:
                # ── Phase 0: Buffer enough text for MiniMax tool-call detection ──
                # MiniMax M2.5 outputs <invoke name="web_search">...</invoke> as
                # TEXT content, not structured tool_calls. We need to buffer enough
                # text to detect this pattern before streaming to the user.
                # If we detect a tool call in the text, we intercept it, execute
                # the tool, and feed the result back into the loop.
                #
                # v0.10: Increased buffer from 800 to 2000 chars. MiniMax M2.5
                # sometimes outputs a long text prefix (e.g. "Let me search for
                # the weather in Cheptais. I'll use the web search tool.") BEFORE
                # the <invoke> XML, which can be 200-500+ chars. The old 800-char
                # limit meant the buffer could fill up with prefix text before the
                # XML arrived, causing us to miss the tool call entirely. Now we
                # also check incrementally — if we see "minimax:tool_call" or
                # "<invoke" appearing mid-buffer, we keep reading.
                _MINIMAX_CHECK_CHARS = 2000
                _MINIMAX_MAX_BUFFER = 4000  # hard cap to prevent infinite buffering
                _minimax_buffer = ""
                _minimax_chunks: list[StreamChunk] = []
                _minimax_stream_ended = False
                _minimax_error = False
                _minimax_partial_seen = False  # track if we've seen start of XML

                async for chunk in result:
                    filtered_text = _filter_system_leaks(chunk.text)
                    _minimax_buffer += filtered_text
                    _minimax_chunks.append(StreamChunk(text=filtered_text, done=chunk.done))
                    if chunk.error:
                        _minimax_error = True
                    if chunk.done:
                        _minimax_stream_ended = True
                        break
                    # Check if we're seeing the START of a tool call XML.
                    # If so, keep reading even past the normal limit.
                    if _has_minimax_tool_call(_minimax_buffer):
                        # Complete tool call found — stop buffering
                        break
                    if _MINIMAX_PARTIAL_RE.search(_minimax_buffer) or _STANDALONE_PARTIAL_RE.search(_minimax_buffer):
                        _minimax_partial_seen = True
                    if len(_minimax_buffer) >= _MINIMAX_CHECK_CHARS:
                        if _minimax_partial_seen:
                            # We're mid-tool-call — keep reading up to max buffer
                            if len(_minimax_buffer) >= _MINIMAX_MAX_BUFFER:
                                break
                            continue
                        # No sign of tool call — check one more time then break
                        break

                # ── Check for MiniMax tool-call XML in the buffered text ──
                _minimax_calls = _parse_minimax_tool_call(_minimax_buffer)

                if _minimax_calls and not _minimax_error:
                    # INTERCEPT: The model output a tool call as text!
                    # Parse it, execute the tool, and feed results back.
                    logger.info(
                        f"[agent.loop] iter={iteration + 1} MINIMAX TOOL CALL INTERCEPTED: "
                        f"{len(_minimax_calls)} call(s) — {[c[0] for c in _minimax_calls]}"
                    )
                    if _obs:
                        _obs.emit(
                            "minimax_tool_call_intercepted",
                            tools=[c[0] for c in _minimax_calls],
                            iteration=iteration + 1,
                        )

                    # Drain remaining chunks from the stream
                    if not _minimax_stream_ended:
                        async for _ in result:
                            pass

                    # Process each intercepted tool call
                    for tc_name, tc_args, tc_raw_xml in _minimax_calls:
                        # Normalize MiniMax parameter names to match our tool definitions
                        # MiniMax uses <parameter name="text"> for the query argument
                        _normalized_args = dict(tc_args)
                        if tc_name == "web_search" and "text" in _normalized_args and "query" not in _normalized_args:
                            _normalized_args["query"] = _normalized_args.pop("text")
                        if tc_name == "web_fetch" and "text" in _normalized_args and "url" not in _normalized_args:
                            _normalized_args["url"] = _normalized_args.pop("text")

                        # Check allowlist
                        if tc_name not in AGENT_ALLOWED_TOOLS:
                            logger.warning(f"[agent.loop] minimax intercept: rejected tool {tc_name!r}")
                            allowed_list = ", ".join(sorted(AGENT_ALLOWED_TOOLS))
                            observation = f"[Tool '{tc_name}' is not available. Available tools: {allowed_list}]"
                            call_id = str(uuid.uuid4())
                            loop_messages.append(
                                {
                                    "role": "assistant",
                                    "content": _strip_minimax_tool_calls(_minimax_buffer),
                                }
                            )
                            loop_messages.append(
                                {
                                    "role": "user",
                                    "content": (
                                        f"You tried to call tool '{tc_name}' but it's not available. "
                                        f"Available tools: {allowed_list}. Try a different approach."
                                    ),
                                }
                            )
                            continue

                        # Extract tool input from normalized args
                        tool_input = _extract_tool_input(tc_name, _normalized_args)

                        if not tool_input or len(tool_input.strip("?. \t")) < 3:
                            logger.warning(
                                f"[agent.loop] minimax intercept: degenerate input for {tc_name!r}: {tool_input!r}"
                            )
                            loop_messages.append(
                                {
                                    "role": "assistant",
                                    "content": _strip_minimax_tool_calls(_minimax_buffer),
                                }
                            )
                            loop_messages.append(
                                {
                                    "role": "user",
                                    "content": (
                                        f"Your tool call for '{tc_name}' had empty or too-short input. "
                                        f"Call it again with a specific, meaningful input."
                                    ),
                                }
                            )
                            continue

                        # Build action label for user feedback
                        _path = _normalized_args.get("path", "")
                        _command = _normalized_args.get("command", "")
                        _query = _normalized_args.get("query", "")
                        _url = _normalized_args.get("url", "")
                        _label_map = {
                            "web_search": f"Searching: {_query[:80]}" if _query else "Searching the web",
                            "web_fetch": f"Fetching: {_url[:80]}" if _url else "Fetching web page",
                            "shell": f"Running: {_command[:80]}" if _command else "Running command",
                            "file_task": f"Reading: {_path[:80]}" if _path else "Reading file",
                            "code_exec": "Executing code",
                            "memory_op": f"Memory: {_normalized_args.get('operation', '')} {_normalized_args.get('content', '')[:40]}".strip(),
                            "sysinfo": f"System info: {_query[:60]}" if _query else "Getting system info",
                        }
                        action_label = _label_map.get(tc_name, f"Running {tc_name}")

                        # Emit status to user — v0.10: use status field
                        yield StreamChunk(text="", done=False, status=action_label)
                        if _obs:
                            _obs.emit(
                                "tool_call",
                                tool=tc_name,
                                label=action_label,
                                status="started",
                                iteration=iteration + 1,
                            )

                        # Dispatch the tool
                        t_tool = time.monotonic()
                        tool_failed = False
                        try:
                            tool_intent = Intent(tc_name)
                            tool_result, tool_failed, retry_count = await dispatch_with_retry(
                                tool_intent,
                                tool_input,
                                adapter=active_adapter,
                                allowed_tool_names=effective_allowed,
                            )
                            latency_ms = round((time.monotonic() - t_tool) * 1000)

                            if tool_result:
                                if tool_intent == Intent.CODE_EXEC:
                                    safe_obs = _filter_code_output(tool_result.content)
                                else:
                                    safe_obs = _filter_tool_injection(tool_result.content)

                                # Prepend structured error context
                                if not tool_result.success and tool_result.error_type:
                                    safe_obs = (
                                        f"[Tool '{tc_name}' returned error_type={tool_result.error_type!r}]\n"
                                        + safe_obs
                                    )

                                # Web-search: synthesize results into a user-facing answer
                                if tool_intent == Intent.WEB_SEARCH:
                                    _user_q = ""
                                    for m in messages:
                                        if m.get("role") == "user":
                                            _user_q = m.get("content", "")
                                            break
                                    async for chunk in self._handle_web_search_result(
                                        safe_obs=safe_obs,
                                        query=tool_input,
                                        thought=_strip_minimax_tool_calls(_minimax_buffer),
                                        iteration=iteration,
                                        trace=trace,
                                        user_question=_user_q,
                                        adapter=active_adapter,
                                        allowed_tool_names=effective_allowed,
                                    ):
                                        yield chunk
                                    if _obs:
                                        _obs.emit(
                                            "tool_call",
                                            tool=tc_name,
                                            label=action_label,
                                            status="done",
                                            latency_ms=latency_ms,
                                            iteration=iteration + 1,
                                        )
                                    return  # web search is terminal

                                observation = safe_obs

                                # Yield completion status
                                if not tool_failed:
                                    yield StreamChunk(
                                        text="",
                                        done=False,
                                        status=f"Done — {action_label} ({latency_ms}ms)",
                                    )

                                # Anti-fabrication wrapper
                                if not tool_failed and observation:
                                    safe_observation = (
                                        f"[ACTUAL TOOL OUTPUT — use ONLY this data in your response]\n"
                                        f"{observation}\n"
                                        f"[END TOOL OUTPUT — do NOT invent or add items not shown above]"
                                    )
                                else:
                                    safe_observation = observation

                                # Add tool call + result to conversation context
                                call_id = str(uuid.uuid4())
                                loop_messages.append(
                                    {
                                        "role": "assistant",
                                        "content": _strip_minimax_tool_calls(_minimax_buffer),
                                        "tool_calls": [
                                            {
                                                "id": call_id,
                                                "type": "function",
                                                "function": {
                                                    "name": tc_name,
                                                    "arguments": json.dumps(_normalized_args),
                                                },
                                            }
                                        ],
                                    }
                                )
                                loop_messages.append(
                                    {
                                        "role": "tool",
                                        "tool_call_id": call_id,
                                        "content": safe_observation,
                                    }
                                )
                                last_tool_failed = False
                                consecutive_failures = 0
                            else:
                                observation = f"[Tool '{tc_name}' returned no result]"
                                tool_failed = True
                                loop_messages.append(
                                    {
                                        "role": "assistant",
                                        "content": _strip_minimax_tool_calls(_minimax_buffer),
                                    }
                                )
                                loop_messages.append(
                                    {
                                        "role": "user",
                                        "content": f"Tool '{tc_name}' returned no result. Try a different approach.",
                                    }
                                )
                                last_tool_failed = True
                                consecutive_failures += 1
                        except (ValueError, Exception) as exc:
                            logger.warning(f"[agent.loop] minimax intercept: tool dispatch failed: {exc}")
                            loop_messages.append(
                                {
                                    "role": "assistant",
                                    "content": _strip_minimax_tool_calls(_minimax_buffer),
                                }
                            )
                            loop_messages.append(
                                {
                                    "role": "user",
                                    "content": f"Tool '{tc_name}' failed: {exc}. Try a different approach.",
                                }
                            )
                            last_tool_failed = True
                            consecutive_failures += 1

                        if _obs:
                            _obs.emit(
                                "tool_call",
                                tool=tc_name,
                                label=action_label,
                                status="done" if not tool_failed else "failed",
                                latency_ms=latency_ms if "latency_ms" in dir() else 0,
                                iteration=iteration + 1,
                            )

                        trace.steps.append(
                            AgentStep(
                                iteration=iteration + 1,
                                thought=_strip_minimax_tool_calls(_minimax_buffer),
                                tool_name=tc_name,
                                tool_input=tool_input[:200],
                                observation=observation[:500] if "observation" in dir() else "",
                                tool_failed=tool_failed if "tool_failed" in dir() else True,
                                retry_count=0,
                                latency_ms=latency_ms if "latency_ms" in dir() else 0,
                            )
                        )

                    # After processing all intercepted tool calls, continue the loop
                    # so the model can reason about the results and produce a final answer
                    continue

                # ── No MiniMax tool calls found — proceed with normal text handling ──
                # Re-use the buffered chunks as the initial_buffer for tool-talk detection
                initial_buffer = _minimax_buffer
                has_error = _minimax_error
                stream_ended_early = _minimax_stream_ended

                # ── Fabrication detection: text response without tool calls ──
                # If the model was supposed to use tools (agent intent, iteration 0)
                # but produced a text response instead, this is a potential fabrication.
                # The model may be describing what it would do instead of actually
                # calling tools. Emit a warning so the observability pipeline can
                # track this pattern.
                if iteration == 0 and intent in AGENT_INTENTS and not trace.steps:
                    fabrication_risk += 1
                    if _obs:
                        _obs.emit(
                            "fabrication_warning",
                            risk=fabrication_risk,
                            reason="model produced text response without tool calls on first iteration",
                            intent=intent.value,
                            iteration=iteration + 1,
                        )
                    logger.warning(
                        f"[agent.loop] fabrication warning: model produced text without "
                        f"tool calls for intent={intent.value} on iter={iteration + 1} "
                        f"(fabrication_risk={fabrication_risk})"
                    )
                # (initial_buffer and initial_chunks already populated by the
                #  MiniMax detection phase above — no need to re-buffer here)

                # Detect errors in the initial buffer
                if has_error or (
                    initial_buffer
                    and any(
                        marker in initial_buffer
                        for marker in [
                            "Ollama returned 5",
                            "Ollama timed out",
                            "Cannot connect to Ollama",
                            "returned 5",
                            "timed out after",
                        ]
                    )
                ):
                    logger.warning(f"[agent.loop] iter={iteration + 1} — error in stream, aborting")
                    if _obs:
                        _obs.emit("agent_loop_error", error=initial_buffer[:120], iteration=iteration + 1)
                    yield StreamChunk(
                        text=(
                            "⚠️ The model ran into an issue. Please try again, "
                            "or switch to a larger model for this task."
                        ),
                        done=True,
                        error=initial_buffer[:200],
                    )
                    # Drain remaining chunks from the stream
                    if not stream_ended_early:
                        async for _ in result:
                            pass
                    return

                # Detect tool-talk in the initial buffer
                if _is_tool_talk(initial_buffer) and trace.tool_talk_recoveries < _MAX_TOOL_TALK_RECOVERIES:
                    trace.tool_talk_recoveries += 1
                    logger.warning(
                        f"[agent.loop] iter={iteration + 1} — tool-talk detected "
                        f"(recovery {trace.tool_talk_recoveries}/{_MAX_TOOL_TALK_RECOVERIES}): "
                        f"{initial_buffer[:120]!r}"
                    )
                    if _obs:
                        _obs.emit(
                            "tool_talk_recovery",
                            iteration=iteration + 1,
                            recovery_num=trace.tool_talk_recoveries,
                            preview=initial_buffer[:80],
                        )
                    # Drain remaining chunks from the stream
                    if not stream_ended_early:
                        async for _ in result:
                            pass
                    # Inject corrective hint and continue without streaming the bad text
                    loop_messages.append(
                        {
                            "role": "assistant",
                            "content": initial_buffer,
                        }
                    )
                    loop_messages.append(
                        {
                            "role": "user",
                            "content": (
                                "You described wanting to use a tool but did not call it. "
                                "You MUST use the tool-calling API directly — do NOT narrate or describe "
                                "your intent. Call the tool now using the function-calling format."
                            ),
                        }
                    )
                    continue  # retry this iteration with the corrective hint

                # ── v0.7: Fabricated data detection (no tool call, no narration) ──
                # The model produced text that looks like real data (scores, weather,
                # prices) but NEVER called a tool. This means it fabricated from
                # training data. For WEB_SEARCH intent, this is the most critical
                # failure mode — the model "knows" the answer from training and
                # outputs it directly, skipping the actual tool call entirely.
                #
                # Pattern: "The current temperature in Cheptais is 22°C..." — no
                # tool was called, this is fabricated.
                _FABRICATED_DATA_PATTERNS = [
                    re.compile(r"\b(temperature|temp)\b.{0,20}\d+°(C|F)", re.IGNORECASE),
                    re.compile(r"\bweather\b.{0,30}\d+°(C|F)", re.IGNORECASE),
                    re.compile(r"\b(score|result)\b.{0,15}\d+\s*[-–]\s*\d+", re.IGNORECASE),
                    re.compile(
                        r"\b(played|vs|versus|against)\b.{0,30}\b(won|lost|drew|beat)\b",
                        re.IGNORECASE,
                    ),
                    re.compile(r"\b(standings|table|rankings?)\b.{0,10}\b(1\.|1st|2nd|3rd)", re.IGNORECASE),
                    re.compile(r"\b(fixture|match|game)\b.{0,20}\b(vs|versus|against)\b", re.IGNORECASE),
                    re.compile(r"\b(price|value|rate)\b.{0,20}[\$€£₹]\d+", re.IGNORECASE),
                    re.compile(r"\b(exchange rate|stock price|crypto|bitcoin|ethereum)\b", re.IGNORECASE),
                ]
                _fabricated_data_detected = any(p.search(initial_buffer) for p in _FABRICATED_DATA_PATTERNS)

                if (
                    _fabricated_data_detected
                    and intent in (Intent.WEB_SEARCH, Intent.WEB_FETCH)
                    and trace.tool_talk_recoveries < _MAX_TOOL_TALK_RECOVERIES + 1
                ):
                    # The model fabricated time-sensitive data from training — this is
                    # the most dangerous hallucination because it looks plausible.
                    # CRITICAL: Drain the stream and force a tool call instead.
                    logger.warning(
                        f"[agent.loop] iter={iteration + 1} — FABRICATED DATA DETECTED "
                        f"for intent={intent.value}: model produced time-sensitive data "
                        f"from training without calling any tool. "
                        f"Preview: {initial_buffer[:120]!r}"
                    )
                    if _obs:
                        _obs.emit(
                            "fabricated_data_intercepted",
                            intent=intent.value,
                            iteration=iteration + 1,
                            preview=initial_buffer[:80],
                        )
                    # Drain remaining chunks from the stream
                    if not stream_ended_early:
                        async for _ in result:
                            pass
                    # Inject corrective hint forcing the model to use the actual tool
                    loop_messages.append(
                        {
                            "role": "assistant",
                            "content": initial_buffer,
                        }
                    )
                    loop_messages.append(
                        {
                            "role": "user",
                            "content": (
                                "CRITICAL: You just output time-sensitive data (weather, scores, prices, etc.) "
                                "from your training knowledge — this data is STALE and likely WRONG. "
                                "You MUST call the web_search tool NOW to get real, current data. "
                                "Do NOT answer from your training data for time-sensitive queries. "
                                "Call web_search with a specific query for the user's request."
                            ),
                        }
                    )
                    fabrication_risk += 2  # Heavy penalty for fabricated data
                    continue  # retry with forced tool call

                # Phase 2: No tool-talk detected — stream the answer
                # incrementally. First yield the initial buffer, then
                # stream remaining chunks directly from the adapter.
                #
                # v0.10: Mid-stream MiniMax detection. Sometimes MiniMax outputs
                # the tool-call XML AFTER the initial buffer check (e.g., it emits
                # 2 sentences of text, then the <invoke> XML in a later chunk).
                # We now check for this pattern during streaming and intercept it.
                full_text = initial_buffer

                # Yield the initial buffer — but filter any MiniMax XML that might
                # have appeared after the initial check
                _stripped_buffer = _strip_minimax_tool_calls(initial_buffer)
                if _stripped_buffer != initial_buffer:
                    # MiniMax XML appeared in the initial buffer but wasn't caught
                    # by the earlier _parse_minimax_tool_call check (e.g., partial XML
                    # that completed during buffering). Re-check now.
                    logger.info("[agent.loop] MiniMax XML detected in initial buffer during Phase 2 — re-checking")
                    _late_calls = _parse_minimax_tool_call(initial_buffer)
                    if _late_calls and not has_error:
                        # Drain remaining chunks and process the intercepted calls
                        if not stream_ended_early:
                            async for _drain_chunk in result:
                                _drain_text = _filter_system_leaks(_drain_chunk.text)
                                _minimax_buffer += _drain_text
                        # Re-process with the complete buffer
                        _minimax_buffer = initial_buffer
                        _minimax_calls = _late_calls
                        # Jump to the MiniMax interception handler above by
                        # re-running the buffer through _parse_minimax_tool_call
                        # and continuing the loop. Since we already consumed the
                        # stream, we process inline here.
                        for _tc_name, _tc_args, _tc_raw_xml in _minimax_calls:
                            _norm_args = dict(_tc_args)
                            if _tc_name == "web_search" and "text" in _norm_args and "query" not in _norm_args:
                                _norm_args["query"] = _norm_args.pop("text")
                            if _tc_name == "web_fetch" and "text" in _norm_args and "url" not in _norm_args:
                                _norm_args["url"] = _norm_args.pop("text")
                            if _tc_name not in AGENT_ALLOWED_TOOLS:
                                continue
                            _tc_input = _extract_tool_input(_tc_name, _norm_args)
                            if not _tc_input or len(_tc_input.strip("?. \t")) < 3:
                                continue
                            _tc_label_parts = {
                                "web_search": f"Searching: {_norm_args.get('query', '')[:80]}",
                                "web_fetch": f"Fetching: {_norm_args.get('url', '')[:80]}",
                                "shell": f"Running: {_norm_args.get('command', '')[:80]}",
                            }
                            _tc_label = _tc_label_parts.get(_tc_name, f"Running {_tc_name}")
                            yield StreamChunk(text="", done=False, status=_tc_label)
                            if _obs:
                                _obs.emit(
                                    "tool_call",
                                    tool=_tc_name,
                                    label=_tc_label,
                                    status="started",
                                    iteration=iteration + 1,
                                )
                            t_late = time.monotonic()
                            try:
                                _late_result, _late_failed, _ = await dispatch_with_retry(
                                    Intent(_tc_name),
                                    _tc_input,
                                    allowed_tool_names=effective_allowed,
                                )
                                _late_lat = round((time.monotonic() - t_late) * 1000)
                                _late_obs = (
                                    _filter_tool_injection(_late_result.content)
                                    if _late_result
                                    else f"[Tool {_tc_name} returned no result]"
                                )
                                if Intent(_tc_name) == Intent.WEB_SEARCH:
                                    _user_q = ""
                                    for m in messages:
                                        if m.get("role") == "user":
                                            _user_q = m.get("content", "")
                                            break
                                    async for chunk in self._handle_web_search_result(
                                        safe_obs=_late_obs,
                                        query=_tc_input,
                                        thought=_strip_minimax_tool_calls(_minimax_buffer),
                                        iteration=iteration,
                                        trace=trace,
                                        user_question=_user_q,
                                        adapter=active_adapter,
                                        allowed_tool_names=effective_allowed,
                                    ):
                                        yield chunk
                                    return

                                trace.steps.append(
                                    AgentStep(
                                        iteration=iteration + 1,
                                        thought=_strip_minimax_tool_calls(_minimax_buffer),
                                        tool_name=_tc_name,
                                        tool_input=_tc_input,
                                        observation=_late_obs[:500],
                                        tool_failed=_late_failed,
                                        latency_ms=_late_lat,
                                    )
                                )
                                if not _late_failed:
                                    yield StreamChunk(
                                        text="",
                                        done=False,
                                        status=f"Done — {_tc_label} ({_late_lat}ms)",
                                    )
                                call_id = str(uuid.uuid4())
                                safe_late_obs = (
                                    (
                                        f"[ACTUAL TOOL OUTPUT — use ONLY this data in your response]\n"
                                        f"{_late_obs}\n"
                                        f"[END TOOL OUTPUT — do NOT invent or add items not shown above]"
                                    )
                                    if not _late_failed and _late_obs
                                    else _late_obs
                                )
                                loop_messages.append(
                                    {
                                        "role": "assistant",
                                        "content": _strip_minimax_tool_calls(_minimax_buffer),
                                        "tool_calls": [
                                            {
                                                "id": call_id,
                                                "type": "function",
                                                "function": {
                                                    "name": _tc_name,
                                                    "arguments": json.dumps(_norm_args),
                                                },
                                            }
                                        ],
                                    }
                                )
                                loop_messages.append(
                                    {
                                        "role": "tool",
                                        "tool_call_id": call_id,
                                        "content": safe_late_obs,
                                    }
                                )
                            except Exception as _late_exc:
                                logger.warning(f"[agent.loop] late MiniMax intercept failed: {_late_exc}")
                            if _obs:
                                _obs.emit(
                                    "tool_call",
                                    tool=_tc_name,
                                    label=_tc_label,
                                    status="done",
                                    latency_ms=_late_lat if "_late_lat" in dir() else 0,
                                    iteration=iteration + 1,
                                )
                        continue  # continue the loop so the model can produce a final answer

                # Yield the clean initial buffer
                if _stripped_buffer.strip():
                    yield StreamChunk(text=_stripped_buffer, done=False)

                # If the stream already ended (short response), we're done
                if stream_ended_early:
                    trace.final_response = full_text
                    trace.steps.append(
                        AgentStep(
                            iteration=iteration + 1,
                            thought=full_text[:500],
                            tool_name=None,
                            tool_input=None,
                            observation=None,
                        )
                    )
                    logger.info(f"[agent.loop] finished iter={iteration + 1} — {trace.summary()}")
                    if _obs:
                        _obs.emit("agent_loop_done", intent=intent.value, iterations=iteration + 1)
                    _worker_report = trace.work_report()
                    if _worker_report.needs_report(full_text):
                        _report_text = _worker_report.render()
                        if _report_text:
                            logger.info(
                                "[agent.loop] short final response did not report tool evidence; "
                                "emitting worker report"
                            )
                            yield StreamChunk(text="\n\n" + _report_text, done=False)
                    yield StreamChunk(text="", done=True)
                    return

                # Stream remaining chunks — with mid-stream MiniMax detection
                _mid_stream_minimax_buffer = ""
                _mid_stream_text = ""
                async for chunk in result:
                    filtered_text = _filter_system_leaks(chunk.text)
                    full_text += filtered_text
                    _mid_stream_text += filtered_text
                    _mid_stream_minimax_buffer += filtered_text
                    if chunk.error:
                        has_error = True
                    # v0.10: Mid-stream MiniMax tool call detection.
                    # If we see a complete <invoke> pattern in the streaming
                    # text, strip it from the output and execute the tool.
                    if _has_minimax_tool_call(_mid_stream_minimax_buffer):
                        logger.info(
                            "[agent.loop] mid-stream MiniMax tool call detected: %s",
                            _mid_stream_minimax_buffer[:200],
                        )
                        # Strip the XML from what we've already yielded
                        _clean = _strip_minimax_tool_calls(_mid_stream_text)
                        # The tool call will be handled on the next iteration
                        # For now, just suppress the XML and let the model see it
                        filtered_text = ""
                        _mid_stream_minimax_buffer = ""
                    # Also strip any partial MiniMax XML from individual chunks
                    _chunk_clean = _strip_minimax_tool_calls(filtered_text)
                    if _chunk_clean:
                        # Keep the terminal marker until report enforcement has
                        # completed below; otherwise the client can finalize
                        # before the worker report is delivered.
                        yield StreamChunk(text=_chunk_clean, done=False)

                trace.final_response = full_text
                trace.steps.append(
                    AgentStep(
                        iteration=iteration + 1,
                        thought=full_text[:500],
                        tool_name=None,
                        tool_input=None,
                        observation=None,
                    )
                )
                logger.info(f"[agent.loop] finished iter={iteration + 1} — {trace.summary()}")
                if _obs:
                    _obs.emit("agent_loop_done", intent=intent.value, iterations=iteration + 1)

                # Explicit worker → report boundary: a tool-bearing turn is
                # not complete merely because the model emitted some text.
                # If that text contains no evidence from successful tool work,
                # append the deterministic report derived from the trace.
                _worker_report = trace.work_report()
                if _worker_report.needs_report(full_text):
                    _report_text = _worker_report.render()
                    if _report_text:
                        logger.info(
                            "[agent.loop] final response did not report tool evidence; "
                            "emitting worker report"
                        )
                        yield StreamChunk(text="\n\n" + _report_text, done=False)
                elif not full_text.strip():
                    # Preserve the existing diagnostic fallback for the rare
                    # case where no structured worker report is available.
                    _tool_summary = self._summarize_trace_for_user(trace, observation_log)
                    if _tool_summary:
                        logger.warning(
                            "[agent.loop] iter=%d — model stream produced no text "
                            "after filtering; yielding trace summary fallback",
                            iteration + 1,
                        )
                        yield StreamChunk(text=_tool_summary, done=False)
                yield StreamChunk(text="", done=True)
                return

        # ── MAX_ITERATIONS hit (or wall-clock cap broke the loop) ──────
        trace.hit_limit = True
        logger.warning(f"[agent.loop] loop ended — {trace.summary()}")
        if _obs:
            _obs.emit("agent_loop_done", intent=intent.value, iterations=trace.iterations_used, hit_limit=True)

        # Session 31: ALWAYS try to synthesize a final answer from what
        # we gathered. Wrap with a timeout so this doesn't hang too.
        # If it times out, yield the observation log directly — the user
        # sees what happened instead of nothing.
        try:
            async for chunk in self._force_final_answer(
                loop_messages=loop_messages,
                observation_log=observation_log,
                active_adapter=active_adapter,
                trace=trace,  # Session 31: pass trace so empty-stream fallback can surface tool outputs
            ):
                yield chunk
        except asyncio.TimeoutError:
            logger.warning("[agent.loop] final synthesis timed out — yielding observation log")
            yield StreamChunk(
                text="I completed the tool calls but ran out of time to synthesize a final answer. Here's what I did:\n\n" + observation_log[:2000],
                done=True,
            )
        except Exception as e:
            logger.warning(f"[agent.loop] final synthesis failed: {e}")
            yield StreamChunk(
                text="I completed the tool calls but couldn't generate a final summary. Here's what I did:\n\n" + observation_log[:2000],
                done=True,
            )

    # ------------------------------------------------------------------
    # Web-search result handler
    # ------------------------------------------------------------------

    async def _handle_web_search_result(
        self,
        safe_obs: str,
        query: str,
        thought: str,
        iteration: int,
        trace: AgentTrace,
        user_question: str = "",
        adapter=None,
        allowed_tool_names: Optional[frozenset[str]] = None,
    ) -> AsyncIterator[StreamChunk]:
        """
        Synthesize search results into a user-facing answer, with follow-up
        fetching when snippets are insufficient.

        Pipeline:
        1. Run synthesizer on search snippets
        2. If snippets are sufficient -> LLM synthesizes answer directly
        3. If snippets need followup -> fetch top URL(s), then use
           synthesize_combined() with a dedicated prompt that prioritizes
           the fetched page content over the snippets

        NEVER dumps raw web content to the user. All output goes through
        the LLM synthesizer or smart regex extraction as a last resort.
        """
        filename = f"search_results_{int(time.time())}.md"

        file_content = (
            f"# Web Search Results: {query}\n\n*Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}*\n\n{safe_obs}"
        )

        # Fire-and-forget: write the raw results file in the background.
        async def _write_file() -> None:
            try:
                await dispatch_with_retry(
                    Intent.FILE_WRITE,
                    f"{filename}:\n\n{file_content}",
                    allowed_tool_names=allowed_tool_names,
                )
                logger.info(f"[agent.loop] web search results written to {filename}")
            except Exception as exc:
                logger.warning(f"[agent.loop] search result file write failed: {exc}")

        asyncio.create_task(_write_file())

        # ── Synthesis pipeline ──────────────────────────────────────────
        synthesis_answer = None

        if self._synthesizer.enabled:
            try:
                # Create a ToolResult from the search output for the synthesizer
                from core.models import RiskLevel, ToolResult

                search_result = ToolResult(
                    content=safe_obs,
                    risk=RiskLevel.LOW,
                    source="web_search",
                )

                # Step 1: Check sufficiency of search snippets
                synthesis = await self._synthesizer.synthesize(
                    tool_results=[search_result],
                    intent=Intent.WEB_SEARCH,
                    user_question=user_question or query,
                    adapter=adapter or self._adapter,
                )

                if synthesis.needs_followup and synthesis.followup_tool == "web_fetch":
                    # Snippets are insufficient — fetch the top URL for actual data
                    followup_url = (synthesis.followup_args or {}).get("url", "")
                    if followup_url:
                        logger.info(f"[agent.loop] synthesis requests web_fetch for: {followup_url[:80]}")
                        # Emit a status chunk so the user knows we're fetching
                        yield StreamChunk(text="", done=False, status=f"Reading page: {followup_url[:60]}")
                        fetch_result, fetch_failed, _ = await dispatch_with_retry(
                            Intent.WEB_FETCH,
                            followup_url,
                            allowed_tool_names=allowed_tool_names,
                        )
                        if fetch_result and not fetch_failed:
                            # Step 2: Use synthesize_combined() — this is the PRIMARY
                            # synthesis path for web queries. It uses a dedicated prompt
                            # that prioritizes fetched page content over search snippets,
                            # and pre-processes the content to remove ads/noise.
                            fetch_synthesis = await self._synthesizer.synthesize_combined(
                                search_result=search_result,
                                fetch_result=fetch_result,
                                user_question=user_question or query,
                                adapter=adapter or self._adapter,
                            )
                            synthesis_answer = fetch_synthesis.answer
                        else:
                            # Fetch failed — use the search-only synthesis
                            synthesis_answer = synthesis.answer or (
                                "I found some relevant results but couldn't read the "
                                "full page content. The search snippets didn't contain "
                                "enough detail to fully answer your question."
                            )
                    else:
                        synthesis_answer = synthesis.answer or (
                            "I found search results but need more detail. "
                            "The search snippets didn't contain enough specific data."
                        )
                elif synthesis.answer:
                    # Search snippets were sufficient — use the synthesized answer
                    synthesis_answer = synthesis.answer
                elif synthesis.is_gap_report:
                    # Honest gap report
                    synthesis_answer = synthesis.answer

            except Exception as e:
                logger.warning(f"[agent.loop] synthesis failed: {e}")
                # Use smart extraction instead of dumping raw content
                from core.agent.synthesizer import _smart_extract_key_data

                synthesis_answer = _smart_extract_key_data(safe_obs, user_question or query)

        # Fallback: if synthesis didn't produce an answer, use smart extraction
        if not synthesis_answer:
            from core.agent.synthesizer import _smart_extract_key_data

            synthesis_answer = _smart_extract_key_data(safe_obs, user_question or query)

        trace.final_response = synthesis_answer
        trace.steps.append(
            AgentStep(
                iteration=iteration + 1,
                thought=thought,
                tool_name="web_search",
                tool_input=query,
                observation=f"Results → {filename}, synthesized answer provided",
            )
        )

        yield StreamChunk(text=synthesis_answer, done=False)
        yield StreamChunk(text="", done=True)

    # ------------------------------------------------------------------
    # Planning phase
    # ------------------------------------------------------------------

    async def _plan_stream(
        self,
        active_adapter,
        intent: Intent,
        loop_messages: list[dict],
        available_tools: list[dict],
        env_context: str,
        intent_history: Optional[list[str]] = None,
    ):
        """
        Streaming version of _plan — yields plan tokens as they arrive.

        This lets the user see the model's planning reasoning (UNDERSTANDING,
        STEPS, ARGS_PRECHECK) in real-time in the thinking block, instead of
        waiting 5-15s for the full plan to be generated before showing anything.
        """
        # Find the user message
        user_message = ""
        for msg in reversed(loop_messages):
            if msg.get("role") == "user":
                user_message = msg.get("content", "")
                break
        if not user_message:
            return

        planning_prompt = build_planning_prompt(
            intent=intent,
            user_message=user_message,
            available_tools=available_tools,
            env_context=env_context,
            intent_history=intent_history,
        )

        planning_messages = [
            {"role": "system", "content": planning_prompt},
            {"role": "user", "content": user_message},
        ]

        try:
            _plan_timeout = PLAN_TIMEOUT_SECS

            # Use a queue for real-time streaming with timeout
            _plan_queue: asyncio.Queue = asyncio.Queue()
            _SENTINEL = object()

            async def _stream_plan():
                try:
                    async for chunk in active_adapter.chat(
                        planning_messages,
                        temperature=0.1,
                        intent="chat",
                    ):
                        if chunk.error:
                            logger.warning("[agent.loop] plan stream adapter error: %s", chunk.error[:120])
                            break
                        text = _filter_system_leaks(chunk.text)
                        if text:
                            await _plan_queue.put(text)
                finally:
                    await _plan_queue.put(_SENTINEL)

            _task = asyncio.create_task(_stream_plan())
            try:
                while True:
                    try:
                        item = await asyncio.wait_for(_plan_queue.get(), timeout=_plan_timeout)
                    except asyncio.TimeoutError:
                        _task.cancel()
                        logger.warning(f"[agent.loop] planning stream timed out ({_plan_timeout}s)")
                        break
                    if item is _SENTINEL:
                        break
                    yield item
                # Ensure the task completes — but don't hang if it already
                # finished or errored. Use a short timeout.
                try:
                    await asyncio.wait_for(_task, timeout=5)
                except (asyncio.TimeoutError, Exception):
                    _task.cancel()
            except Exception:
                _task.cancel()
                raise

        except Exception as exc:
            logger.warning(f"[agent.loop] planning stream failed (non-fatal): {exc}")

    async def _plan(
        self,
        active_adapter,
        intent: Intent,
        loop_messages: list[dict],
        available_tools: list[dict],
        env_context: str,
        intent_history: Optional[list[str]] = None,
    ) -> tuple[str, int]:
        """
        Run a planning LLM call (no tools) to produce a step-by-step plan.

        Returns:
            (plan_text, iterations_cost): The plan text to inject into the
            execution prompt, and how many iterations the planning phase
            consumed from the budget (typically PLAN_ITERATION_COST = 1).
        """
        # Extract user message from the conversation
        user_message = ""
        for msg in reversed(loop_messages):
            if msg.get("role") == "user":
                user_message = msg.get("content", "")
                break

        if not user_message:
            return "", 0

        planning_prompt = build_planning_prompt(
            intent=intent,
            user_message=user_message,
            available_tools=available_tools,
            env_context=env_context,
            intent_history=intent_history,
        )

        planning_messages = [
            {"role": "system", "content": planning_prompt},
            {"role": "user", "content": user_message},
        ]

        try:
            t_plan = time.monotonic()
            plan_chunks: list[str] = []

            # v0.11: Add timeout to planning phase (previously unbounded).
            # On slow models or API providers, planning could take 30+ seconds.
            _plan_timeout = PLAN_TIMEOUT_SECS

            async def _collect_plan():
                async for chunk in active_adapter.chat(
                    planning_messages,
                    temperature=0.1,
                    intent="chat",
                ):
                    if chunk.error:
                        logger.warning("[agent.loop] plan collect adapter error: %s", chunk.error[:120])
                        break
                    plan_chunks.append(chunk.text)

            await asyncio.wait_for(_collect_plan(), timeout=_plan_timeout)
            plan_text = "".join(plan_chunks).strip()
            plan_ms = round((time.monotonic() - t_plan) * 1000)

            if plan_text:
                # Truncate plan to prevent context bloat — plans should be concise
                _PLAN_MAX_CHARS = 1500
                if len(plan_text) > _PLAN_MAX_CHARS:
                    plan_text = plan_text[:_PLAN_MAX_CHARS] + "\n[... plan truncated]"
                logger.info(f"[agent.loop] planning phase completed in {plan_ms}ms, plan_len={len(plan_text)}")
                return plan_text, PLAN_ITERATION_COST
            else:
                logger.info("[agent.loop] planning phase returned empty plan — skipping")
                return "", 0

        except asyncio.TimeoutError:
            logger.warning(f"[agent.loop] planning phase timed out ({_plan_timeout}s) — skipping")
            return "", 0
        except Exception as exc:
            logger.warning(f"[agent.loop] planning phase failed (non-fatal): {exc}")
            return "", 0

    # ------------------------------------------------------------------
    # Post-execution verification
    # ------------------------------------------------------------------

    async def _verify_tool_result(
        self,
        tool_name: str,
        tool_args: dict,
        observation: str,
        allowed_tool_names: Optional[frozenset[str]] = None,
    ) -> Optional[str]:
        """
        Verify a tool result after successful execution.

        Returns:
            A verification message to append to the observation, or None
            if no verification was needed or it passed silently.

        Verification checks:
        - file_write: Read the file back to confirm it exists and has content
        - code_exec: Check for Python error indicators in the output
        - shell: Check for common error patterns in the output
        """
        try:
            # ── file_write verification ──────────────────────────────────
            if tool_name == "file_write" and VERIFY_FILE_WRITE:
                path = tool_args.get("path", "")
                expected_len = len(tool_args.get("content", ""))
                if not path:
                    return None

                # Dispatch a file_task to read the file back
                # NOTE: dispatch_with_retry is imported at module level (line 177).
                # Do NOT re-import it here — that would shadow the module-level
                # binding and cause UnboundLocalError in other parts of run().
                verify_result, verify_failed, _ = await dispatch_with_retry(
                    Intent.FILE_TASK,
                    path,
                    max_retries=0,  # no retry for verification
                    allowed_tool_names=allowed_tool_names,
                )
                if verify_failed or not verify_result or not verify_result.success:
                    return (
                        f"File verification FAILED — could not read back '{path}'. "
                        f"The file may not have been written correctly."
                    )

                actual_content = verify_result.content or ""
                actual_len = len(actual_content)

                # Check if the file was written with reasonable content
                if actual_len == 0:
                    return (
                        f"File verification FAILED — '{path}' exists but is empty. "
                        f"Expected {expected_len} chars of content."
                    )

                # Check for significant truncation (>50% content loss)
                if expected_len > 100 and actual_len < expected_len * 0.5:
                    return (
                        f"File verification WARNING — '{path}' may be truncated. "
                        f"Written {actual_len} chars but expected ~{expected_len} chars. "
                        f"Consider rewriting the file with complete content."
                    )

                # Silent pass — no verification message needed
                logger.info(
                    f"[agent.loop] file_write verification passed: "
                    f"path={path} expected={expected_len} actual={actual_len}"
                )
                return None

            # ── code_exec verification ───────────────────────────────────
            if tool_name == "code_exec" and VERIFY_CODE_EXEC:
                # Check for common Python error patterns in the output
                error_indicators = [
                    "Traceback (most recent call last)",
                    "SyntaxError:",
                    "IndentationError:",
                    "NameError:",
                    "TypeError:",
                    "ValueError:",
                    "ImportError:",
                    "ModuleNotFoundError:",
                    "KeyboardInterrupt",
                ]
                found_errors = [e for e in error_indicators if e in observation]
                if found_errors:
                    return f"Code execution produced errors: {', '.join(found_errors[:3])}. Fix the code and try again."
                return None

        except Exception as exc:
            logger.warning(f"[agent.loop] verification failed (non-fatal): {exc}")
            return None

        return None

    # ------------------------------------------------------------------
    # Trace summarization — for silent-failure fallbacks (Session 31)
    # ------------------------------------------------------------------

    @staticmethod
    def _summarize_trace_for_user(trace, observation_log: str) -> str:
        """
        Build a user-facing summary of what tools actually ran, for the
        silent-failure fallback path. Returns an empty string if no tools
        ran (so the caller knows there's nothing to summarize).

        Session 31 (revised per user feedback): the previous version guessed
        "free-tier model overload" — a plausible-sounding but unverified
        self-diagnosis. The user correctly pushed back: for a 4-step task
        (mkdir, git init, write a small file, commit), context overflow is
        not plausible. The real cause is more likely a tool returning
        broken/unexpected data that the synthesizer chokes on.

        The honest fix: surface the ACTUAL tool inputs and outputs (truncated)
        so the user can see for themselves what happened. Don't guess at the
        cause — let the evidence speak. If a tool returned malformed data,
        the user will spot it immediately in the output.

        Args:
            trace: AgentTrace with .steps (list of AgentStep).
            observation_log: the failed-tool log (may be empty if all
                tools succeeded).

        Returns:
            A user-facing string with tool call details, or "" if no tool
            calls ran.
        """
        # Collect tool calls from the trace (skip pure-thinking steps
        # where tool_name is None).
        tool_calls = [s for s in trace.steps if s.tool_name]
        if not tool_calls:
            # No tools ran — return empty so caller falls back to the
            # model-overload suggestion in _force_final_answer.
            return ""

        lines = [
            "I ran the requested tools but the model couldn't summarize "
            "what happened (it returned an empty response). Instead of "
            "guessing why, here's the raw evidence — each tool I called, "
            "what I sent it, and what it returned:",
            "",
        ]
        # Session 32: if the iteration limit was hit, say so explicitly.
        # The previous fallback guessed "overload" — that was a wrong
        # diagnosis. The real cause was almost always the iteration cap
        # being too low (now fixed — raised from 3 to 8). When hit_limit
        # is True, the user needs to know: the model didn't fail, it just
        # ran out of iterations before finishing the task.
        if getattr(trace, "hit_limit", False):
            lines.insert(0, (
                f"I hit my iteration limit ({trace.iterations_used} iterations) "
                f"before completing the task. This is NOT a model overload or "
                f"context-overflow issue — I simply ran out of steps. Here's "
                f"what I managed to do before the cap:"
            ))
            # Remove the generic "couldn't summarize" line we just added —
            # it's misleading when the real cause is the iteration cap.
            lines = [lines[0], ""] + lines[3:]
        for i, step in enumerate(tool_calls, 1):
            status = "FAILED" if step.tool_failed else "ok"
            _input = (step.tool_input or "").strip()
            if len(_input) > 120:
                _input = _input[:117] + "..."
            lines.append(f"  {i}. {step.tool_name}({_input}) — {status}")

            # ALWAYS surface the observation (tool output), not just for
            # failed tools. The user's point is that a SUCCEEDED tool might
            # be returning malformed data that chokes the synthesizer —
            # we need to show success outputs too, not just error outputs.
            if step.observation:
                _obs_text = step.observation.strip()
                if len(_obs_text) > 300:
                    _obs_text = _obs_text[:297] + "..."
                # First non-empty line, or the whole thing if single-line
                _first_line = _obs_text.splitlines()[0] if _obs_text.splitlines() else _obs_text
                if step.tool_failed:
                    lines.append(f"     → error: {_first_line}")
                else:
                    lines.append(f"     → output: {_first_line}")

        # Surface the observation log too if it has content (failed tools
        # are logged here with their full error context — more detail than
        # the per-step snippet above).
        if observation_log.strip():
            lines.append("")
            lines.append("Full error details:")
            lines.append(observation_log[:1500])

        lines.append("")
        # Session 32: tailor the "what to try" advice to the actual cause.
        # If hit_limit is True, the advice is "tell me to continue" or
        # "raise the iteration limit" — NOT "switch to a larger model"
        # (the model didn't fail, it just ran out of steps).
        if getattr(trace, "hit_limit", False):
            lines.append(
                "What to try next:\n"
                "  • Tell me to \"continue\" — I'll pick up where I left off\n"
                "    and finish the remaining steps.\n"
                "  • Or ask me to do one step at a time so each step gets\n"
                "    its own iteration budget.\n"
                "  • The iteration limit is configurable via the\n"
                "    LOCALMIND_MAX_ITERATIONS env var (default: 8)."
            )
        else:
            lines.append(
                "What to try next:\n"
                "  • Check the outputs above — if a tool returned something\n"
                "    unexpected, that's likely the real cause (not 'overload').\n"
                "  • Try one step at a time to isolate which step breaks.\n"
                "  • Or switch to a larger model if you want me to retry the\n"
                "    synthesis with more reasoning capacity."
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Forced final answer after iteration limit
    # ------------------------------------------------------------------

    async def _force_final_answer(
        self,
        loop_messages: list[dict],
        observation_log: str,
        active_adapter,
        trace=None,
    ) -> AsyncIterator[StreamChunk]:
        """
        After hitting MAX_ITERATIONS, ask the LLM to synthesize a final
        answer from everything gathered so far.  Uses plain chat() without
        tools — the model should just summarize what it knows.

        Session 31: now accepts an optional `trace` parameter so the
        empty-stream fallback can surface ACTUAL tool inputs/outputs
        instead of guessing "overload" (per user feedback — the overload
        diagnosis was unverified and likely wrong for small tasks).
        """
        # Strip tool_calls from messages for the plain chat call.
        # Convert tool results to user-readable context with generous truncation
        # (1500 chars — the 500-char limit was too aggressive and lost key info).
        clean_messages = []
        for msg in loop_messages:
            if msg.get("role") == "tool":
                # Tool results become user context — use generous truncation
                content = msg.get("content", "")
                if len(content) > 1500:
                    half = 750
                    content = content[:half] + f"\n…[{len(content) - 1500} chars omitted]…\n" + content[-half:]
                clean_messages.append(
                    {
                        "role": "user",
                        "content": f"[Tool result]: {content}",
                    }
                )
            elif msg.get("role") == "assistant" and msg.get("tool_calls"):
                # Keep text content, drop tool_calls — model sees it as its own prior turn
                clean_messages.append(
                    {
                        "role": "assistant",
                        "content": msg.get("content", "") or "I was gathering information.",
                    }
                )
            else:
                clean_messages.append(msg)

        force_msg = clean_messages + [
            {
                "role": "user",
                "content": (
                    f"{observation_log}\n"
                    "Maximum iterations reached. Provide your best answer now "
                    "based on everything gathered so far. Do not call any tools — "
                    "just answer directly.\n\n"
                    "ANTI-FABRICATION: Your answer MUST be based EXACTLY on the tool "
                    "results shown above. Do NOT invent file names, folder contents, "
                    "or any data that was not in the tool output. If a tool showed "
                    "3 items, report 3 items — never add items that 'seem typical'."
                ),
            }
        ]
        # Session 31: track whether the model produced ANY non-empty text.
        # Free-tier models sometimes return an empty stream (zero chunks, or
        # chunks whose text is entirely filtered out as system-leak XML).
        # Without this check, _force_final_answer returns silently, the
        # engine sees an empty full_response_chunks, and the user gets the
        # uselessly generic "I wasn't able to complete that request. The
        # tool may have failed or returned no useful output." fallback —
        # with zero indication of what actually happened. This is the
        # "Tools execution failure" symptom the user reported.
        _any_text_yielded = False
        _final_chunks: list[StreamChunk] = []
        _final_text_parts: list[str] = []
        try:
            t_final = time.monotonic()
            async for chunk in active_adapter.chat(force_msg, temperature=0.4):
                if chunk.error:
                    _error_report = trace.work_report().render() if trace is not None else ""
                    yield StreamChunk(text=_error_report, done=True, error=chunk.error)
                    return
                filtered_text = _filter_system_leaks(chunk.text)
                if filtered_text:
                    _any_text_yielded = True
                    _final_text_parts.append(filtered_text)
                # Hold the terminal marker until the worker report contract
                # has been enforced below.
                _final_chunks.append(StreamChunk(text=filtered_text, done=False))
            logger.info(f"[agent.loop] final synthesis: {round((time.monotonic() - t_final) * 1000)}ms")
        except Exception as exc:
            logger.warning(f"[agent.loop] final synthesis failed: {exc}")
            _error_report = trace.work_report().render() if trace is not None else ""
            _exception_text = (
                "I've reached my iteration limit. Here are the key findings gathered so far:\n\n"
                + observation_log
            )
            if _error_report:
                _exception_text += "\n\n" + _error_report
            yield StreamChunk(text=_exception_text, done=True)
            return  # CRITICAL: return after yielding the exception fallback

        _final_text = "".join(_final_text_parts)
        if trace is not None and trace.work_report().needs_report(_final_text):
            _report_text = trace.work_report().render()
            if _report_text:
                logger.info(
                    "[agent.loop] forced final response did not report tool evidence; "
                    "emitting worker report"
                )
                _final_chunks.append(StreamChunk(text="\n\n" + _report_text, done=False))

        if _final_chunks and _any_text_yielded:
            for _final_chunk in _final_chunks:
                yield _final_chunk
            yield StreamChunk(text="", done=True)

        # Session 31 (revised per user feedback): if the model returned an
        # empty stream (or all chunks were filtered out as system-leak XML),
        # yield a fallback that surfaces ACTUAL EVIDENCE — not a guess.
        #
        # The previous version guessed "free-tier model overload." The user
        # correctly pushed back: for a 4-step task (mkdir, git init, write
        # a small file, commit), context overflow is not plausible. The
        # real cause is more likely a tool returning broken data that the
        # synthesizer chokes on. So instead of guessing, surface the actual
        # tool inputs and outputs from the trace and let the user decide.
        if not _any_text_yielded:
            logger.warning(
                "[agent.loop] final synthesis produced no text — "
                "yielding evidence-based fallback (model returned empty stream)"
            )
            # Try the trace summary first — it lists every tool call with
            # its actual input and output (truncated). This is the honest
            # fallback: show what happened, don't guess why.
            _evidence_summary = ""
            if trace is not None:
                _evidence_summary = self._summarize_trace_for_user(trace, observation_log)

            if _evidence_summary:
                # Trace has tool calls — surface them as evidence.
                yield StreamChunk(text=_evidence_summary, done=True)
            elif observation_log.strip():
                # No trace available but observation_log has content (failed
                # tools). Surface that.
                yield StreamChunk(
                    text=(
                        "I completed the tool calls but the model couldn't "
                        "synthesize a final response (it returned an empty "
                        "stream). Here's what I did:\n\n"
                        + observation_log[:2000]
                        + "\n\nCheck the outputs above — if a tool returned "
                        "something unexpected, that's likely the real cause."
                    ),
                    done=True,
                )
            else:
                # No tools ran AND no observation log — this is a genuine
                # model issue (no tools to blame). Only here do we suggest
                # model overload as a possibility.
                yield StreamChunk(
                    text=(
                        "The model returned an empty response and no tools "
                        "were executed. This is likely a model-side issue "
                        "(overload, rate limit, or the model rejected the "
                        "prompt).\n\n"
                        "Try one of these:\n"
                        "  • Re-run the request — transient overload is common\n"
                        "  • Switch to a larger model (Settings → Model)\n"
                        "  • Try a simpler phrasing of your request"
                    ),
                    done=True,
                )
