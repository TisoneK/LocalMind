"""
Tests for the agents package — BaseAgent interface, registry, BrowserAgent.

Locks in the ADR-6 structural skeleton introduced in Session 15:
    - BaseAgent is abstract; can't be instantiated directly
    - BrowserAgent supplies browser-specific config, context, is_done
    - BrowserAgent's scoped_tools() filters out non-browser tools
    - registry register/get/list/is_registered work as documented
    - the browser agent's BROWSER_TOOLS is a subset of AGENT_ALLOWED_TOOLS
"""

from __future__ import annotations

import pytest

from agents import (
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_MAX_WALL_CLOCK_SECS,
    AgentConfig,
    BaseAgent,
    BrowserAgent,
    get_agent,
    is_registered,
    list_agents,
    register,
)
from agents.browser import BROWSER_TOOLS, build_browser_context, is_browser_done
from core.agent.constants import AGENT_ALLOWED_TOOLS
from core.models import Intent

# ── BaseAgent is abstract ────────────────────────────────────────────────────


def test_base_agent_is_abstract():
    """BaseAgent has abstract methods; can't be instantiated directly."""
    with pytest.raises(TypeError):
        BaseAgent(adapter=None)  # type: ignore[abstract]


# ── AgentConfig defaults ─────────────────────────────────────────────────────


def test_agent_config_defaults():
    """The default AgentConfig has sensible caps and the full tool allowlist."""
    cfg = AgentConfig(name="test")
    assert cfg.name == "test"
    assert cfg.max_iterations == DEFAULT_MAX_ITERATIONS
    assert cfg.max_wall_clock_secs == DEFAULT_MAX_WALL_CLOCK_SECS
    assert cfg.tools_enabled is True
    assert cfg.allowed_tools == AGENT_ALLOWED_TOOLS


# ── BrowserAgent interface ───────────────────────────────────────────────────


def test_browser_agent_config():
    """BrowserAgent's config has the right name, scoped tools, and caps."""
    agent = BrowserAgent(adapter=None)
    cfg = agent.config()
    assert cfg.name == "browser"
    assert cfg.tools_enabled is True
    # Scoped toolset: only Intent.BROWSE, not the full AGENT_ALLOWED_TOOLS
    assert cfg.allowed_tools == BROWSER_TOOLS
    assert cfg.allowed_tools == frozenset({Intent.BROWSE.value})
    assert cfg.allowed_tools.issubset(AGENT_ALLOWED_TOOLS)
    # Browser tasks are slow but rarely need many iterations
    assert cfg.max_iterations < DEFAULT_MAX_ITERATIONS
    assert cfg.max_wall_clock_secs < DEFAULT_MAX_WALL_CLOCK_SECS


def test_browser_agent_description_is_concrete():
    """The description must be concrete enough for a small model to pick
    the right agent (ADR-6 point 6 — tool/agent descriptions are the real
    design risk on gemma3:1b-class hardware)."""
    agent = BrowserAgent(adapter=None)
    desc = agent.description()
    assert len(desc) > 50, "description too short — small model won't disambiguate"
    assert "browser" in desc.lower()
    assert "click" in desc.lower() or "navigate" in desc.lower()
    # Must mention what it CAN'T do — scoped toolset
    assert "cannot" in desc.lower() or "scoped" in desc.lower()


def test_browser_agent_build_context_returns_string():
    """build_context returns a non-empty string with the agent-type header."""
    agent = BrowserAgent(adapter=None)
    ctx = agent.build_context(
        messages=[{"role": "user", "content": "open https://example.com"}],
        intent=Intent.BROWSE,
        memory_facts=["user prefers dark mode"],
    )
    assert isinstance(ctx, str)
    assert "Browser Agent" in ctx
    assert "dark mode" in ctx  # memory facts are included


def test_browser_agent_is_done_returns_false_in_phase1():
    """Phase 1: is_done always returns (False, '') — the existing AgentLoop
    handles termination. Phase 2 will add browser-specific stop conditions."""
    agent = BrowserAgent(adapter=None)
    done, reason = agent.is_done(
        iterations=5,
        wall_clock_secs=120.0,
        last_tool_result=None,
        trace=None,
    )
    assert done is False
    assert reason == ""


