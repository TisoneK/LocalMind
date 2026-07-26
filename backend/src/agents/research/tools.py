"""Research agent scoped toolset — web_search + web_fetch only."""

from __future__ import annotations

from core.agent.constants import AGENT_ALLOWED_TOOLS

# The research agent's scoped toolset: web search + web fetch.
# Excludes shell/files/browser/code_exec/memory/sysinfo — those belong
# to other agents. Smaller surface = more reliable selection on
# gemma3:1b-class hardware (ADR-6 point 6).
RESEARCH_TOOLS: frozenset[str] = frozenset({"web_search", "web_fetch"})

assert RESEARCH_TOOLS.issubset(AGENT_ALLOWED_TOOLS), (
    f"RESEARCH_TOOLS ({RESEARCH_TOOLS}) must be a subset of "
    f"AGENT_ALLOWED_TOOLS ({AGENT_ALLOWED_TOOLS})"
)
