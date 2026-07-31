"""
Tests for ADR-8 Phase 1 (Session 34): agents as directories.

Locks in the structural refactor introduced in Session 34 Phase 1:
    - Each agent class lives INSIDE its directory at agents/<name>/agent.py
    - Each agents/<name>/__init__.py re-exports the class
    - The backward-compat shim agents/<name>_agent.py still works
    - The shim re-exports the SAME class object (identity check)
    - The registry auto_discovers all 4 built-in agents on package import
    - The auto_discover helper registers agents under their directory name

Per ADR-8 Principle 5: agents are directories, not modules. This test
file codifies that structural invariant so a future agent that breaks
the layout (e.g., drops the agent.py file, or removes the __init__.py
re-export) fails loudly here rather than silently breaking the
registry at runtime.
"""

from __future__ import annotations

import importlib

import pytest

# ── Directory layout: each agent has agent.py + __init__ re-export ─────────


@pytest.mark.parametrize(
    "agent_name,agent_class_name",
    [
        ("coding", "CodingAgent"),
        ("research", "ResearchAgent"),
        ("browser", "BrowserAgent"),
        ("direct", "DirectAgent"),
    ],
)
def test_agent_directory_has_agent_py(agent_name, agent_class_name):
    """Each agent directory must have an agent.py with the expected class."""
    mod = importlib.import_module(f"agents.{agent_name}.agent")
    assert hasattr(mod, agent_class_name), (
        f"agents.{agent_name}.agent must define {agent_class_name}"
    )


@pytest.mark.parametrize(
    "agent_name,agent_class_name",
    [
        ("coding", "CodingAgent"),
        ("research", "ResearchAgent"),
        ("browser", "BrowserAgent"),
        ("direct", "DirectAgent"),
    ],
)
def test_agent_subpackage_re_exports_class(agent_name, agent_class_name):
    """The agents/<name>/__init__.py re-exports the class for convenience."""
    subpkg = importlib.import_module(f"agents.{agent_name}")
    assert hasattr(subpkg, agent_class_name), (
        f"agents.{agent_name} (subpackage __init__) must re-export {agent_class_name}"
    )


# ── Backward-compat shims: agents/<name>_agent.py still works ─────────────


@pytest.mark.parametrize(
    "shim_path,agent_class_name",
    [
        ("agents.coding_agent", "CodingAgent"),
        ("agents.research_agent", "ResearchAgent"),
        ("agents.browser_agent", "BrowserAgent"),
        ("agents.direct_agent", "DirectAgent"),
    ],
)
def test_backward_compat_shim_imports(shim_path, agent_class_name):
    """The legacy module path still imports the class (backward compat)."""
    mod = importlib.import_module(shim_path)
    assert hasattr(mod, agent_class_name), (
        f"{shim_path} must re-export {agent_class_name} for backward compat"
    )


@pytest.mark.parametrize(
    "shim_path,canonical_path,agent_class_name",
    [
        ("agents.coding_agent", "agents.coding.agent", "CodingAgent"),
        ("agents.research_agent", "agents.research.agent", "ResearchAgent"),
        ("agents.browser_agent", "agents.browser.agent", "BrowserAgent"),
        ("agents.direct_agent", "agents.direct.agent", "DirectAgent"),
    ],
)
def test_shim_identity_matches_canonical(shim_path, canonical_path, agent_class_name):
    """The shim must re-export the SAME class object (identity, not a copy)."""
    shim_cls = getattr(importlib.import_module(shim_path), agent_class_name)
    canonical_cls = getattr(importlib.import_module(canonical_path), agent_class_name)
    assert shim_cls is canonical_cls, (
        f"{shim_path}.{agent_class_name} must be the same object as "
        f"{canonical_path}.{agent_class_name} (identity, not a re-definition)"
    )


# ── Registry auto-discovery ───────────────────────────────────────────────


def test_registry_auto_discovers_all_built_in_agents():
    """The auto_discover_agents() helper registers all 5 built-in agents."""
    from agents import list_agents
    from agents.registry import auto_discover_agents

    # Reset the registry by re-running auto-discover on a fresh import.
    # The auto_discover helper is idempotent — re-running it on the same
    # package is a no-op (same class registered under same name).
    count = auto_discover_agents()
    assert count == 5, (
        f"auto_discover_agents should find 5 agents (coding, research, "
        f"browser, direct, verifier); found {count}"
    )

    registered_names = {name for name, _ in list_agents()}
    assert {"coding", "research", "browser", "direct", "verifier"}.issubset(registered_names), (
        f"all 5 built-in agent names should be in registry; got {registered_names}"
    )


@pytest.mark.parametrize(
    "agent_name,expected_class_name",
    [
        ("coding", "CodingAgent"),
        ("research", "ResearchAgent"),
        ("browser", "BrowserAgent"),
        ("direct", "DirectAgent"),
    ],
)
def test_registry_lookup_returns_directory_agent_class(agent_name, expected_class_name):
    """get_agent(name) returns the class from agents/<name>/agent.py."""
    from agents import get_agent

    cls = get_agent(agent_name)
    assert cls is not None, f"agent {agent_name!r} not registered"
    assert cls.__name__ == expected_class_name, (
        f"get_agent({agent_name!r}) returned {cls.__name__}; expected {expected_class_name}"
    )


# ── Adding a new agent = adding a new directory (no registry edit) ────────


def test_auto_discover_picks_up_new_directory_agent(tmp_path, monkeypatch):
    """
    ADR-8 Principle 5: adding a new agent = adding a new directory under
    agents/ with an agent.py file. The registry auto-discovers it without
    manual register() calls.

    This test creates a fake agent package on a temporary path, points
    the auto_discover helper at it, and verifies the agent gets picked
    up under its directory name.
    """
    import sys
    from pathlib import Path

    # Create a fake agents package on tmp_path
    fake_pkg = tmp_path / "fake_agents_pkg"
    fake_pkg.mkdir()
    (fake_pkg / "__init__.py").write_text("")

    # Create a fake agent directory with an agent.py
    fake_agent_dir = fake_pkg / "weather"
    fake_agent_dir.mkdir()
    (fake_agent_dir / "__init__.py").write_text(
        "from fake_agents_pkg.weather.agent import WeatherAgent\n"
        "__all__ = ['WeatherAgent']\n"
    )
    (fake_agent_dir / "agent.py").write_text(
        "class WeatherAgent:\n"
        "    pass\n"
    )

    # Make the fake package importable. Clear any stale sys.modules
    # entries from prior runs so importlib re-imports from tmp_path.
    monkeypatch.syspath_prepend(str(tmp_path))
    for mod_name in list(sys.modules):
        if mod_name == "fake_agents_pkg" or mod_name.startswith("fake_agents_pkg."):
            monkeypatch.setitem(sys.modules, mod_name, None)
            # importlib.import_module will reload on next import

    # Run auto_discover against the fake package
    from agents.registry import auto_discover_agents, get_agent, _REGISTRY

    # Save registry state and clear for this test
    saved = dict(_REGISTRY)
    try:
        count = auto_discover_agents(package="fake_agents_pkg")
        assert count == 1, f"expected 1 agent discovered; got {count}"
        assert get_agent("weather") is not None, "weather agent should be registered"
    finally:
        # Restore registry state
        _REGISTRY.clear()
        _REGISTRY.update(saved)