def test_browser_agent_scoped_tools_filters_non_browser():
    """scoped_tools() filters the global tool list down to browser-only."""
    agent = BrowserAgent(adapter=None)
    all_tools = [
        {"intent": "browse", "description": "browser"},
        {"intent": "shell", "description": "shell"},
        {"intent": "code_exec", "description": "code"},
        {"intent": "file_task", "description": "file read"},
        {"intent": "web_search", "description": "search"},
    ]
    scoped = agent.scoped_tools(all_tools)
    assert len(scoped) == 1
    assert scoped[0]["intent"] == "browse"


def test_browser_agent_scoped_tools_empty_input():
    """scoped_tools() handles an empty input list."""
    agent = BrowserAgent(adapter=None)
    assert agent.scoped_tools([]) == []


# ── Registry ─────────────────────────────────────────────────────────────────


def test_registry_browser_is_registered():
    """BrowserAgent is auto-registered under 'browser' at import time."""
    assert is_registered("browser")
    assert get_agent("browser") is BrowserAgent


def test_registry_list_agents_includes_browser():
    """list_agents() returns the browser agent."""
    agents = list_agents()
    names = [name for name, _ in agents]
    assert "browser" in names


def test_registry_register_idempotent():
    """Re-registering the same class under the same name is a no-op."""
    register("browser", BrowserAgent)  # should not raise
    assert get_agent("browser") is BrowserAgent


def test_registry_register_conflict_raises():
    """Registering a different class under an existing name raises ValueError."""
    # Define a throwaway agent class to conflict with
    class FakeAgent(BaseAgent):
        def config(self):
            return AgentConfig(name="fake")

        def build_context(self, **kwargs):
            return ""

        def is_done(self, **kwargs):
            return False, ""

        def description(self):
            return "fake"

    with pytest.raises(ValueError, match="already registered"):
        register("browser", FakeAgent)


def test_registry_get_unknown_returns_none():
    """Looking up an unregistered name returns None."""
    assert get_agent("nonexistent-agent") is None


def test_registry_is_registered_unknown_returns_false():
    """is_registered returns False for unregistered names."""
    assert is_registered("nonexistent-agent") is False


# ── Browser subpackage ───────────────────────────────────────────────────────


def test_browser_tools_is_subset_of_agent_allowed():
    """BROWSER_TOOLS must be a subset of AGENT_ALLOWED_TOOLS — the assertion
    in browser/tools.py catches this at import time, but the test documents
    the invariant explicitly."""
    assert BROWSER_TOOLS.issubset(AGENT_ALLOWED_TOOLS)


def test_browser_tools_only_browse():
    """The browser agent's scoped toolset is exactly one tool: Intent.BROWSE."""
    assert BROWSER_TOOLS == frozenset({Intent.BROWSE.value})


def test_build_browser_context_includes_memory_facts():
    """build_browser_context includes provided memory facts (capped)."""
    facts = [f"fact {i}" for i in range(20)]
    ctx = build_browser_context(messages=[], intent=Intent.BROWSE, memory_facts=facts)
    # Only the first 10 facts are included (cap to avoid context bloat)
    assert "fact 0" in ctx
    assert "fact 9" in ctx
    assert "fact 10" not in ctx


def test_build_browser_context_includes_orchestrator_plan():
    """build_browser_context includes the orchestrator plan if provided."""
    ctx = build_browser_context(
        messages=[],
        intent=Intent.BROWSE,
        orchestrator_context="Step 1: open URL\nStep 2: click button",
    )
    assert "Orchestrator Plan" in ctx
    assert "Step 1: open URL" in ctx


def test_is_browser_done_phase1_always_false():
    """Phase 1: is_browser_done always returns (False, '')."""
    assert is_browser_done(0, 0.0, None, None) == (False, "")
    assert is_browser_done(100, 1000.0, None, None) == (False, "")
