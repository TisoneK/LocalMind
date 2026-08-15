"""Session 238 regression tests — forced-tool recovery in the agent loop.

Step 0 of the Thinker/Agent rebuild (see `.context/memory/tasks/current.md`):
the agent loop's tool-calling must actually FIRE. Session 237's live trace
showed `gemini-2.5-flash` (via the OpenAI-compat endpoint) returning an EMPTY
response on the first execute tool call (788ms, 0 tools), and other models
returning text-without-tool on iteration 0. Both previously failed the turn
with the "empty response" message or streamed unverified text as the answer.

The fix has two layers:
  1. The loop passes `tool_choice="required"` on the FIRST tool iteration
     (adapter now honors it; see tests/adapters/test_zen_deepseek_fixes.py
     for the payload-level tests).
  2. If the model STILL returns empty or text-without-tool on iteration 0,
     the loop reprompts ONCE with a forced-tool nudge (bounded), then falls
     back to the honest Session 115 fast-fail / text streaming.

Contract under test:
  - empty iter-0 → nudge → the next call can produce a real tool call
  - text-without-tool iter-0 → nudge → next call can produce a real tool call
  - a second empty reply (iteration > 0) fails honestly, no further nudge
  - a second text reply (iteration > 0) is accepted and streamed
  - the nudge is bounded — never a spin
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from adapters.ollama import ToolCallResult
from core.agent.loop import AgentLoop
from core.models import Intent, RiskLevel, StreamChunk, ToolResult


async def _run(loop, adapter, intent=Intent.SHELL, message="list files"):
    chunks = []
    with patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
         patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x), \
         patch("core.agent.loop.dispatch_with_retry", side_effect=_fake_dispatch):
        async for chunk in loop.run(
            messages=[{"role": "user", "content": message}],
            intent=intent,
            initial_tool_result=None,
            available_tools=[],
            adapter=adapter,
        ):
            chunks.append(chunk)
    return chunks


def _fake_dispatch(intent, raw_input, **kwargs):
    return (
        ToolResult(
            content="file1.txt\nfile2.txt",
            risk=RiskLevel.LOW,
            source="shell",
        ),
        False,
        0,
    )


def _empty_stream():
    async def _gen():
        yield StreamChunk(text="", done=False)
        yield StreamChunk(text="", done=True)
    return _gen()


def _text_stream(text):
    async def _gen():
        yield StreamChunk(text=text, done=False)
        yield StreamChunk(text="", done=True)
    return _gen()


class TestEmptyIter0Nudge:
    @pytest.mark.asyncio
    async def test_empty_then_nudge_then_tool_call_runs(self):
        """The money case: an empty iter-0 response gets ONE forced-tool
        nudge; the next call CAN produce a real tool call that executes —
        instead of failing the turn with 'empty response' (Session 237)."""
        loop = AgentLoop(adapter=MagicMock())
        seen = {"calls": 0, "nudge_seen": False}

        async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
            seen["calls"] += 1
            if seen["calls"] == 1:
                # gemini-2.5-flash behavior: empty on the first tool call.
                assert tool_choice == "required", "iter-0 tool call must force tool_choice"
                return _empty_stream()
            if seen["calls"] == 2:
                # The nudge must be visible in this call's messages.
                joined = " ".join(m.get("content", "") or "" for m in messages).lower()
                seen["nudge_seen"] = "requires a tool call" in joined
                return ToolCallResult(
                    tool_name="shell",
                    tool_args={"command": "ls -la"},
                    raw_content="",
                )
            # After the tool ran, the model goes quiet again → honest fail
            # surfaces the tool evidence (iteration != 0: no second nudge).
            return _empty_stream()

        mock_adapter = MagicMock()
        mock_adapter.chat_with_tools = chat_with_tools
        mock_adapter.chat = _text_stream("")

        chunks = await _run(loop, mock_adapter)
        full = "".join(c.text for c in chunks)

        assert seen["calls"] == 3, f"expected empty→nudge→tool→fail, got {seen['calls']} calls"
        assert seen["nudge_seen"], "the forced-tool nudge must reach the model"
        assert "file1.txt" in full, (
            f"the tool must have run and its evidence must surface, got {full!r}"
        )
        assert "empty response" in full, (
            f"the honest fast-fail must still apply after the tool evidence, got {full!r}"
        )

    @pytest.mark.asyncio
    async def test_empty_after_a_tool_does_not_nudge(self):
        """Once a tool has run (iteration > 0), an empty reply fails honestly
        WITHOUT a nudge — the nudge is only for the FIRST tool call."""
        loop = AgentLoop(adapter=MagicMock())
        seen = {"calls": 0}

        async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
            seen["calls"] += 1
            if seen["calls"] == 1:
                return ToolCallResult(
                    tool_name="shell",
                    tool_args={"command": "ls -la"},
                    raw_content="",
                )
            return _empty_stream()

        mock_adapter = MagicMock()
        mock_adapter.chat_with_tools = chat_with_tools
        mock_adapter.chat = _text_stream("")

        chunks = await _run(loop, mock_adapter)
        full = "".join(c.text for c in chunks)

        assert seen["calls"] == 2, "empty after a tool must fail immediately (no nudge)"
        assert "empty response" in full


class TestTextWithoutToolIter0Nudge:
    @pytest.mark.asyncio
    async def test_text_then_nudge_then_tool_call_runs(self):
        """Text-without-tool on iter-0 gets one nudge; the next call can
        produce a real tool call (Session 237: the 'fabrication warning' used
        to just stream the text as the answer)."""
        loop = AgentLoop(adapter=MagicMock())
        seen = {"calls": 0, "tool_evidence_seen": False}

        async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
            seen["calls"] += 1
            if seen["calls"] == 1:
                assert tool_choice == "required"
                return _text_stream("Let me tell you about the files without looking.")
            if seen["calls"] == 2:
                return ToolCallResult(
                    tool_name="shell",
                    tool_args={"command": "ls -la"},
                    raw_content="",
                )
            # After the tool ran, the model synthesizes its answer.
            joined = " ".join(m.get("content", "") or "" for m in messages).lower()
            seen["tool_evidence_seen"] = "file1.txt" in joined
            return _text_stream("Done with the task.")

        mock_adapter = MagicMock()
        mock_adapter.chat_with_tools = chat_with_tools
        mock_adapter.chat = _text_stream("")

        chunks = await _run(loop, mock_adapter)
        full = "".join(c.text for c in chunks)

        assert seen["calls"] == 3, f"text→nudge→tool→answer, got {seen['calls']} calls"
        assert seen["tool_evidence_seen"], "the tool result must be in the model's context"
        assert "Done with the task." in full

    @pytest.mark.asyncio
    async def test_text_twice_is_accepted_not_looped(self):
        """If the model insists on text after the single nudge (iteration != 0
        now), the text is accepted and streamed — never an unbounded retry."""
        loop = AgentLoop(adapter=MagicMock())
        seen = {"calls": 0}

        async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
            seen["calls"] += 1
            return _text_stream("There are two files in the folder.")

        mock_adapter = MagicMock()
        mock_adapter.chat_with_tools = chat_with_tools
        mock_adapter.chat = _text_stream("")

        chunks = await _run(loop, mock_adapter)
        full = "".join(c.text for c in chunks)

        assert seen["calls"] == 2, f"exactly one nudge, then accept — got {seen['calls']} calls"
        assert "There are two files in the folder." in full


class TestNonToolIntentsUntouched:
    @pytest.mark.asyncio
    async def test_chat_intent_empty_response_does_not_nudge(self):
        """Non-agent intents keep the pre-Session-238 behavior: no nudge, no
        tool_choice forcing."""
        loop = AgentLoop(adapter=MagicMock())
        seen = {"calls": 0, "tool_choice": "unset"}

        async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
            seen["calls"] += 1
            seen["tool_choice"] = tool_choice
            return _empty_stream()

        mock_adapter = MagicMock()
        mock_adapter.chat_with_tools = chat_with_tools
        mock_adapter.chat = _text_stream("")

        chunks = await _run(loop, mock_adapter, intent=Intent.CHAT, message="hi")
        full = "".join(c.text for c in chunks)

        assert seen["calls"] == 1, "chat intent must not be nudged"
        assert seen["tool_choice"] is None, "chat intent must not force tool_choice"
        assert "empty response" in full
