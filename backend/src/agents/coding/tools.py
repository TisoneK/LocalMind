"""
Coding agent scoped toolset.

Each agent has its own scoped toolset. A coding agent has
shell + filesystem + code execution tools. It does NOT have web search,
web fetch, browser, memory_op, or sysinfo — those belong to other
agents or are secondary during coding tasks.

The goal is simple: fewer tools for the small model
to choose from = more reliable selection. A gemma3:1b-class model
choosing among 5 coding tools is far more reliable than choosing among
10+ flat tools.
"""

from __future__ import annotations

from core.agent.constants import AGENT_ALLOWED_TOOLS

# The coding agent's scoped tool allowlist. This is a subset
# of AGENT_ALLOWED_TOOLS — only the tools this agent should be able to
# call.
#
# NOTE: AGENT_ALLOWED_TOOLS uses tool-module names (e.g., "edit_file"),
# NOT Intent enum values (e.g., Intent.FILE_EDIT.value == "file_edit").
# This is a pre-existing naming inconsistency in the codebase: most
# intent values match their tool module names, but FILE_EDIT's tool
# module is "edit_file" (tools/edit_file.py) while its intent value is
# "file_edit". We use the tool-module names here to match
# AGENT_ALLOWED_TOOLS, since that's what the tool-filtering logic in
# agent/loop.py compares against.
#
# The 5 coding tools map to the CODING HARNESS diagram's Column 3
# (Tools — "what changes the world"):
#   - shell      → terminal/sandboxed bash (Execute)
#   - file_task  → read & search files (Execute)
#   - file_write → create files (Land)
#   - edit_file  → modify files in-place (Land)
#   - code_exec  → execute code (Execute)
#   - delegate   → delegate to research/browser/direct
#     when the coding task needs another domain (e.g., "write a script
#     that uses the current weather API" — delegate the weather lookup
#     to the research agent, then continue coding with the result).
#
# Excluded (belong to other agents or are secondary):
#   - web_search, web_fetch → research agent (delegate to it instead)
#   - browse → browser agent (delegate to it instead)
#   - memory_op → shared but secondary during coding (the agent has
#     env_context + workspace_state for context)
#   - sysinfo → the agent gets system info from env_context already
CODING_TOOLS: frozenset[str] = frozenset(
    {
        "shell",
        "file_task",
        "file_write",
        "edit_file",
        "code_exec",
        "git",
        "system_search",  # unified local search — single front door (find_path retired from model surface)
        "observe",  # desktop awareness — window/clipboard/apps/state/recent files
        "calculator",  # safe arithmetic — offline, bounded
        "csv",  # bounded CSV parsing — offline, bounded
        "json",  # bounded JSON parse/query — offline, bounded
        "sql",  # read-only SQLite queries — offline, bounded
        "process",
        "delegate",  # agent-initiated delegation
        "delegate_parallel",  # parallel delegation fan-out
        "propose_str_replace",  # stage an edit proposal (no write)
        "propose_write_file",  # stage a write proposal (no write)
        "apply_proposed_edit",  # write a staged proposal to disk
        "add_subgoal",  # subgoal scratchpad
        "update_subgoal",  # subgoal scratchpad
        "create_plan",  # subgoal scratchpad
        "skill",  # load a skill into context
        "best_of_n_edit",  # N candidate edits → selector → apply winner
        "diagnostics",  # structured failure analysis
    }
)

# Sanity check: CODING_TOOLS must be a subset of AGENT_ALLOWED_TOOLS.
assert CODING_TOOLS.issubset(AGENT_ALLOWED_TOOLS), (
    f"CODING_TOOLS ({CODING_TOOLS}) must be a subset of "
    f"AGENT_ALLOWED_TOOLS ({AGENT_ALLOWED_TOOLS})"
)
