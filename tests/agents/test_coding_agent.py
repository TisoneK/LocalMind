"""
Tests for the CodingAgent — the second concrete BaseAgent subclass.

Locks in the ADR-6 structural skeleton for the coding agent:
    - CodingAgent is registered under "coding"
    - CodingAgent config has the right name, scoped tools, and caps
    - CodingAgent's scoped_tools() filters out non-coding tools
    - CODING_TOOLS is a subset of AGENT_ALLOWED_TOOLS
    - description is concrete enough for a small model (ADR-6 point 6)
    - build_context returns a string with the agent-type header
    - is_done returns (False, "") in Phase 1
"""

from __future__ import annotations

from agents import CodingAgent, get_agent, is_registered
from agents.base_agent import DEFAULT_MAX_ITERATIONS, DEFAULT_MAX_WALL_CLOCK_SECS
from agents.coding import CODING_TOOLS, build_coding_context, is_coding_done
from core.agent.constants import AGENT_ALLOWED_TOOLS
from core.models import Intent

# ── CodingAgent interface ────────────────────────────────────────────────────


def test_coding_agent_config():
    """CodingAgent's config has the right name, scoped tools, and caps."""
    agent = CodingAgent(adapter=None)
    cfg = agent.config()
    assert cfg.name == "coding"
    assert cfg.tools_enabled is True
    # Scoped toolset: 5 coding tools, not the full AGENT_ALLOWED_TOOLS
    assert cfg.allowed_tools == CODING_TOOLS
    assert cfg.allowed_tools == frozenset(
        {"shell", "file_task", "file_write", "edit_file", "code_exec"}
    )
    assert cfg.allowed_tools.issubset(AGENT_ALLOWED_TOOLS)
    # Coding tasks need more iterations than browser tasks
    assert cfg.max_iterations >= DEFAULT_MAX_ITERATIONS
    assert cfg.max_wall_clock_secs >= DEFAULT_MAX_WALL_CLOCK_SECS


def test_coding_agent_description_is_concrete():
    """The description must be concrete enough for a small model to pick
    the right agent (ADR-6 point 6)."""
    agent = CodingAgent(adapter=None)
    desc = agent.description()
    assert len(desc) > 50, "description too short — small model won't disambiguate"
    assert "coding" in desc.lower() or "code" in desc.lower()
    assert "shell" in desc.lower() or "file" in desc.lower()
    # Must mention what it CAN'T do — scoped toolset
    assert "cannot" in desc.lower() or "scoped" in desc.lower()


def test_coding_agent_build_context_returns_string():
    """build_context returns a non-empty string with the coding workflow.

    ADR-8 Phase 2 (Session 34): build_context() now loads the coding
    workflow from agents/coding/workflow.md (was a static header in
    Phase 1). The workflow's "## Coding Workflow" section appears in
    the context string along with the constraints (read-before-write,
    verify-after-write, follow-conventions, small-verifiable-changes).
    """
    agent = CodingAgent(adapter=None)
    ctx = agent.build_context(
        messages=[{"role": "user", "content": "fix the bug in app.py"}],
        intent=Intent.SHELL,
        memory_facts=["user prefers Python 3.12"],
    )
    assert isinstance(ctx, str)
    # Phase 2: the workflow file is loaded — its section header appears
    assert "Coding Workflow" in ctx
    # Phase 2: the workflow's constraints reach the context
    assert "Read before writing" in ctx
    assert "Verify after writing" in ctx
    assert "Python 3.12" in ctx  # memory facts are included
    # Must mention the workspace state feedback loop (ADR-5 differentiator)
    assert "workspace" in ctx.lower() or "git" in ctx.lower()


def test_coding_agent_is_done_returns_false_in_phase1():
    """Phase 1: is_done always returns (False, '') — the existing AgentLoop
    handles termination. Phase 2 will add coding-specific stop conditions."""
    agent = CodingAgent(adapter=None)
    done, reason = agent.is_done(
        iterations=5,
        wall_clock_secs=120.0,
        last_tool_result=None,
        trace=None,
    )
    assert done is False
    assert reason == ""


def test_coding_agent_scoped_tools_filters_non_coding():
    """scoped_tools() filters the global tool list down to coding-only."""
    agent = CodingAgent(adapter=None)
    all_tools = [
        {"intent": "shell", "description": "shell"},
        {"intent": "file_task", "description": "file read"},
        {"intent": "file_write", "description": "file write"},
        {"intent": "edit_file", "description": "file edit"},
        {"intent": "code_exec", "description": "code exec"},
        {"intent": "web_search", "description": "web search"},
        {"intent": "web_fetch", "description": "web fetch"},
        {"intent": "browse", "description": "browser"},
        {"intent": "memory_op", "description": "memory"},
        {"intent": "sysinfo", "description": "sysinfo"},
    ]
    scoped = agent.scoped_tools(all_tools)
    scoped_intents = {t["intent"] for t in scoped}
    assert scoped_intents == CODING_TOOLS
    assert len(scoped) == 5
    # Must NOT include web/browser/memory/sysinfo tools
    assert "web_search" not in scoped_intents
    assert "web_fetch" not in scoped_intents
    assert "browse" not in scoped_intents
    assert "memory_op" not in scoped_intents
    assert "sysinfo" not in scoped_intents


