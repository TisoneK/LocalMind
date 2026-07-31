"""
Tests for ADR-8 Phase 3 (Session 34): agent-initiated delegation.

Tests the `delegate` tool — the primitive that lets any agent with
`delegate` in its toolset delegate a sub-task to another agent.

Locks in:
    - The delegate tool is registered (Intent.DELEGATE → handler)
    - The delegate tool is in AGENT_ALLOWED_TOOLS
    - The delegate tool is in CODING_TOOLS, RESEARCH_TOOLS, BROWSER_TOOLS
      (NOT in DIRECT_TOOLS — DirectAgent has no tools)
    - The delegate tool validates its args (target_agent required, task
      required, target_agent must be registered)
    - The delegate tool rejects unknown target agents
    - The delegate tool enforces recursion depth (MAX_DELEGATION_DEPTH)
    - The delegate tool returns a meaningful ToolResult on each path
    - The delegate tool definition appears in TOOL_DEFINITIONS
    - The _extract_tool_input helper handles the 'delegate' tool name

The full end-to-end test (an agent actually delegates to another agent
via a real model call) is in the real-model smoke test script at
/home/z/my-project/scripts/phase3_smoke_after.py.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

import pytest

from core.agent.constants import AGENT_ALLOWED_TOOLS
from core.models import Intent, RiskLevel


# ── Tool registration ─────────────────────────────────────────────────────


def test_delegate_intent_exists():
    """Intent.DELEGATE exists per ADR-8 Phase 3."""
    assert hasattr(Intent, "DELEGATE")
    assert Intent.DELEGATE.value == "delegate"


def test_delegate_tool_is_registered():
    """The delegate tool is registered in the tool registry."""
    from tools import _REGISTRY
    assert Intent.DELEGATE in _REGISTRY, (
        "Intent.DELEGATE not registered — the delegate tool module must be "
        "imported in tools/__init__.py"
    )
    entry = _REGISTRY[Intent.DELEGATE]
    assert entry["description"], "delegate tool has no description"
    assert entry["cost"] > 0, "delegate tool should have non-zero cost (it's expensive)"
    assert entry["parallelizable"] is False, (
        "delegate tool should NOT be parallelizable (handoff semantics)"
    )


def test_delegate_in_agent_allowed_tools():
    """AGENT_ALLOWED_TOOLS includes 'delegate' so the agent loop can dispatch it."""
    assert "delegate" in AGENT_ALLOWED_TOOLS


def test_delegate_in_coding_tools():
    """CODING_TOOLS includes 'delegate' (CodingAgent can delegate to research/browser)."""
    from agents.coding import CODING_TOOLS
    assert "delegate" in CODING_TOOLS


def test_delegate_in_research_tools():
    """RESEARCH_TOOLS includes 'delegate' (ResearchAgent can delegate to coding)."""
    from agents.research import RESEARCH_TOOLS
    assert "delegate" in RESEARCH_TOOLS


def test_delegate_in_browser_tools():
    """BROWSER_TOOLS includes 'delegate' (BrowserAgent can delegate to research/coding)."""
    from agents.browser import BROWSER_TOOLS
    assert "delegate" in BROWSER_TOOLS


def test_delegate_NOT_in_direct_tools():
    """DIRECT_TOOLS does NOT include 'delegate' (DirectAgent has no tools)."""
    from agents.direct import DIRECT_TOOLS
    assert "delegate" not in DIRECT_TOOLS
    assert len(DIRECT_TOOLS) == 0


# ── Tool definition appears in TOOL_DEFINITIONS ───────────────────────────


def test_delegate_in_tool_definitions():
    """The delegate tool appears in TOOL_DEFINITIONS (so the model knows it can call it)."""
    from core.agent.loop import TOOL_DEFINITIONS
    delegate_defs = [td for td in TOOL_DEFINITIONS if td["function"]["name"] == "delegate"]
    assert len(delegate_defs) == 1, (
        f"expected exactly 1 delegate tool definition; found {len(delegate_defs)}"
    )
    fn = delegate_defs[0]["function"]
    assert "target_agent" in fn["parameters"]["properties"]
    assert "task" in fn["parameters"]["properties"]
    assert "target_agent" in fn["parameters"]["required"]
    assert "task" in fn["parameters"]["required"]
    # target_agent has an enum constraint
    assert "enum" in fn["parameters"]["properties"]["target_agent"]
    assert set(fn["parameters"]["properties"]["target_agent"]["enum"]) == {
        "research", "coding", "browser", "direct", "verifier", "reviewer", "debugger"
    }


# ── _extract_tool_input handles delegate ──────────────────────────────────


def test_extract_tool_input_delegate():
    """_extract_tool_input serializes delegate args as JSON."""
    from core.agent.loop import _extract_tool_input
    args = {"target_agent": "research", "task": "find weather in Nairobi"}
    result = _extract_tool_input("delegate", args)
    parsed = json.loads(result)
    assert parsed == args


# ── delegate tool argument validation ─────────────────────────────────────


@pytest.mark.asyncio
async def test_delegate_rejects_non_json_input():
    """If the input isn't JSON, delegate returns an error ToolResult."""
    from tools.delegate import delegate
    result = await delegate("not a json string")
    assert result.success is False
    assert result.error_type == "invalid_input"
    assert "JSON" in result.content or "json" in result.content


@pytest.mark.asyncio
async def test_delegate_rejects_missing_target_agent():
    """If target_agent is missing, delegate returns an error."""
    from tools.delegate import delegate
    result = await delegate(json.dumps({"task": "find weather"}))
    assert result.success is False
    assert result.error_type == "invalid_input"
    assert "target_agent" in result.content


