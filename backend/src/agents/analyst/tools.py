"""
Analyst agent scoped toolset.

Each agent has its own scoped toolset. An analyst agent has
file_task + git + delegate. It does NOT have code_exec, file_write,
edit_file, shell, process, web tools, browser, memory, or sysinfo.

The analyst's tools map to its responsibilities:
  - file_task → read specs, requirements docs, project files
  - git       → check project history, understand what's been built
  - delegate  → hand off clarified specs to other agents

The analyst's job is to UNDERSTAND and CLARIFY — it reads specifications,
examines project context, and produces a clear, actionable description of
what needs to be built. It does NOT plan implementation (that's the
planner's job), build code (coding agent), or verify results (verifier).
"""

from __future__ import annotations

from core.agent.constants import AGENT_ALLOWED_TOOLS

ANALYST_TOOLS: frozenset[str] = frozenset(
    {
        "file_task",
        "git",
        "delegate",
        "skill",  # universal skill tool
    }
)

assert ANALYST_TOOLS.issubset(AGENT_ALLOWED_TOOLS), (
    f"ANALYST_TOOLS ({ANALYST_TOOLS}) must be a subset of "
    f"AGENT_ALLOWED_TOOLS ({AGENT_ALLOWED_TOOLS})"
)
