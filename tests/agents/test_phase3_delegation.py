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
from typing import ClassVar
from unittest.mock import MagicMock

import pytest
from core.agent.constants import AGENT_ALLOWED_TOOLS
from core.agent.delegation import (
    AgentRunContext,
    DelegationInstructionPacket,
    DelegationResult,
    get_current_run_id,
    reset_current_run_id,
    set_current_run_id,
)
from core.models import Intent, StreamChunk

# ── Fixed instruction packet and isolated run contracts ────────────────────


def test_delegation_packet_renders_literal_scoped_instructions():
    packet = DelegationInstructionPacket.from_payload(
        {
            "target_agent": "research",
            "task": "Find current authentication guidance",
            "scope": ["Official documentation only"],
            "constraints": ["Do not modify files"],
            "forbidden_tools": ["shell"],
            "input_evidence": "The parent found three candidate providers.",
            "output_contract": {"format": "structured report", "must_include": "sources"},
        }
    )

    prompt = packet.to_prompt()
    metadata = packet.to_metadata()
    assert "The parent found three candidate providers." in prompt
    assert "BEGIN UNTRUSTED EVIDENCE" in prompt
    assert "END UNTRUSTED EVIDENCE" in prompt
    assert "The parent found three candidate providers." not in str(metadata)
    assert metadata["input_evidence_present"] is True
    assert packet.target_agent == "research"
    assert "Objective: Find current authentication guidance" in prompt
    assert "- Do not modify files" in prompt
    assert "- shell" in prompt
    assert "format: structured report" in prompt
    assert "must_include: sources" in prompt


def test_delegation_packet_is_immutable_and_run_context_is_scoped():
    packet = DelegationInstructionPacket.from_payload(
        {"target_agent": "verifier", "task": "Run the focused checks"}
    )
    context = AgentRunContext.create(packet, parent_run_id="run_parent")
    assert context.run_id.startswith("run_")
    assert context.parent_run_id == "run_parent"
    assert context.to_metadata()["instruction"]["objective"] == "Run the focused checks"

    token = set_current_run_id(context.run_id)
    try:
        assert get_current_run_id() == context.run_id
        with pytest.raises((AttributeError, TypeError)):
            packet.objective = "mutated"  # frozen contract
    finally:
        reset_current_run_id(token)
    assert get_current_run_id() is None


def test_delegation_packet_rejects_oversized_payloads():
    with pytest.raises(ValueError, match="at most"):
        DelegationInstructionPacket.from_payload(
            {"target_agent": "research", "task": "x" * 4_001}
        )
    with pytest.raises(ValueError, match="at most"):
        DelegationInstructionPacket.from_payload(
            {
                "target_agent": "research",
                "task": "short task",
                "input_evidence": "x" * 4_001,
            }
        )


def test_delegation_result_is_json_friendly():
    result = DelegationResult(
        status="completed",
        run_id="run_child",
        agent_name="research",
        output="Found two sources.",
    )
    assert result.to_metadata() == {
        "status": "completed",
        "run_id": "run_child",
        "agent_name": "research",
        "output_preview": "Found two sources.",
        "output_chars": 18,
        "error_type": "",
        "iterations": 0,
    }


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


def test_delegate_not_in_direct_tools():
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
        "research", "coding", "browser", "direct", "verifier", "reviewer", "debugger", "analyst"
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
        # Use Intent.SYSINFO which is registered and fast
        _result, _failed, _retries = await dispatch_with_retry(
            Intent.SYSINFO, "test query", adapter=fake_adapter
        )
        # The adapter should now be set
        assert _current_adapter.get() is fake_adapter
    finally:
        _current_adapter.reset(token)


# ── Integration: delegate tool end-to-end with mocked sub-agent ───────────


@pytest.mark.asyncio
async def test_delegate_child_exception_returns_structured_failure():
    from tools import delegate as delegate_mod
    from tools.delegate import delegate

    class _ExplodingAgent:
        def __init__(self, adapter=None):
            self.adapter = adapter

        async def run(self, **kwargs):
            raise RuntimeError("child exploded")
            yield  # pragma: no cover

    from agents.registry import _REGISTRY
    saved_registry = dict(_REGISTRY)
    _REGISTRY.clear()
    _REGISTRY["research"] = _ExplodingAgent
    adapter_token = delegate_mod._current_adapter.set(MagicMock())
    depth_token = delegate_mod._current_depth.set(0)
    try:
        result = await delegate(
            json.dumps({"target_agent": "research", "task": "explode safely"})
        )
        assert result.success is False
        assert result.error_type == "child_exception"
        assert result.metadata["delegation"]["status"] == "failed"
        assert result.metadata["delegation"]["error_type"] == "child_exception"
        assert delegate_mod._current_depth.get() == 0
        assert get_current_run_id() is None
    finally:
        delegate_mod._current_depth.reset(depth_token)
        delegate_mod._current_adapter.reset(adapter_token)
        _REGISTRY.clear()
        _REGISTRY.update(saved_registry)


