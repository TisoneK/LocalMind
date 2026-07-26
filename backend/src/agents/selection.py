"""
Agent selection — maps Intent → agent name, then looks up the agent class.

Per ADR-6: the intent router / UI picker selects an agent by name from
the registry, rather than an if/else buried in a chat handler. This
module provides the intent-based auto-selection mapping (the fallback
when the user hasn't explicitly picked an agent via the UI).

The mapping is conservative: each intent maps to the agent whose scoped
toolset includes that intent's tool. Intents that don't clearly belong
to one agent (e.g., MEMORY_OP) default to the coding agent, which has
the broadest coding-focused toolset.

Usage:
    from agents.selection import select_agent, intent_to_agent_name

    # Map an intent to an agent name
    name = intent_to_agent_name(Intent.SHELL)  # → "coding"

    # Get the agent class for an intent
    agent_class = select_agent(Intent.SHELL)  # → CodingAgent

    # Or instantiate with an adapter
    agent = select_agent(Intent.SHELL)(adapter=some_adapter)

Non-breaking: this module is opt-in. The existing engine pipeline
doesn't call it yet — it still uses AgentLoop directly. A future session
(or the user) can wire it in by replacing `AgentLoop(adapter).run(...)`
with `select_agent(intent)(adapter).run(...)`.

Per ADR-6 point 5: explicit user selection (UI picker) is preferred over
LLM-based routing. This intent-based mapping is the fallback for when
the user hasn't picked — it's deterministic and free (no extra LLM call).
"""

from __future__ import annotations

import logging
from typing import Optional

from agents.registry import get_agent
from core.models import Intent

logger = logging.getLogger(__name__)

# The intent → agent name mapping. Each intent maps to the agent whose
# scoped toolset includes that intent's tool. This is the deterministic
# fallback when the user hasn't explicitly picked an agent via the UI.
#
# Mapping rationale:
#   - SHELL, FILE_TASK, FILE_WRITE, FILE_EDIT, CODE_EXEC → coding agent
#     (these are the 5 tools in CODING_TOOLS)
#   - WEB_SEARCH, WEB_FETCH → research agent
#     (these are the 2 tools in RESEARCH_TOOLS)
#   - BROWSE → browser agent
#     (this is the 1 tool in BROWSER_TOOLS)
#   - CHAT → direct agent
#     (no tools — single model call, steps 1-2 only)
#   - SYSINFO, MEMORY_OP → coding agent (broadest toolset; these are
#     secondary during any task and the coding agent has the most
#     general-purpose tools)
_INTENT_TO_AGENT: dict[Intent, str] = {
    Intent.SHELL: "coding",
    Intent.FILE_TASK: "coding",
    Intent.FILE_WRITE: "coding",
    Intent.FILE_EDIT: "coding",
    Intent.CODE_EXEC: "coding",
    Intent.WEB_SEARCH: "research",
    Intent.WEB_FETCH: "research",
    Intent.BROWSE: "browser",
    Intent.CHAT: "direct",
    Intent.SYSINFO: "coding",
    Intent.MEMORY_OP: "coding",
}


def intent_to_agent_name(intent: Intent) -> str:
    """
    Map an Intent to an agent name.

    This is the deterministic fallback when the user hasn't explicitly
    picked an agent via the UI. Per ADR-6 point 5, explicit user
    selection is preferred — but when it's not available, this mapping
    is free (no extra LLM call) and reliable.

    Args:
        intent: the classified intent for the user's message.

    Returns:
        The agent name (e.g., "coding", "research", "browser", "direct").

    Raises:
        KeyError: if the intent has no mapping (shouldn't happen — all
            Intent enum values are mapped above).
    """
    name = _INTENT_TO_AGENT.get(intent)
    if name is None:
        logger.warning(
            "[agents.selection] no mapping for intent %s — defaulting to 'direct'",
            intent.value,
        )
        return "direct"
    return name


def select_agent(intent: Intent) -> Optional[type]:
    """
    Look up the agent class for an intent.

    Convenience wrapper: maps intent → name → agent class via the
    registry. Returns None if the mapped agent isn't registered (shouldn't
    happen — all 4 agents are auto-registered at import time).

    Args:
        intent: the classified intent for the user's message.

    Returns:
        The agent class (a BaseAgent subclass), or None if not found.
    """
    name = intent_to_agent_name(intent)
    return get_agent(name)


def list_intent_mappings() -> list[tuple[Intent, str]]:
    """Return all (intent, agent_name) pairs. For documentation / UI."""
    return list(_INTENT_TO_AGENT.items())
