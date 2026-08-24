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

The parent runtime does not use this module for request-time routing.
It remains a registry lookup utility for UI metadata and explicit child-agent
selection; the parent delegates through the native delegation tools.

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
    Intent.FIND_PATH: "coding",  # Session 125: name-match search routes to coding
    Intent.SYSTEM_SEARCH: "coding",  # Session 400: unified local search routes to coding
    Intent.FILE_WRITE: "coding",
    Intent.FILE_EDIT: "coding",
    Intent.CODE_EXEC: "coding",
    Intent.WEB_SEARCH: "research",
    Intent.WEB_FETCH: "research",
    Intent.BROWSE: "browser",
    Intent.CHAT: "direct",
    Intent.SYSINFO: "coding",
    Intent.OBSERVE: "coding",  # B-2026-07-31-9: desktop awareness routes to coding (observe tool)
    Intent.CALCULATE: "coding",  # B-2026-07-31-10: safe arithmetic routes to coding (calculator)
    Intent.CSV: "coding",  # B-2026-07-31-10: CSV parsing routes to coding
    Intent.JSON: "coding",  # B-2026-07-31-10: JSON parse/query routes to coding
    Intent.SQL: "coding",  # B-2026-07-31-10: SQLite queries route to coding
    Intent.MEMORY_OP: "coding",
    Intent.GIT: "coding",  # Session 41: git operations route to coding agent
    Intent.PROCESS: "coding",  # Session 42: process management routes to coding agent
    Intent.GREP_SEARCH: "coding",  # B-2026-08-23-31: grep search routes to coding agent
    Intent.VERIFY: "verifier",  # Session 43: verification routes to VerifierAgent
    Intent.REVIEW: "reviewer",  # Session 44: code review routes to ReviewerAgent
    Intent.DEBUG: "debugger",  # Session 45: debugging routes to DebuggerAgent
    Intent.ANALYZE: "analyst",  # Session 46: analysis routes to AnalystAgent
    Intent.DIAGNOSTICS: "coding",  # Session 49: diagnostics routes to coding agent
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


# ── Registry metadata selection ────────────────────────────────────────────
#
# The parent runtime does not classify user turns into these mappings. The
# helpers remain useful for UI metadata and explicit child-agent selection.
# They classify by task type rather than by individual tool:
# "browse", "web_fetch", "file_analysis", "system_info",
# "shell_command" — these map to AGENTS (not intents). This is the
# Phase 4 routing key.
#
# The request runtime intentionally has no pre-classification stage.

# Map primary_domain → agent name. When primary_domain is set
# (non-empty), it takes precedence over the intent-based map.
_DOMAIN_TO_AGENT: dict[str, str] = {
    "browse": "browser",
    "web_fetch": "research",
    "web_search": "research",
    "file_analysis": "coding",  # file reading/analysis is a coding task
    "file_edit": "coding",
    "file_write": "coding",
    "system_info": "coding",  # sysinfo is shell-adjacent; coding agent handles it
    "observe": "coding",  # B-2026-07-31-9: desktop awareness — coding agent owns the observe tool
    "shell_command": "coding",
    "code_exec": "coding",
    "memory_op": "coding",
    "chat": "direct",
    "direct": "direct",
    "verify": "verifier",  # Session 43: verification tasks route to VerifierAgent
    "review": "reviewer",  # Session 44: code review tasks route to ReviewerAgent
    "debug": "debugger",  # Session 45: debugging tasks route to DebuggerAgent
    "analyze": "analyst",  # Session 46: analysis tasks route to AnalystAgent
}


def primary_domain_to_agent_name(primary_domain: str) -> Optional[str]:
    """Map a task-type primary_domain value to an agent name.

    When a caller provides a task type (e.g., "shell_command",
    "web_fetch", "browse"), this function maps it to the appropriate
    agent. Returns None for unknown/empty domains (caller falls back to
    intent-based selection).

    Args:
        primary_domain: the task-type string. May be empty.

    Returns:
        The agent name (e.g., "coding", "research"), or None if the
        domain isn't in the map.
    """
    if not primary_domain:
        return None
    return _DOMAIN_TO_AGENT.get(primary_domain)


def select_agent_by_task_profile(
    primary_domain: str,
    fallback_intent: Intent,
) -> Optional[type]:
    """ADR-8 Phase 4: select an agent by task type (primary_domain),
    falling back to intent-based selection.

    Per ADR-8 Principle 1: "Classification by task type, not tool." The
    primary_domain is the task-type
    signal. When available, it takes precedence over the intent-based
    map. When unavailable (empty or unknown), fall back to the intent-
    based map (Phase 1-3 behavior).

    Args:
        primary_domain: the task-type string. May be empty.
        fallback_intent: the Intent derived from the task profile
            (used when primary_domain is empty or unknown).

    Returns:
        The agent class, or None if neither path resolves.
    """
    # Try task-type-based selection first (Phase 4)
    name = primary_domain_to_agent_name(primary_domain)
    if name is None:
        # Fall back to intent-based selection (Phase 1-3)
        name = intent_to_agent_name(fallback_intent)
    return get_agent(name)