@pytest.mark.asyncio
async def test_delegate_applies_forbidden_tools_to_child_allowlist():
    from tools import delegate as delegate_mod
    from tools.delegate import delegate

    class _Config:
        allowed_tools = frozenset({"web_search", "shell"})

    class _ResearchAgent:
        received_allowed = None

        def __init__(self, adapter=None):
            self.adapter = adapter

        def config(self):
            return _Config()

        async def run(self, **kwargs):
            type(self).received_allowed = kwargs["allowed_tool_names"]
            yield type("Chunk", (), {"text": "restricted result"})()

    from agents.registry import _REGISTRY
    saved_registry = dict(_REGISTRY)
    _REGISTRY.clear()
    _REGISTRY["research"] = _ResearchAgent
    adapter_token = delegate_mod._current_adapter.set(MagicMock())
    depth_token = delegate_mod._current_depth.set(0)
    try:
        result = await delegate(
            json.dumps(
                {
                    "target_agent": "research",
                    "task": "research safely",
                    "forbidden_tools": ["shell"],
                }
            )
        )
        assert result.success is True
        assert result.metadata["delegation"]["status"] == "completed"
        assert _ResearchAgent.received_allowed == frozenset({"web_search"})
    finally:
        delegate_mod._current_depth.reset(depth_token)
        delegate_mod._current_adapter.reset(adapter_token)
        _REGISTRY.clear()
        _REGISTRY.update(saved_registry)


@pytest.mark.asyncio
async def test_delegate_timeout_returns_structured_failure_and_restores_parent(monkeypatch):
    from tools import delegate as delegate_mod
    from tools.delegate import delegate

    class _SlowAgent:
        def __init__(self, adapter=None):
            self.adapter = adapter

        async def run(self, **kwargs):
            await asyncio.sleep(0.05)
            yield type("Chunk", (), {"text": "late result"})()

    from agents.registry import _REGISTRY
    saved_registry = dict(_REGISTRY)
    _REGISTRY.clear()
    _REGISTRY["research"] = _SlowAgent
    adapter_token = delegate_mod._current_adapter.set(MagicMock())
    depth_token = delegate_mod._current_depth.set(0)
    parent_token = set_current_run_id("run_parent")
    monkeypatch.setattr(delegate_mod, "DELEGATION_WALL_CLOCK_SECS", 0.001)
    try:
        result = await delegate(
            json.dumps({"target_agent": "research", "task": "time out safely"})
        )
        assert result.success is False
        assert result.error_type == "timeout"
        assert "Suggested next step" in result.content
        assert result.metadata["delegation"]["status"] == "timed_out"
        assert result.metadata["run"]["parent_run_id"] == "run_parent"
        assert get_current_run_id() == "run_parent"
        assert delegate_mod._current_depth.get() == 0
    finally:
        reset_current_run_id(parent_token)
        delegate_mod._current_depth.reset(depth_token)
        delegate_mod._current_adapter.reset(adapter_token)
        _REGISTRY.clear()
        _REGISTRY.update(saved_registry)


@pytest.mark.asyncio
async def test_delegate_setup_exception_returns_structured_failure():
    from tools import delegate as delegate_mod
    from tools.delegate import delegate

    class _BadConfigAgent:
        def __init__(self, adapter=None):
            self.adapter = adapter

        def config(self):
            raise RuntimeError("bad config")

        async def run(self, **kwargs):
            yield type("Chunk", (), {"text": "unreachable"})()

    from agents.registry import _REGISTRY
    saved_registry = dict(_REGISTRY)
    _REGISTRY.clear()
    _REGISTRY["research"] = _BadConfigAgent
    adapter_token = delegate_mod._current_adapter.set(MagicMock())
    depth_token = delegate_mod._current_depth.set(0)
    parent_token = set_current_run_id("run_parent")
    try:
        result = await delegate(
            json.dumps({
                "target_agent": "research",
                "task": "handle setup failure",
                "input_evidence": "private evidence that must not be returned",
            })
        )
        assert result.success is False
        assert result.error_type == "child_exception"
        assert result.metadata["run"]["parent_run_id"] == "run_parent"
        assert "private evidence" not in str(result.metadata)
        assert result.metadata["delegation"]["output_chars"] == 0
        assert get_current_run_id() == "run_parent"
    finally:
        reset_current_run_id(parent_token)
        delegate_mod._current_depth.reset(depth_token)
        delegate_mod._current_adapter.reset(adapter_token)
        _REGISTRY.clear()
        _REGISTRY.update(saved_registry)


