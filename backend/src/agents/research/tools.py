"""Research agent scoped toolset — web_search + web_fetch + delegate."""

from __future__ import annotations

from core.agent.constants import AGENT_ALLOWED_TOOLS

# The research agent's scoped toolset: web search + web fetch + delegate.
# Excludes shell/files/browser/code_exec/memory/sysinfo — those belong
# to other agents. Smaller surface = more reliable selection on
# gemma3:1b-class hardware (ADR-6 point 6).
#
# ADR-8 Phase 3: 'delegate' lets the research agent hand off a sub-task
# to the coding agent (e.g., "parse this downloaded CSV and return the
# row count") instead of trying to do file analysis itself (which it
# can't — it has no file tools).
RESEARCH_TOOLS: frozenset[str] = frozenset(
    {"web_search", "web_fetch", "delegate", "skill"}  # B-2026-08-02-12: universal skill tool
)

assert RESEARCH_TOOLS.issubset(AGENT_ALLOWED_TOOLS), (
    f"RESEARCH_TOOLS ({RESEARCH_TOOLS}) must be a subset of "
    f"AGENT_ALLOWED_TOOLS ({AGENT_ALLOWED_TOOLS})"
)
