"""
Reviewer agent scoped toolset.

Each agent has its own scoped toolset. A reviewer agent has
file_task + git + shell + delegate. It does NOT have code_exec, file_write,
edit_file, web tools, browser, process, memory, or sysinfo.

The reviewer's tools map to its responsibilities:
  - file_task → read source files under review
  - git       → check what changed (diff against baseline)
  - shell     → run static analysis, linters, quality checks
  - delegate  → hand off findings to coding/verifier

The reviewer's job is to ASSESS quality, not to build or fix. It reads code,
checks it against specs and best practices, and reports findings. It does NOT
edit code (that's the coding agent's job) or run tests (that's the verifier's
job). This clean separation keeps each agent's responsibility clear.
"""

from __future__ import annotations

from core.agent.constants import AGENT_ALLOWED_TOOLS

REVIEWER_TOOLS: frozenset[str] = frozenset(
    {
        "file_task",
        "git",
        "shell",
        "delegate",  # hand off findings to other agents
        "skill",  # universal skill tool
    }
)

assert REVIEWER_TOOLS.issubset(AGENT_ALLOWED_TOOLS), (
    f"REVIEWER_TOOLS ({REVIEWER_TOOLS}) must be a subset of "
    f"AGENT_ALLOWED_TOOLS ({AGENT_ALLOWED_TOOLS})"
)
