"""
Debugger agent scoped toolset.

Per ADR-6: each agent has its own scoped toolset. A debugger agent has
file_task + git + shell + process + delegate. It does NOT have code_exec,
file_write, edit_file, web tools, browser, memory, or sysinfo.

The debugger's tools map to its responsibilities:
  - file_task → read source files, error logs, tracebacks
  - git       → check what changed (diff, log, bisect candidates)
  - shell     → run diagnostic commands, inspect state
  - process   → start/stop services for debugging
  - delegate  → ADR-8 Phase 3: hand off root cause + fix to coding agent

The debugger's job is to FIND root causes, not to fix them. It reads
error output, traces through code, checks git history for regressions,
and isolates the minimal reproduction. Once the root cause is identified,
it reports findings and delegates the fix to the coding agent.
"""

from __future__ import annotations

from core.agent.constants import AGENT_ALLOWED_TOOLS

DEBUGGER_TOOLS: frozenset[str] = frozenset(
    {
        "file_task",
        "git",
        "shell",
        "process",
        "delegate",
        "diagnostics",  # Session 49: structured failure analysis
        "skill",  # B-2026-08-02-12: universal skill tool
    }
)

assert DEBUGGER_TOOLS.issubset(AGENT_ALLOWED_TOOLS), (
    f"DEBUGGER_TOOLS ({DEBUGGER_TOOLS}) must be a subset of "
    f"AGENT_ALLOWED_TOOLS ({AGENT_ALLOWED_TOOLS})"
)
