"""Parent-agent routing regressions.

The old direct/dispatcher escalation path was removed. Every user turn now
enters LocalMind's parent AgentLoop, which owns tool selection and can consume
native tool calls or delegate to specialized child agents.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from core.engine import Engine
from core.models import StreamChunk
from core.obs import ObsCollector


@pytest.mark.asyncio
async def test_runtime_enters_one_parent_loop_without_dispatcher():
    engine = Engine()
    captured: dict = {}

    async def fake_run(**kwargs):
        captured.update(kwargs)
        yield StreamChunk(text="Parent completed the request.", done=False)
        yield StreamChunk(text="", done=True)

    adapter = MagicMock()
    adapter.effective_context_window = 8192
    obs = ObsCollector()
    with patch("core.engine.get_adapter", return_value=adapter), patch.object(
        engine._agent_loop, "run", fake_run
    ):
        chunks = [
            chunk
            async for chunk in engine.process(
                "check the project and report the result",
                "parent-runtime-1",
                obs=obs,
            )
        ]

    assert captured["agent_config"].name == "parent"
    assert captured["reformulated_message"] == "check the project and report the result"
    assert "delegate" in captured["allowed_tool_names"]
    assert any(tool["intent"] == "web_search" for tool in captured["available_tools"])
    assert "Parent completed" in "".join(chunk.text for chunk in chunks)
    assert sum(chunk.done for chunk in chunks) == 1


@pytest.mark.asyncio
async def test_runtime_preserves_parent_tool_and_delegation_contract():
    engine = Engine()
    captured: dict = {}

    async def fake_run(**kwargs):
        captured.update(kwargs)
        yield StreamChunk(text="done", done=False)
        yield StreamChunk(text="", done=True)

    adapter = MagicMock()
    adapter.effective_context_window = 8192
    with patch("core.engine.get_adapter", return_value=adapter), patch.object(
        engine._agent_loop, "run", fake_run
    ):
        # The parent runtime now emits an immediate acknowledgement before
        # entering the loop. Consume the stream like the real SSE client so
        # the parent contract is observed after that progress event.
        _chunks = [
            chunk
            async for chunk in engine.process(
                "research this and compare the sources",
                "parent-runtime-2",
            )
        ]

    names = {tool["intent"] for tool in captured["available_tools"]}
    assert {"delegate", "delegate_parallel", "delegate_inline"}.issubset(names)
    assert captured["agent_context"]
    assert "Parent-Agent" in captured["agent_context"]


@pytest.mark.asyncio
async def test_runtime_does_not_expose_internal_loop_done_markers():
    engine = Engine()

    async def fake_run(**kwargs):
        yield StreamChunk(text="answer", done=True)

    adapter = MagicMock()
    adapter.effective_context_window = 8192
    with patch("core.engine.get_adapter", return_value=adapter), patch.object(
        engine._agent_loop, "run", fake_run
    ):
        chunks = [
            chunk
            async for chunk in engine.process("say hello", "parent-runtime-3")
        ]

    assert "answer" in "".join(chunk.text for chunk in chunks)
    assert sum(chunk.done for chunk in chunks) == 1
