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

    assert statuses[0] == "I’m preparing an execution plan before using tools…"
    assert "I’m creating a short plan before I act…" in statuses
    assert any(status.startswith("Plan ready (2 steps).") for status in statuses)
    assert "I’m deciding the next action from the current evidence…" in statuses
    assert "I’m verifying the result against the objective…" in statuses
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
