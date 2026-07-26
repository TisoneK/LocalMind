"""
Agent registry — name → agent class.

Per ADR-6: the intent router / UI picker selects an agent by name from
this registry, rather than an if/else buried in a chat handler. Direct
Mode vs Agent Mode becomes a registry lookup: DirectAgent vs the user-
selected agent.

Phase 1 (this session, Session 15): only BrowserAgent is registered.
The existing AgentLoop continues to handle all other traffic. Adding
CodingAgent, ResearchAgent, DirectAgent in future sessions is a matter
of subclassing BaseAgent and calling register() here.

Usage:
    from agents.registry import get_agent, list_agents, register

    # Register a new agent (done at module import time in agents/__init__.py)
    register("browser", BrowserAgent)

    # Look up an agent by name (the UI picker / intent router does this)
    agent_class = get_agent("browser")
    agent = agent_class(adapter=some_adapter)

    # List all registered agents (the UI picker shows these)
    for name, cls in list_agents():
        print(f"{name}: {cls().description()}")
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# The registry: name → agent class (not instance). Instances are
# constructed on demand with the current adapter.
_REGISTRY: dict[str, type] = {}


def register(name: str, agent_class: type) -> None:
    """Register an agent class under a name.

    Args:
        name: the agent's short name (e.g., "browser", "coding",
            "research", "direct"). Used as the registry key — the UI
            picker and intent router look up agents by this name.
        agent_class: the agent class (a BaseAgent subclass). Constructed
            on demand with the current adapter.

    Raises:
        ValueError: if the name is already registered with a different
            class. Re-registering the same class under the same name is
            a no-op (idempotent — useful for hot-reload during dev).
    """
    existing = _REGISTRY.get(name)
    if existing is not None and existing is not agent_class:
        raise ValueError(
            f"agent name {name!r} is already registered to {existing.__name__}; "
            f"refusing to overwrite with {agent_class.__name__}"
        )
    _REGISTRY[name] = agent_class
    logger.debug("[agents.registry] registered %s → %s", name, agent_class.__name__)


def get_agent(name: str) -> Optional[type]:
    """Look up an agent class by name. Returns None if not registered."""
    return _REGISTRY.get(name)


def list_agents() -> list[tuple[str, type]]:
    """Return all registered (name, agent_class) pairs. For UI pickers."""
    return list(_REGISTRY.items())


def is_registered(name: str) -> bool:
    """Check whether an agent name is registered."""
    return name in _REGISTRY
