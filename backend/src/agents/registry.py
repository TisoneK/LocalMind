"""
Agent registry — name → agent class.

The intent router / UI picker selects an agent by name from
this registry, rather than an if/else buried in a chat handler. Direct
Mode vs Agent Mode becomes a registry lookup: DirectAgent vs the user-
selected agent.

The registry auto-discovers
agent directories under `agents/` that contain an `agent.py` file. Each
such directory's `__init__.py` re-exports the agent class. Adding a new
agent = adding a new directory under `agents/` with an `agent.py` file —
no manual `register()` call needed. The manual `register()` API is
retained for backward compatibility and for programmatic registration
of non-standard agents (test doubles, custom user agents, etc.).

Usage:
    from agents.registry import get_agent, list_agents, register,
        auto_discover_agents

    # Auto-discover all agents in agents/* subdirectories with agent.py
    auto_discover_agents()

    # Or register a new agent manually (done at module import time in
    # agents/__init__.py for backward-compat with non-conforming agents)
    register("browser", BrowserAgent)

    # Look up an agent by name (the UI picker / intent router does this)
    agent_class = get_agent("browser")
    agent = agent_class(adapter=some_adapter)

    # List all registered agents (the UI picker shows these)
    for name, cls in list_agents():
        print(f"{name}: {cls().description()}")
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
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


def auto_discover_agents(package: str = "agents") -> int:
    """Auto-discover agent directories and register their classes.

    Scans `agents/` for
    subdirectories that contain an `agent.py` module. Each such
    directory's `__init__.py` is expected to re-export the agent class
    (e.g., `agents/coding/__init__.py` re-exports `CodingAgent`). This
    function imports each subpackage and looks for a class whose name
    matches the directory (capitalized + "Agent" suffix). If found, it
    is registered under the directory name.

    Adding a new agent = adding a new directory under `agents/` with an
    `agent.py` file and an `__init__.py` that re-exports the class. No
    manual `register()` call needed.

    Args:
        package: the package name to scan (default "agents"). Used for
            test injection — production always uses "agents".

    Returns:
        The number of agents registered (for logging / testing).
    """
    try:
        pkg = importlib.import_module(package)
    except ImportError as exc:
        logger.warning("[agents.registry] auto_discover: package %r not found: %s", package, exc)
        return 0

    if not hasattr(pkg, "__path__"):
        # Not a package (no __path__) — nothing to scan
        return 0

    count = 0
    for _finder, name, is_pkg in pkgutil.iter_modules(pkg.__path__):
        if not is_pkg:
            continue  # skip standalone modules — only directories
        # Import the subpackage and look for an `agent` submodule
        subpkg_full = f"{package}.{name}"
        try:
            importlib.import_module(subpkg_full)
        except Exception as exc:
            logger.warning("[agents.registry] auto_discover: skipping %r (%s)", subpkg_full, exc)
            continue
        # Try to import the .agent submodule
        try:
            agent_mod = importlib.import_module(f"{subpkg_full}.agent")
        except ImportError:
            # No agent.py in this subpackage — skip silently
            continue
        except Exception as exc:
            logger.warning("[agents.registry] auto_discover: %s.agent import failed: %s", subpkg_full, exc)
            continue
        # Find the class whose name matches <Name>Agent (capitalized dir name + "Agent")
        expected_class_name = name.capitalize() + "Agent"
        agent_class = getattr(agent_mod, expected_class_name, None)
        if agent_class is None:
            # Fallback: scan the module for any BaseAgent subclass
            from agents.base_agent import BaseAgent  # local import — avoids cycle at module load
            for attr_name in dir(agent_mod):
                attr = getattr(agent_mod, attr_name)
                if isinstance(attr, type) and issubclass(attr, BaseAgent) and attr is not BaseAgent:
                    agent_class = attr
                    break
        if agent_class is None:
            logger.warning(
                "[agents.registry] auto_discover: %s.agent has no %s class — skipping",
                subpkg_full, expected_class_name,
            )
            continue
        register(name, agent_class)
        count += 1
    logger.debug("[agents.registry] auto_discover: registered %d agents from %s", count, package)
    return count


def get_agent(name: str) -> Optional[type]:
    """Look up an agent class by name. Returns None if not registered."""
    return _REGISTRY.get(name)


def list_agents() -> list[tuple[str, type]]:
    """Return all registered (name, agent_class) pairs. For UI pickers."""
    return list(_REGISTRY.items())


def is_registered(name: str) -> bool:
    """Check whether an agent name is registered."""
    return name in _REGISTRY