@pytest.mark.asyncio
async def test_delegate_rejects_missing_task():
    """If task is missing, delegate returns an error."""
    from tools.delegate import delegate
    result = await delegate(json.dumps({"target_agent": "research"}))
    assert result.success is False
    assert result.error_type == "invalid_input"
    assert "task" in result.content


@pytest.mark.asyncio
async def test_delegate_rejects_empty_target_agent():
    """If target_agent is empty string, delegate returns an error."""
    from tools.delegate import delegate
    result = await delegate(json.dumps({"target_agent": "", "task": "find weather"}))
    assert result.success is False
    assert result.error_type == "invalid_input"


@pytest.mark.asyncio
async def test_delegate_rejects_unknown_target_agent():
    """If target_agent isn't registered, delegate returns a not_found error."""
    from tools.delegate import delegate
    result = await delegate(
        json.dumps({"target_agent": "nonexistent_agent", "task": "do something"})
    )
    assert result.success is False
    assert result.error_type == "not_found"
    # The error should mention registered agents
    assert "research" in result.content
    assert "coding" in result.content


# ── Recursion depth enforcement ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_delegate_rejects_recursion_depth_exceeded():
    """If delegation depth >= MAX_DELEGATION_DEPTH, delegate returns recursion_limit."""
    from tools import delegate as delegate_mod
    from tools.delegate import MAX_DELEGATION_DEPTH, delegate

    # Set the current depth to the max — next delegation should be rejected
    token = delegate_mod._current_depth.set(MAX_DELEGATION_DEPTH)
    try:
        result = await delegate(
            json.dumps({"target_agent": "research", "task": "find weather"})
        )
        assert result.success is False
        assert result.error_type == "recursion_limit"
        assert "delegation depth limit" in result.content
    finally:
        delegate_mod._current_depth.reset(token)


# ── Adapter access ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delegate_rejects_when_no_adapter_set():
    """If no adapter is set (via set_current_adapter), delegate returns adapter_unavailable."""
    from tools import delegate as delegate_mod
    from tools.delegate import delegate

    # Ensure no adapter is set (default is None)
    token = delegate_mod._current_adapter.set(None)
    try:
        # Also reset depth to 0 so we don't hit recursion_limit first
        depth_token = delegate_mod._current_depth.set(0)
        try:
            result = await delegate(
                json.dumps({"target_agent": "research", "task": "find weather"})
            )
            assert result.success is False
            assert result.error_type == "adapter_unavailable"
        finally:
            delegate_mod._current_depth.reset(depth_token)
    finally:
        delegate_mod._current_adapter.reset(token)


# ── Adapter set/get helpers ───────────────────────────────────────────────


def test_set_current_adapter_sets_adapter():
    """set_current_adapter() sets the adapter contextvar."""
    from tools.delegate import _current_adapter, set_current_adapter
    fake_adapter = MagicMock()
    token = _current_adapter.set(None)  # reset to known state
    try:
        set_current_adapter(fake_adapter)
        assert _current_adapter.get() is fake_adapter
    finally:
        _current_adapter.reset(token)


def test_get_current_depth_returns_default():
    """get_current_depth() returns 0 by default."""
    from tools.delegate import _current_depth, get_current_depth
    token = _current_depth.set(0)
    try:
        assert get_current_depth() == 0
    finally:
        _current_depth.reset(token)


# ── dispatch_with_retry passes adapter ────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_with_retry_accepts_adapter_kwarg():
    """dispatch_with_retry() accepts an `adapter` kwarg without error."""
    from core.agent.tool_dispatch import dispatch_with_retry
    from tools.delegate import _current_adapter

    # Call with adapter=None — should be a no-op (no adapter set)
    # but should NOT raise.
    fake_adapter = MagicMock()
    token = _current_adapter.set(None)
    try:
        # Use a non-existent intent so dispatch returns None quickly
        # (we're testing the adapter-setting behavior, not the dispatch)
        # Use Intent.SYSINFO which is registered and fast
        result, failed, retries = await dispatch_with_retry(
            Intent.SYSINFO, "test query", adapter=fake_adapter
        )
        # The adapter should now be set
        assert _current_adapter.get() is fake_adapter
    finally:
        _current_adapter.reset(token)


# ── Integration: delegate tool end-to-end with mocked sub-agent ───────────


@pytest.mark.asyncio
async def test_delegate_runs_sub_agent_and_returns_its_response(monkeypatch):
    """End-to-end: delegate() runs the sub-agent and returns its response."""
    from tools import delegate as delegate_mod
    from tools.delegate import delegate

    # Mock the ResearchAgent to return a canned response
    class _FakeResearchAgent:
        def __init__(self, adapter=None):
            self.adapter = adapter

        async def run(self, **kwargs):
            # Yield a fake response
            from core.models import StreamChunk
            yield StreamChunk(text="The weather in Nairobi is 22°C, light rain.", done=False)
            yield StreamChunk(text="", done=True)

    # Patch get_agent to return our fake agent
    from agents.registry import _REGISTRY
    saved_registry = dict(_REGISTRY)
    _REGISTRY.clear()
    _REGISTRY["research"] = _FakeResearchAgent
    try:
        # Set a fake adapter
        adapter_token = delegate_mod._current_adapter.set(MagicMock())
        depth_token = delegate_mod._current_depth.set(0)
        try:
            result = await delegate(
                json.dumps({"target_agent": "research", "task": "find weather in Nairobi"})
            )
            assert result.success is True
            assert result.source == "delegate"
            assert "22°C" in result.content
            assert "light rain" in result.content
            assert result.metadata["target_agent"] == "research"
        finally:
            delegate_mod._current_depth.reset(depth_token)
            delegate_mod._current_adapter.reset(adapter_token)
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(saved_registry)
