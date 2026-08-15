"""Parent-agent workflow progress regressions.

The parent loop must behave like an agent at the presentation boundary:
acknowledge the work, plan, act, verify, and only then finish. Provider
planning/reasoning tokens are internal execution context, not chat UI content.
"""

from __future__ import annotations

import pytest

from core.agent.loop import AgentLoop
from core.models import Intent, StreamChunk


class _WorkflowAdapter:
    """Adapter with a plan stream and a final no-tool answer."""

    async def chat(self, messages, temperature=0.1, intent="chat"):
        yield StreamChunk(
            text=(
                "UNDERSTANDING: inspect the project\n"
                "STEPS:\n"
                "1. Use shell to inspect the current project state\n"
                "2. Use shell to verify the result\n"
                "ARGS_PRECHECK: no additional arguments needed"
            )
        )

    async def chat_with_tools(self, messages, tools, temperature=0.3, intent=None):
        async def _stream():
            yield StreamChunk(text="The requested work is complete.", done=False)
            yield StreamChunk(text="", done=True)

        return _stream()


@pytest.mark.asyncio
async def test_parent_exposes_lifecycle_status_not_raw_planner_text():
    loop = AgentLoop(adapter=_WorkflowAdapter())

    chunks = [
        chunk
        async for chunk in loop.run(
            messages=[{"role": "user", "content": "inspect the project"}],
            intent=Intent.SHELL,
            initial_tool_result=None,
            available_tools=[],
            adapter=_WorkflowAdapter(),
        )
    ]

    statuses = [chunk.status for chunk in chunks if chunk.status]
    thinking = [chunk.thinking for chunk in chunks if chunk.thinking]
    text = "".join(chunk.text for chunk in chunks)

    # ADR-37: the hardcoded stage-name narration is gone. The parent no longer
    # emits theater status lines ("preparing an execution plan…", "creating a
    # short plan…", "Plan ready…", "deciding the next action…", "verifying the
    # result…") — real model output (ack + thinking) is the only status signal.
    assert not any("preparing an execution plan" in s for s in statuses)
    assert not any("creating a short plan" in s for s in statuses)
    assert not any(s.startswith("Plan ready") for s in statuses)
    assert not any("deciding the next action" in s for s in statuses)
    assert not any("verifying the result" in s for s in statuses)
    assert thinking == []
    assert "The requested work is complete." in text
    assert any(chunk.done for chunk in chunks)


@pytest.mark.asyncio
async def test_parent_does_not_turn_provider_planner_text_into_user_thinking():
    """Planner output remains available to execution internally, but is not
    forwarded as raw UNDERSTANDING/STEPS text to the chat surface."""
    loop = AgentLoop(adapter=_WorkflowAdapter())
    chunks = []

    async for chunk in loop.run(
        messages=[{"role": "user", "content": "inspect the project"}],
        intent=Intent.SHELL,
        initial_tool_result=None,
        available_tools=[],
        adapter=_WorkflowAdapter(),
    ):
        chunks.append(chunk)

    assert all("UNDERSTANDING:" not in (chunk.text or "") for chunk in chunks)
    assert all("STEPS:" not in (chunk.text or "") for chunk in chunks)
    assert all("UNDERSTANDING:" not in (chunk.thinking or "") for chunk in chunks)
    assert all("STEPS:" not in (chunk.thinking or "") for chunk in chunks)


@pytest.mark.asyncio
async def test_tool_observation_returns_to_parent_before_final_answer():
    """A search result is evidence for the parent, not the user's final reply.

    The parent must get another decision turn after the tool result so it can
    fetch/verify/replan before producing the final response.
    """
    from unittest.mock import patch

    from adapters.ollama import ToolCallResult
    from core.models import RiskLevel, ToolResult

    class _SearchAdapter(_WorkflowAdapter):
        def __init__(self):
            self.tool_call_messages = []
            self.calls = 0

        async def chat_with_tools(self, messages, tools, temperature=0.3, intent=None):
            self.calls += 1
            if self.calls == 1:
                return ToolCallResult(
                    tool_name="web_search",
                    tool_args={"query": "current weather in Kitengela"},
                    raw_content="I should search for current conditions.",
                )

            self.tool_call_messages.append(messages)

            async def _stream():
                yield StreamChunk(
                    text="I checked the search evidence and verified the result before answering.",
                    done=False,
                )
                yield StreamChunk(text="", done=True)

            return _stream()

    adapter = _SearchAdapter()
    search_result = ToolResult(
        content="Kitengela: sunny, 26°C. Source: https://example.test/weather",
        risk=RiskLevel.LOW,
        source="web_search",
        success=True,
    )

    with patch("core.agent.loop.dispatch_with_retry", return_value=(search_result, False, 0)):
        chunks = [
            chunk
            async for chunk in AgentLoop(adapter=adapter).run(
                messages=[{"role": "user", "content": "What's the weather in Kitengela?"}],
                intent=Intent.WEB_SEARCH,
                initial_tool_result=None,
                available_tools=[],
                adapter=adapter,
            )
        ]

    text = "".join(chunk.text for chunk in chunks)
    statuses = [chunk.status for chunk in chunks if chunk.status]
    assert adapter.calls == 2, "the parent must make a post-observation decision"
    assert adapter.tool_call_messages, "the second decision must receive tool context"
    assert any(
        message.get("role") == "tool" and "26°C" in message.get("content", "")
        for message in adapter.tool_call_messages[0]
    )
    assert "I checked the search evidence" in text
    assert "Kitengela: sunny, 26°C" not in text
    assert any(status.startswith("Done — Searching") for status in statuses)
    assert sum(chunk.done for chunk in chunks) == 1
