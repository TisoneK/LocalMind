"""
E2E for the classify-flake → answer-from-history fallback (B-2026-08-18-5).

Transcript that motivated it: on a follow-up ("Why did you say Arsenal vs Man
City?") the weak model's classify JSON came back empty, so the turn degraded to
a canned context-free "I'm here and ready to help. Could you tell me a little
more…" — ignoring the whole conversation. Now, when classify flakes with nothing
to salvage, the loop answers the user's latest message directly from history.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core.agent.initialization import InitializationDecision, _FALLBACK_DIRECT_RESPONSE
from core.agent.loop import AgentLoop
from core.models import Intent, StreamChunk

_PARENT_CFG = SimpleNamespace(
    name="parent", max_iterations=8, max_wall_clock_secs=600.0,
    allowed_tools=None, tools_enabled=True,
)

_CONVERSATION = [
    {"role": "user", "content": "When is the first match of epl"},
    {"role": "assistant", "content": "The first match of the 2026-27 season is on August 21, 2026 — Arsenal vs Coventry City."},
    {"role": "user", "content": "Why did you say Arsenal vs Man City"},
]


async def _run(fake_init, chat_impl):
    loop = AgentLoop(adapter=MagicMock())
    adapter = MagicMock()
    adapter.chat = chat_impl
    chunks = []
    with patch.object(AgentLoop, "_initialize_parent_streaming", fake_init), \
         patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x):
        async for c in loop.run(
            messages=_CONVERSATION,
            intent=Intent.ANALYZE,
            initial_tool_result=None,
            available_tools=[],
            adapter=adapter,
            agent_config=_PARENT_CFG,
        ):
            chunks.append(c)
    return "".join(c.text for c in chunks if getattr(c, "text", None))


@pytest.mark.asyncio
async def test_flaked_classify_answers_from_history_not_canned():
    """classify returns nothing → the loop answers from the conversation, and
    the from-history chat receives the full history (so it can address the
    user's actual question)."""
    seen = {}

    async def fake_init(*_a, **_k):
        yield ("decision", InitializationDecision(
            mode="direct", response=_FALLBACK_DIRECT_RESPONSE, needs_history_answer=True,
        ))

    async def chat_impl(messages, temperature=0.4, intent="chat"):
        seen["messages"] = messages
        yield StreamChunk(text="I didn't say Man City — I said Arsenal vs Coventry City.", done=False)
        yield StreamChunk(text="", done=True)

    text = await _run(fake_init, chat_impl)

    # The real, context-aware answer is used …
    assert "Coventry City" in text
    assert "Man City" in text
    # … and the canned context-free fallback is NOT.
    assert "ready to help" not in text
    # The from-history call actually received the conversation (last user turn).
    assert any(m.get("content", "").startswith("Why did you say") for m in seen["messages"])


@pytest.mark.asyncio
async def test_flaked_classify_with_dead_chat_falls_back_to_canned():
    """If even the from-history chat yields nothing, the canned line is the
    last resort (never a silent empty turn)."""

    async def fake_init(*_a, **_k):
        yield ("decision", InitializationDecision(
            mode="direct", response=_FALLBACK_DIRECT_RESPONSE, needs_history_answer=True,
        ))

    async def dead_chat(messages, temperature=0.4, intent="chat"):
        return
        yield  # empty async generator

    text = await _run(fake_init, dead_chat)
    assert _FALLBACK_DIRECT_RESPONSE.split(".")[0] in text
