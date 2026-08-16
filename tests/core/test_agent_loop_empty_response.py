"""Session 115 regression tests - empty-response fast-fail in the agent loop.

The free-tier model sometimes returns an empty stream (no text, no tool
call). Previously the loop fell through to "stream the answer" with an
empty buffer - the user saw a spinner for 60-120s and then a blank reply
(the silent-stall failure mode). The loop now detects an empty final
buffer and fast-fails with an honest user-facing message instead of
spinning another PER_CALL_TIMEOUT_SECS model call on the same empty output.

Contract under test:
  1. An empty text-only response yields a non-empty, honest final message.
  2. The FIRST tool iteration gets at most ONE forced-tool nudge (Session
     238); a second empty reply hits the honest fast-fail - bounded retry,
     never a spin.
  3. Regression: a normal non-empty text response still streams through.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from core.agent.loop import AgentLoop, TerminalProviderError
from core.models import Intent, StreamChunk


class TestEmptyResponseFastFail:
    @pytest.mark.asyncio
    async def test_empty_stream_fast_fails_with_honest_message(self):
        loop = AgentLoop(adapter=MagicMock())
        seen = {"calls": 0}

        async def empty_chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
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
        # Session 238: the FIRST tool iteration gets ONE forced-tool nudge
        # (bounded reprompt) before the honest fail — the empty-response
        # fast-fail (Session 115) still applies to the second empty reply.
        assert seen["calls"] == 2, (
            f"loop must retry an iter-0 empty output at most once, then fail "
            f"honestly (chat_with_tools called {seen['calls']}x)"
        )

    @pytest.mark.asyncio
    async def test_normal_text_response_still_streams(self):
        loop = AgentLoop(adapter=MagicMock())

        async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
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
    async def test_streamed_deltas_keep_boundary_spaces(self):
        """Regression: the per-chunk transform in the execute streaming path
        must not .strip() each delta, or space-prefixed tokens weld together
        ("assistantrunning", "thisdevice"). The loop must use the whitespace-
        safe stream variant on every streamed chunk.
        """
        loop = AgentLoop(adapter=MagicMock())

        # The execute streaming path buffers the first ~2000 chars (for tool
        # detection) and yields them as one block, then streams the REMAINDER
        # chunk by chunk. The per-chunk transform on that remainder must not
        # .strip() each delta. So: a >2000-char prefix to fill the buffer, then
        # the space-prefixed deltas that must survive intact.
        prefix = "word " * 500  # ~2500 chars, forces the buffer to flush
        deltas = [" LocalMind", " —", " a", " local", " assistant", " running", " here."]

        async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
            async def _stream():
                yield StreamChunk(text=prefix, done=False)
                for d in deltas:
                    yield StreamChunk(text=d, done=False)
                yield StreamChunk(text="", done=True)

            return _stream()

        async def empty_chat(messages, temperature=0.4):
            return
            yield

        mock_adapter = MagicMock()
        mock_adapter.chat_with_tools = chat_with_tools
        mock_adapter.chat = empty_chat

        chunks = []
        # NOTE: do NOT stub _filter_system_leaks here — we want the real
        # per-chunk transform path (incl. _strip_minimax_tool_calls_stream).
        with patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x):
            async for chunk in loop.run(
                messages=[{"role": "user", "content": "what can you do"}],
                intent=Intent.SHELL,
                initial_tool_result=None,
                available_tools=[],
                adapter=mock_adapter,
            ):
                chunks.append(chunk)

        full = "".join(c.text for c in chunks)
        assert "local assistant running here" in full, f"boundary spaces lost: {full!r}"
        assert "assistantrunning" not in full, f"delta strip regressed: {full!r}"

    @pytest.mark.asyncio
    async def test_terminal_planning_error_stops_before_tool_call(self):
        """ADR-32: a terminal provider error on the first provider call must
        not be swallowed by planning and retried in the parent loop."""
        loop = AgentLoop(adapter=MagicMock())
        seen = {"planning": 0, "tool_calls": 0}
        error = (
            'zen returned 429: {"error":{"type":"FreeUsageLimitError",'
            '"message":"free daily quota exceeded"}}'
        )

        async def failing_plan(messages, temperature=0.1, intent="chat"):
            seen["planning"] += 1
            yield StreamChunk(text="", done=True, error=error)

        async def tool_call_should_not_run(**kwargs):
            seen["tool_calls"] += 1
            raise AssertionError("terminal planning error entered tool loop")

        mock_adapter = MagicMock()
        mock_adapter.chat = failing_plan
        mock_adapter.chat_with_tools = tool_call_should_not_run

        with patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x), pytest.raises(
            TerminalProviderError
        ) as raised:
            async for _chunk in loop.run(
                messages=[{"role": "user", "content": "check the project"}],
                intent=Intent.SHELL,
                initial_tool_result=None,
                available_tools=[],
                adapter=mock_adapter,
            ):
                pass

        assert isinstance(raised.value, TerminalProviderError)
        assert str(raised.value) == error
        assert seen == {"planning": 1, "tool_calls": 0}

    @pytest.mark.asyncio
    async def test_transient_planning_error_keeps_existing_loop_path(self):
        """A plain transient 429 remains non-terminal and reaches the normal
        parent decision call rather than being treated as auth/quota failure."""
        loop = AgentLoop(adapter=MagicMock())
        seen = {"planning": 0, "tool_calls": 0}
        transient = 'zen returned 429: {"error":{"type":"requests","message":"per minute"}}'

        async def failing_plan(messages, temperature=0.1, intent="chat"):
            seen["planning"] += 1
            yield StreamChunk(text="", done=True, error=transient)

        async def final_chat(**kwargs):
            seen["tool_calls"] += 1

            async def _stream():
                yield StreamChunk(text="Recovered", done=False)
                yield StreamChunk(text="", done=True)

            return _stream()

        mock_adapter = MagicMock()
        mock_adapter.chat = failing_plan
        mock_adapter.chat_with_tools = final_chat

        with patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x):
            chunks = [
                chunk
                async for chunk in loop.run(
                    messages=[{"role": "user", "content": "check the project"}],
                    intent=Intent.SHELL,
                    initial_tool_result=None,
                    available_tools=[],
                    adapter=mock_adapter,
                )
            ]

        # Session 238: the first tool-required call gets one forced-tool
        # nudge (iter-0 text is not accepted as the answer), then the
        # model's text is streamed on the second pass.
        assert seen == {"planning": 1, "tool_calls": 2}
        assert "Recovered" in "".join(chunk.text for chunk in chunks)

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

        async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
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

    @pytest.mark.asyncio
    async def test_retryable_error_after_successful_tool_preserves_evidence(self):
        """A rate limit on the post-tool synthesis call must not erase a
        successful tool result or turn the whole request into an error.

        This is the exact user-visible failure mode: Cerebras completes
        web_search, then rejects the follow-up model call with HTTP 429.
        """
        from adapters.ollama import ToolCallResult
        from core.models import ToolResult
        from core.obs import ObsCollector

        loop = AgentLoop(adapter=MagicMock())
        seen = {"calls": 0}
        rate_limit = (
            'cerebras returned 429: {"error":{"type":"rate_limit_exceeded",'
            '"message":"Too many requests"}}'
        )

        async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
            seen["calls"] += 1
            if seen["calls"] == 1:
                return ToolCallResult(
                    tool_name="web_search",
                    tool_args={"query": "trending news August 15 2026"},
                )

            async def _stream():
                yield StreamChunk(text="", done=True, error=rate_limit)

            return _stream()

        async def dispatch(*args, **kwargs):
            return (
                ToolResult(
                    source="web_search",
                    content="Headline A — verified search result",
                ),
                False,
                0,
            )

        mock_adapter = MagicMock()
        mock_adapter.chat_with_tools = chat_with_tools
        mock_adapter.chat = lambda *args, **kwargs: iter(())
        obs = ObsCollector()
        with patch("core.agent.loop.dispatch_with_retry", dispatch):
            chunks = [
                chunk
                async for chunk in loop.run(
                    messages=[{"role": "user", "content": "whats trending today"}],
                    intent=Intent.WEB_SEARCH,
                    initial_tool_result=None,
                    available_tools=[],
                    adapter=mock_adapter,
                    obs=obs,
                    skip_planning=True,
                )
            ]

        full = "".join(chunk.text for chunk in chunks)
        assert seen["calls"] == 2
        assert not [chunk.error for chunk in chunks if chunk.error]
        assert "rate-limited the final synthesis call" in full
        assert "Headline A" in full
        assert any(event.type == "agent_loop_degraded" for event in obs.history())
        assert any(event.type == "tool_call" for event in obs.history())