def test_coding_agent_scoped_tools_empty_input():
    """scoped_tools() handles an empty input list."""
    agent = CodingAgent(adapter=None)
    assert agent.scoped_tools([]) == []


# ── Registry ─────────────────────────────────────────────────────────────────


def test_registry_coding_is_registered():
    """CodingAgent is auto-registered under 'coding' at import time."""
    assert is_registered("coding")
    assert get_agent("coding") is CodingAgent


def test_registry_has_both_browser_and_coding():
    """list_agents() returns both browser and coding agents."""
    from agents import list_agents

    names = [name for name, _ in list_agents()]
    assert "browser" in names
    assert "coding" in names
    assert len(names) >= 2


# ── Coding subpackage ────────────────────────────────────────────────────────


def test_coding_tools_is_subset_of_agent_allowed():
    """CODING_TOOLS must be a subset of AGENT_ALLOWED_TOOLS — the assertion
    in coding/tools.py catches this at import time, but the test documents
    the invariant explicitly."""
    assert CODING_TOOLS.issubset(AGENT_ALLOWED_TOOLS)


def test_coding_tools_has_five_tools():
    """The coding agent's scoped toolset is exactly 5 tools."""
    assert len(CODING_TOOLS) == 5
    assert CODING_TOOLS == frozenset(
        {"shell", "file_task", "file_write", "edit_file", "code_exec"}
    )


def test_coding_tools_excludes_web_and_browser():
    """CODING_TOOLS must NOT include web/browser/memory/sysinfo tools."""
    assert "web_search" not in CODING_TOOLS
    assert "web_fetch" not in CODING_TOOLS
    assert "browse" not in CODING_TOOLS
    assert "memory_op" not in CODING_TOOLS
    assert "sysinfo" not in CODING_TOOLS


def test_build_coding_context_includes_memory_facts():
    """build_coding_context includes provided memory facts (capped)."""
    facts = [f"fact {i}" for i in range(20)]
    ctx = build_coding_context(messages=[], intent=Intent.SHELL, memory_facts=facts)
    # Only the first 10 facts are included (cap to avoid context bloat)
    assert "fact 0" in ctx
    assert "fact 9" in ctx
    assert "fact 10" not in ctx


def test_build_coding_context_includes_orchestrator_plan():
    """build_coding_context includes the orchestrator plan if provided."""
    ctx = build_coding_context(
        messages=[],
        intent=Intent.SHELL,
        orchestrator_context="Step 1: read file\nStep 2: fix bug\nStep 3: run tests",
    )
    assert "Orchestrator Plan" in ctx
    assert "Step 1: read file" in ctx


def test_build_coding_context_mentions_workspace_state():
    """build_coding_context mentions the workspace state feedback loop
    (ADR-5 differentiator — the coding agent benefits most from it)."""
    ctx = build_coding_context(messages=[], intent=Intent.SHELL)
    assert "workspace" in ctx.lower() or "git" in ctx.lower()


def test_is_coding_done_phase1_always_false():
    """Phase 1: is_coding_done always returns (False, '')."""
    assert is_coding_done(0, 0.0, None, None) == (False, "")
    assert is_coding_done(100, 1000.0, None, None) == (False, "")


# ── CodingAgent vs BrowserAgent comparison ───────────────────────────────────


def test_coding_and_browser_have_different_toolsets():
    """CodingAgent and BrowserAgent have disjoint toolsets (ADR-6 scoped tools)."""
    from agents.browser import BROWSER_TOOLS

    coding = CodingAgent(adapter=None)
    assert coding.config().allowed_tools != BROWSER_TOOLS
    # Disjoint: no overlap between coding tools and browser tools
    assert coding.config().allowed_tools.isdisjoint(BROWSER_TOOLS)


def test_coding_agent_has_more_iterations_than_browser():
    """Coding tasks need more iterations than browser tasks."""
    from agents.browser_agent import BrowserAgent

    coding = CodingAgent(adapter=None)
    browser = BrowserAgent(adapter=None)
    assert coding.config().max_iterations > browser.config().max_iterations
    assert coding.config().max_wall_clock_secs > browser.config().max_wall_clock_secs
