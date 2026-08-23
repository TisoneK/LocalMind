"""
Session 374: tool-talk recovery must be intent-gated (the "garbled Approach"
greeting bug).

Live trace (user's app, deepseek-v4-flash): the user sent "Hi" and the turn
streamed a garbled "Approach" thinking block in which the model wrestled with
"You described wanting to use a tool but did not call it. You MUST use the
tool-calling API directly…" — a message the user never sent. Root cause: the
CHAT-intent greeting happened to mention tools ("I'm ready to help — file
work, research, coding…"), which tripped `_is_tool_talk`; the loop then
suppressed the greeting and injected the corrective nudge — even though a
conversational turn requires NO tool. The small model spiraled trying to
reconcile the demand with "Hi needs no tool".

Fix: the tool-talk recovery now runs only for AGENT_INTENTS (the same gate the
fabrication / forced-tool checks use). Tool-talk narration is only a failure
when the turn is supposed to use tools.

These tests prove:
1. A CHAT-intent turn whose text matches `_is_tool_talk` is NOT recovered:
   exactly one model call, text streamed through, no corrective injection.
2. An agent-intent turn with the same text still recovers (regression guard):
   a second call happens and carries the corrective message.
"""
from unittest.mock import MagicMock, patch

import pytest

from core.agent.loop import AgentLoop
from core.models import Intent, StreamChunk


def _stream_text(tool_talk_line: str):
    """Async generator stream: one narration line, then done."""

    async def _stream():
        yield StreamChunk(text=tool_talk_line, done=False)
        yield StreamChunk(text="", done=True)

    return _stream()


@pytest.mark.asyncio
async def test_chat_intent_tool_talk_is_not_recovered():
    """A greeting that mentions tools must NOT get the corrective nudge.

    Before the fix this produced the user-visible bug: the loop suppressed
    the greeting, injected \"You described wanting to use a tool but did not
    call it\", and the free-tier model's reasoning spiraled around the
    contradiction — the garbled \"Approach\" block.
    """
    loop = AgentLoop(adapter=MagicMock())
    calls = {"n": 0}

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        calls["n"] += 1
        return _stream_text(
            "Hi there! I'm searching for a good way to help you today. What can I do for you?"
        )

    async def empty_chat(messages, temperature=0.4):
        return
        yield

    mock_adapter = MagicMock()
    mock_adapter.chat_with_tools = chat_with_tools
    mock_adapter.chat = empty_chat

    out = []
    with (
        patch("core.agent.loop.dispatch_with_retry", return_value=("", False, 0)),
        patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x),
        patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x),
    ):
        async for chunk in loop.run(
            messages=[{"role": "user", "content": "Hi"}],
            intent=Intent.CHAT,
            initial_tool_result=None,
            available_tools=[],
            adapter=mock_adapter,
        ):
            out.append(chunk)

    assert calls["n"] == 1, "CHAT turn must not be retried with a tool-talk correction"
    text = "".join(c.text for c in out if c.text)
    assert "Hi there!" in text, "the greeting must stream through as the answer"


@pytest.mark.asyncio
async def test_agent_intent_tool_talk_still_recovers():
    """Agent-intent turns keep the recovery: nudge + retry (regression guard)."""
    loop = AgentLoop(adapter=MagicMock())
    seen_messages: list[list[dict]] = []

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        seen_messages.append(messages)
        return _stream_text("Let me search for the weather in Nairobi")

    async def empty_chat(messages, temperature=0.4, **kwargs):
        return
        yield

    mock_adapter = MagicMock()
    mock_adapter.chat_with_tools = chat_with_tools
    mock_adapter.chat = empty_chat

    with (
        patch("core.agent.loop.dispatch_with_retry", return_value=("", False, 0)),
        patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x),
        patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x),
    ):
        async for _ in loop.run(
            messages=[{"role": "user", "content": "check the weather in Nairobi"}],
            intent=Intent.WEB_SEARCH,
            initial_tool_result=None,
            available_tools=[],
            adapter=mock_adapter,
        ):
            pass

    assert len(seen_messages) >= 3, "agent-intent tool-talk must trigger a retry"
    # Iter 1 text-without-tool → forced-tool nudge; iter 2 tool-talk → the
    # corrective message; iter 3's messages carry it.
    any_corrective = any(
        any(
            isinstance(m.get("content"), str)
            and "You described wanting to use a tool but did not call it" in m["content"]
            for m in msgs
        )
        for msgs in seen_messages
    )
    assert any_corrective, "agent-intent tool-talk must inject the corrective nudge"


@pytest.mark.asyncio
async def test_chat_intent_no_tool_talk_still_answers():
    """Plain CHAT text (no tool-talk) is untouched — no regression on the norm."""
    loop = AgentLoop(adapter=MagicMock())
    calls = {"n": 0}

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        calls["n"] += 1
        return _stream_text("Hi there! 👋 I'm LocalMind, ready to help. What do you need?")

    async def empty_chat(messages, temperature=0.4):
        return
        yield

    mock_adapter = MagicMock()
    mock_adapter.chat_with_tools = chat_with_tools
    mock_adapter.chat = empty_chat

    out = []
    with (
        patch("core.agent.loop.dispatch_with_retry", return_value=("", False, 0)),
        patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x),
        patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x),
    ):
        async for chunk in loop.run(
            messages=[{"role": "user", "content": "Hi"}],
            intent=Intent.CHAT,
            initial_tool_result=None,
            available_tools=[],
            adapter=mock_adapter,
        ):
            out.append(chunk)

    assert calls["n"] == 1
    text = "".join(c.text for c in out if c.text)
    assert "ready to help" in text
