"""
Browser agent scoped toolset.

Each agent has its own scoped toolset. A browser agent
shouldn't have shell tools; a coding agent shouldn't have browser
tools. Smaller surface = more reliable selection on gemma3:1b-class
models.

The browser agent's tool surface is exactly one tool: Intent.BROWSE.
This is the smallest possible scoped surface and the natural starting
point for the multi-agent architecture — the existing
tools/browser_agent.py tool becomes the sole tool the BrowserAgent
class exposes.
"""

from __future__ import annotations

from core.agent.constants import AGENT_ALLOWED_TOOLS
from core.models import Intent

# The browser agent's scoped tool allowlist. This is a
# subset of AGENT_ALLOWED_TOOLS — only the tools this agent should
# be able to call.
#
# 'delegate' lets the browser agent hand off a sub-task
# to the research agent (e.g., "search for the login URL for site X"
# before navigating) or the coding agent (e.g., "extract data from
# the downloaded HTML file"). The browser agent's primary job is
# page interaction; research/coding sub-tasks are delegated.
BROWSER_TOOLS: frozenset[str] = frozenset(
    {
        Intent.BROWSE.value,  # the browser_agent tool
        "delegate",  # agent-initiated delegation
        "skill",  # universal skill tool
    }
)

# Sanity check: BROWSER_TOOLS must be a subset of AGENT_ALLOWED_TOOLS.
# If a future change adds a browser-only tool that isn't in the global
# allowlist, this assertion catches it at import time.
assert BROWSER_TOOLS.issubset(AGENT_ALLOWED_TOOLS), (
    f"BROWSER_TOOLS ({BROWSER_TOOLS}) must be a subset of "
    f"AGENT_ALLOWED_TOOLS ({AGENT_ALLOWED_TOOLS})"
)
