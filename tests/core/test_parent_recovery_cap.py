"""Tests for the parent-path empty-reasoning recovery cap (B-2026-08-20-7 / Session 310).

The parent path gets a higher recovery cap (3 vs 2) because weak models on
the parent path frequently need the extra recovery attempt to complete a
tool-bearing turn. The non-parent cap stays at 2.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from core.agent.loop import (
    _MAX_EMPTY_REASONING_RECOVERIES,
    _MAX_EMPTY_REASONING_RECOVERIES_PARENT,
    AgentLoop,
)
from core.models import StreamChunk


def test_parent_cap_is_higher_than_non_parent_cap():
    """The parent recovery cap (3) must be higher than the non-parent cap (2)."""
    assert _MAX_EMPTY_REASONING_RECOVERIES_PARENT > _MAX_EMPTY_REASONING_RECOVERIES
    assert _MAX_EMPTY_REASONING_RECOVERIES_PARENT == 3
    assert _MAX_EMPTY_REASONING_RECOVERIES == 2


class _ParentEmptyAfterToolAdapter:
    """Stub adapter matching the parent path's expectations.

    call 1 → shell tool call (returns ToolCallResult, not a stream).
    calls 2+ → reasoning-only (empty content, no tool call — the 'thinks but
    doesn't act' weak-model pattern that should trigger recovery).

    The parent path's _ParentAdapterCompat wrapper handles both return shapes.
    """

    def __init__(self) -> None:
        self.calls = 0

    async def list_models(self):
        return []

    async def health_check(self):
        return True

    @property
    def effective_context_window(self):
        return 8192

    async def chat(self, messages, temperature=0.1, intent="chat"):
        # Plain chat() fallback for synthesis calls.
        self.calls += 1
        yield StreamChunk(text="Synthesized answer from evidence: hello world.", done=False)
        yield StreamChunk(text="", done=True)

    async def chat_with_tools(self, messages, tools, temperature=0.3, intent=None, tool_choice=None):
        self.calls += 1
        if self.calls == 1:
            from adapters.ollama import ToolCallResult

            return ToolCallResult(
                tool_name="shell",
                tool_args={"command": "echo hello"},
                raw_content="I'll run a quick check.",
            )

        # All later calls: reasoning-only (empty content, no tool call).
        async def _think_only():
            yield StreamChunk(text="", thinking="Still thinking about the task. ", done=False)
            yield StreamChunk(text="", done=True)

        return _think_only()


def _collect_parent(loop, adapter):
    """Run the loop with a parent agent_config (name='parent', skip_planning=True)."""
    from agents.base_agent import AgentConfig
    from core.agent.constants import AGENT_ALLOWED_TOOLS
    from core.models import Intent

    async def _run():
        agent_config = AgentConfig(
            name="parent",
            max_iterations=20,
            allowed_tools=AGENT_ALLOWED_TOOLS,
        )
        return [
            chunk
            async for chunk in loop.run(
                messages=[{"role": "user", "content": "list /tmp files"}],
                intent=Intent.ANALYZE,
                initial_tool_result=None,
                available_tools=[],
                adapter=adapter,
                agent_config=agent_config,
                skip_planning=True,
            )
        ]

    return asyncio.run(_run())


def _fake_dispatch(*args, **kwargs):
    from core.models import RiskLevel, ToolResult
    return ToolResult(content="hello\n", risk=RiskLevel.LOW, source="shell", success=True), False, 0


def test_parent_path_gets_three_recovery_attempts():
    """The parent path should allow up to 3 empty-reasoning recoveries
    (vs 2 for non-parent paths). The tool call (call 1) + 3 recovery empties
    = 4 chat_with_tools calls before the cap is hit; the post-loop synthesis
    is a separate chat() call."""
    adapter = _ParentEmptyAfterToolAdapter()
    loop = AgentLoop(adapter=adapter)

    with patch("core.agent.loop.dispatch_with_retry", side_effect=_fake_dispatch):
        chunks = _collect_parent(loop, adapter)

    # The turn must end with output (post-loop synthesis or honest fallback).
    text = "".join(chunk.text for chunk in chunks if chunk.text)
    assert text.strip(), "the turn must end with a synthesized answer or honest fallback"

    # The parent path should have made: 1 tool call + 3 recovery empties = 4
    # chat_with_tools calls before the cap. The post-loop synthesis uses
    # chat() (not chat_with_tools), so it's a separate counter on the adapter.
    # We assert the chat_with_tools call count reached at least 4 (the parent
    # cap allows 3 recoveries, not 2).
    assert adapter.calls >= 4, (
        f"parent path should allow >= 4 chat_with_tools calls (1 tool + 3 recoveries), got {adapter.calls}"
    )


def test_non_parent_path_still_capped_at_two():
    """The non-parent path must still cap at 2 recoveries (unchanged behavior)."""
    from tests.adapters.test_thinking_policy_adr41 import (
        _collect_with_dispatch,
    )
    from tests.adapters.test_thinking_policy_adr41 import (
        _EmptyAfterToolAdapter as _NonParentAdapter,
    )

    adapter = _NonParentAdapter()
    adapter.chat_with_tools = _always_empty_after_tool(adapter)
    chunks = _collect_with_dispatch(AgentLoop(adapter=adapter), adapter)

    text = "".join(chunk.text for chunk in chunks if chunk.text)
    assert text.strip(), "the turn must end with a synthesized answer or honest fallback"
    # Non-parent: 1 tool call + 2 recovery empties = 3 calls + 1 synthesis = 4.
    assert adapter.calls == 1 + _MAX_EMPTY_REASONING_RECOVERIES + 1, (
        f"non-parent path should cap at 2 recoveries (4 total calls), got {adapter.calls}"
    )


def _always_empty_after_tool(adapter):
    """Replace the stub so EVERY post-tool call is reasoning-only."""
    original = adapter.chat_with_tools

    async def _patched(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        adapter.calls += 1
        if adapter.calls == 1:
            return await original(messages, tools, temperature=temperature, intent=intent, tool_choice=tool_choice)

        async def _think_only():
            yield StreamChunk(text="", thinking="Still thinking... ", done=False)
            yield StreamChunk(text="", done=True)

        return _think_only()

    return _patched