@pytest.mark.asyncio
async def test_delegate_construction_failure_returns_structured_failure():
    """If the sub-agent's constructor raises, delegate returns construction_failed.

    B-2026-08-02-3: construction failure must be distinguishable from
    timeout / child_exception / empty_response so the parent model gets
    the actual cause (not a generic error) plus a suggested next step.
    """
    from tools import delegate as delegate_mod
    from tools.delegate import delegate

    class _ConstructorExplodesAgent:
        def __init__(self, adapter=None):
            raise RuntimeError("cannot build agent")

    from agents.registry import _REGISTRY
    saved_registry = dict(_REGISTRY)
    _REGISTRY.clear()
    _REGISTRY["research"] = _ConstructorExplodesAgent
    adapter_token = delegate_mod._current_adapter.set(MagicMock())
    depth_token = delegate_mod._current_depth.set(0)
    try:
        result = await delegate(
            json.dumps({"target_agent": "research", "task": "construct safely"})
        )
        assert result.success is False
        assert result.error_type == "construction_failed"
        assert result.metadata["delegation"]["status"] == "failed"
        assert result.metadata["delegation"]["error_type"] == "construction_failed"
        assert "Suggested next step" in result.content
        assert get_current_run_id() is None
    finally:
        delegate_mod._current_depth.reset(depth_token)
        delegate_mod._current_adapter.reset(adapter_token)
        _REGISTRY.clear()
        _REGISTRY.update(saved_registry)


@pytest.mark.asyncio
async def test_delegate_empty_response_returns_structured_failure():
    """If the sub-agent finishes with no text, delegate returns empty_response.

    B-2026-08-02-3: the empty-response path must be a distinct, actionable
    diagnostic — not a silent success and not a generic failure.
    """
    from tools import delegate as delegate_mod
    from tools.delegate import delegate

    class _SilentAgent:
        def __init__(self, adapter=None):
            self.adapter = adapter

        async def run(self, **kwargs):
            # Finishes immediately, yielding only empty text chunks.
            yield type("Chunk", (), {"text": ""})()
            yield type("Chunk", (), {"text": ""})()

    from agents.registry import _REGISTRY
    saved_registry = dict(_REGISTRY)
    _REGISTRY.clear()
    _REGISTRY["research"] = _SilentAgent
    adapter_token = delegate_mod._current_adapter.set(MagicMock())
    depth_token = delegate_mod._current_depth.set(0)
    try:
        result = await delegate(
            json.dumps({"target_agent": "research", "task": "stay silent"})
        )
        assert result.success is False
        assert result.error_type == "empty_response"
        assert result.metadata["delegation"]["status"] == "failed"
        assert result.metadata["delegation"]["error_type"] == "empty_response"
        assert "returned an empty response" in result.content
        assert "Suggested next step" in result.content
        assert get_current_run_id() is None
    finally:
        delegate_mod._current_depth.reset(depth_token)
        delegate_mod._current_adapter.reset(adapter_token)
        _REGISTRY.clear()
        _REGISTRY.update(saved_registry)


@pytest.mark.asyncio
async def test_delegate_runs_sub_agent_and_returns_its_response(monkeypatch):
    """End-to-end: delegate() runs the sub-agent and returns its response."""
    from tools import delegate as delegate_mod
    from tools.delegate import delegate

    # Mock the ResearchAgent to return a canned response
    class _FakeResearchAgent:
        received_messages: ClassVar[list] = []

        def __init__(self, adapter=None):
            self.adapter = adapter

        async def run(self, **kwargs):
            self.received_messages.append(kwargs["messages"])
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
                json.dumps(
                    {
                        "target_agent": "research",
                        "task": "find weather in Nairobi",
                        "constraints": ["Do not modify files"],
                        "output_contract": {"must_include": "temperature"},
                    }
                )
            )
            assert result.success is True
            assert result.source == "delegate"
            assert "22°C" in result.content
            assert "light rain" in result.content
            assert result.metadata["target_agent"] == "research"
            assert result.metadata["delegation"]["status"] == "completed"
            assert result.metadata["run"]["parent_run_id"] is None
            child_prompt = _FakeResearchAgent.received_messages[0][0]["content"]
            assert "DELEGATED TASK INSTRUCTION" in child_prompt
            assert "- Do not modify files" in child_prompt
            assert "must_include: temperature" in child_prompt
            assert get_current_run_id() is None
        finally:
            delegate_mod._current_depth.reset(depth_token)
            delegate_mod._current_adapter.reset(adapter_token)
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(saved_registry)


