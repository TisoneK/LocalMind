"""
Tests for ADR-6 scoped-tool filtering in AgentLoop.

Verifies that _filtered_tool_defs() respects the allowed_tools parameter,
so a coding agent sees only 5 tools, a browser agent sees only 1, etc.
"""

from __future__ import annotations

from agents.browser import BROWSER_TOOLS
from agents.coding import CODING_TOOLS
from agents.research import RESEARCH_TOOLS
from core.agent.constants import AGENT_ALLOWED_TOOLS
from core.agent.loop import _filtered_tool_defs


def test_filtered_tool_defs_default_uses_global_allowlist():
    """_filtered_tool_defs() with no arg uses AGENT_ALLOWED_TOOLS."""
    tools = _filtered_tool_defs()
    tool_names = {td["function"]["name"] for td in tools}
    assert tool_names.issubset(AGENT_ALLOWED_TOOLS)


def test_filtered_tool_defs_with_coding_scope():
    """_filtered_tool_defs(CODING_TOOLS) returns only the 5 coding tools."""
    tools = _filtered_tool_defs(CODING_TOOLS)
    tool_names = {td["function"]["name"] for td in tools}
    assert tool_names.issubset(CODING_TOOLS)
    # Should be exactly the coding tools that are registered
    assert tool_names == CODING_TOOLS


def test_filtered_tool_defs_with_browser_scope():
    """_filtered_tool_defs(BROWSER_TOOLS) returns only the browser tool."""
    tools = _filtered_tool_defs(BROWSER_TOOLS)
    tool_names = {td["function"]["name"] for td in tools}
    assert tool_names.issubset(BROWSER_TOOLS)


def test_filtered_tool_defs_with_research_scope():
    """_filtered_tool_defs(RESEARCH_TOOLS) returns only research tools."""
    tools = _filtered_tool_defs(RESEARCH_TOOLS)
    tool_names = {td["function"]["name"] for td in tools}
    assert tool_names.issubset(RESEARCH_TOOLS)


def test_filtered_tool_defs_empty_set():
    """_filtered_tool_defs(frozenset()) returns no tools (direct agent)."""
    tools = _filtered_tool_defs(frozenset())
    assert tools == []


def test_coding_scope_smaller_than_global():
    """CODING_TOOLS is a strict subset of AGENT_ALLOWED_TOOLS (ADR-6 value)."""
    assert CODING_TOOLS.issubset(AGENT_ALLOWED_TOOLS)
    assert len(CODING_TOOLS) < len(AGENT_ALLOWED_TOOLS)


def test_browser_scope_smaller_than_coding():
    """Browser has fewer tools than coding (1 vs 5)."""
    assert len(BROWSER_TOOLS) < len(CODING_TOOLS)
