"""Session 115 regression tests - empty-response fast-fail in the agent loop.

The free-tier model sometimes returns an empty stream (no text, no tool
call). Previously the loop fell through to "stream the answer" with an
empty buffer - the user saw a spinner for 60-120s and then a blank reply
(the silent-stall failure mode). The loop now detects an empty final
buffer and fast-fails with an honest user-facing message instead of
spinning another PER_CALL_TIMEOUT_SECS model call on the same empty output.

Contract under test:
  1. An empty text-only response yields a non-empty, honest final message.
  2. chat_with_tools is called exactly ONCE - the loop does NOT retry.
  3. Regression: a normal non-empty text response still streams through.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from core.agent.loop import AgentLoop
from core.models import Intent, StreamChunk


class TestEmptyResponseFastFail:
    @pytest.mark.asyncio
    async def test_empty_stream_fast_fails_with_honest_message(self):
        loop = AgentLoop(adapter=MagicMock())
        seen = {"calls": 0}

        async def empty_chat_with_tools(messages, tools, temperature=0.3, intent=None):
            seen["calls"] += 1

            async def _stream():
                yield StreamChunk(text="", done=False)
                yield StreamChunk(text="", done=True)

            return _stream()

        async def empty_chat(messages, temperature=0.4):
            return
            yield

        mock_adapter = MagicMock()
        mock_adapter.chat_with_tools = empty_chat_with_tools
        mock_adapter.chat = empty_chat

        chunks = []
        with patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
             patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x):
            async for chunk in loop.run(
                messages=[{"role": "user", "content": "check git status"}],
                intent=Intent.SHELL,
                initial_tool_result=None,
                available_tools=[],
                adapter=mock_adapter,
            ):
                chunks.append(chunk)

        full = "".join(c.text for c in chunks)
        assert "empty response" in full, f"expected honest empty-response message, got {full!r}"
        assert seen["calls"] == 1, (
            f"loop must not retry the same empty output (chat_with_tools called {seen['calls']}x)"
        )

    @pytest.mark.asyncio
    async def test_normal_text_response_still_streams(self):
        loop = AgentLoop(adapter=MagicMock())

        async def chat_with_tools(messages, tools, temperature=0.3, intent=None):
            async def _stream():
                yield StreamChunk(text="All good - nothing to do.", done=False)
                yield StreamChunk(text="", done=True)

            return _stream()

        async def empty_chat(messages, temperature=0.4):
            return
            yield

        mock_adapter = MagicMock()
        mock_adapter.chat_with_tools = chat_with_tools
        mock_adapter.chat = empty_chat

        chunks = []
        with patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
             patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x):
            async for chunk in loop.run(
                messages=[{"role": "user", "content": "hi"}],
                intent=Intent.SHELL,
                initial_tool_result=None,
                available_tools=[],
                adapter=mock_adapter,
            ):
                chunks.append(chunk)

        full = "".join(c.text for c in chunks)
        assert "All good - nothing to do." in full, f"expected normal text, got {full!r}"

    @pytest.mark.asyncio
    async def test_stream_error_propagates_adapter_message(self):
        """Session 187: when the adapter yields an error chunk (e.g. zen 429),
        the loop must pass the adapter's error message through to the SSE
        error event. Previously the MiniMax buffering dropped the message
        (error=""), so the chat route skipped the error event and the
        frontend rendered a silent spinner."""
        loop = AgentLoop(adapter=MagicMock())

        zen_429 = (
            'zen returned 429: {"type":"error","error":{"type":'
            '"FreeUsageLimitError","message":"Rate limit exceeded."}}'
        )

        async def chat_with_tools(messages, tools, temperature=0.3, intent=None):
            async def _stream():
                yield StreamChunk(text="", done=True, error=zen_429)

            return _stream()

        async def empty_chat(messages, temperature=0.4):
            return
            yield

        mock_adapter = MagicMock()
        mock_adapter.chat_with_tools = chat_with_tools
        mock_adapter.chat = empty_chat

        chunks = []
        with patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
             patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x):
            async for chunk in loop.run(
                messages=[{"role": "user", "content": "list files"}],
                intent=Intent.SHELL,
                initial_tool_result=None,
                available_tools=[],
                adapter=mock_adapter,
            ):
                chunks.append(chunk)

        # The error message must survive — not be replaced by "".
        errs = [c.error for c in chunks if c.error]
        assert errs, f"expected a non-empty chunk.error, got {chunks!r}"
        assert any("429" in e for e in errs), f"expected the 429 text to survive, got {errs!r}"
