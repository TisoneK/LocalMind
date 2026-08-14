"""Regression tests for the AgentLoop web-search result boundary."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from core.agent.loop import AgentLoop
from core.agent.models import AgentTrace


@pytest.mark.asyncio
async def test_web_search_handler_accepts_reasoning_keyword() -> None:
    """The tool-call path supplies structured step reasoning to the handler.

    Keep this contract explicit: a search result must still be synthesized
    instead of failing before the user-facing answer is produced.
    """
    loop = AgentLoop(adapter=MagicMock())
    loop._synthesizer.enabled = False
    trace = AgentTrace()

    with patch(
        "core.agent.loop.dispatch_with_retry",
        new=AsyncMock(return_value=(None, False, 0)),
    ):
        chunks = [
            chunk
            async for chunk in loop._handle_web_search_result(
                safe_obs="1. **Kitengela weather**\n   https://example.com\n   Current conditions",
                query="Kitengela weather now",
                thought="search for current weather",
                reasoning="The request asks for live local conditions.",
                iteration=0,
                trace=trace,
                user_question="What's the weather like in Kitengela now?",
            )
        ]
        # Let the fire-and-forget raw-result write finish under the mock.
        await asyncio.sleep(0)

    assert chunks[-1].done is True
    assert trace.steps[-1].tool_name == "web_search"
    assert trace.steps[-1].thought == "search for current weather"