# ── ADR-15 §3: bounded-instruction contract + final-output-only ─────────────


def test_delegation_packet_renders_explicit_do_do_not_return_contract():
    """Even a BARE {target_agent, task} delegation carries the bounded
    instruction: explicit DO / DO NOT / RETURN framing, so the child knows
    what to accomplish, what is forbidden, and the exact report shape."""
    packet = DelegationInstructionPacket.from_payload(
        {"target_agent": "research", "task": "find the current weather"}
    )
    prompt = packet.to_prompt()
    assert "DELEGATED TASK INSTRUCTION" in prompt
    assert "Objective: find the current weather" in prompt
    assert "DO:" in prompt
    assert "DO NOT:" in prompt
    assert "Do not rely on or reference the parent conversation" in prompt
    assert "RETURN (report contract):" in prompt
    # The default return shape is spelled out even with no explicit contract.
    assert "concise report of work performed" in prompt


def test_delegation_packet_renders_contract_when_sections_empty():
    """The DO NOT / RETURN sections fall back to safe defaults when the
    caller provided no constraints or output contract."""
    packet = DelegationInstructionPacket.from_payload(
        {"target_agent": "coding", "task": "refactor the module"}
    )
    prompt = packet.to_prompt()
    assert "- Deviate from the objective or invent extra work." in prompt
    assert "RETURN (report contract):" in prompt
    # No accidental empty labels.
    assert "Constraints:" not in prompt


@pytest.mark.asyncio
async def test_delegate_child_sees_only_packet_not_parent_history():
    """ADR-15 §3 (final-output-only): the child receives EXACTLY ONE user
    message — the bounded instruction packet — never the parent's message
    history. And the parent receives only the child's concatenated final
    output, not the child's internal message list."""
    from tools import delegate as delegate_mod
    from tools.delegate import delegate

    class _RecordingAgent:
        received_messages: ClassVar[list] = []

        def __init__(self, adapter=None):
            self.adapter = adapter

        async def run(self, **kwargs):
            _RecordingAgent.received_messages.append(kwargs["messages"])
            # Simulate a child that internally produced MANY messages.
            for i in range(5):
                yield StreamChunk(text=f"internal step {i}\n", done=False)
            yield StreamChunk(text="final report", done=False)
            yield StreamChunk(text="", done=True)

    from agents.registry import _REGISTRY
    saved_registry = dict(_REGISTRY)
    _REGISTRY.clear()
    _REGISTRY["research"] = _RecordingAgent
    adapter_token = delegate_mod._current_adapter.set(MagicMock())
    depth_token = delegate_mod._current_depth.set(0)
    try:
        _RecordingAgent.received_messages = []
        result = await delegate(
            json.dumps(
                {
                    "target_agent": "research",
                    "task": "summarize the docs",
                    "output_contract": {"format": "bullets"},
                }
            )
        )
        assert result.success is True
        # The child's message list is exactly ONE user message (the packet).
        assert len(_RecordingAgent.received_messages) == 1
        child_messages = _RecordingAgent.received_messages[0]
        assert len(child_messages) == 1
        assert child_messages[0]["role"] == "user"
        assert "DELEGATED TASK INSTRUCTION" in child_messages[0]["content"]
        assert "Objective: summarize the docs" in child_messages[0]["content"]
        # The parent got back the child's final output as ONE result — the
        # child's 5 internal messages never bloat the parent context.
        assert "internal step 3" in result.content
        assert "final report" in result.content
        assert result.metadata["response_length"] == len(
            "internal step 0\ninternal step 1\ninternal step 2\ninternal step 3\ninternal step 4\nfinal report"
        )
    finally:
        delegate_mod._current_depth.reset(depth_token)
        delegate_mod._current_adapter.reset(adapter_token)
        _REGISTRY.clear()
        _REGISTRY.update(saved_registry)
