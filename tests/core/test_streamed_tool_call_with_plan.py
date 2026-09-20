"""A weak model that writes its next tool call as TEXT inside a streamed reply, on a turn that
has a plan.

The loop's streamed-reply branch read `result.raw_content` for the tool-call event, but there
`result` is the stream itself, so the turn died with "'async_generator' object has no
attribute 'raw_content'" right after a search and a fetch. The plan made this reachable for
plain lookups ("today's livescore results").
"""
import asyncio
from unittest.mock import MagicMock, patch

from core.agent.lookup_plan import LOOKUP_STEPS
from core.agent.loop import AgentLoop
from core.models import Intent, StreamChunk, ToolResult
from core.obs import ObsCollector

DSML_FETCH = (
    '<｜DSML｜tool_calls><｜DSML｜invoke name="web_fetch">'
    '<｜DSML｜parameter name="url" string="true">https://scores.example.com/today</｜DSML｜parameter>'
    "</｜DSML｜invoke></｜DSML｜tool_calls>"
)


def _run():
    from adapters.ollama import ToolCallResult

    seen = {"calls": 0}

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        seen["calls"] += 1
        if seen["calls"] == 1:
            return ToolCallResult(tool_name="web_search", tool_args={"query": "today's livescore results"})

        async def _stream():
            if seen["calls"] == 2:
                # The model answers with its NEXT tool call written as text.
                yield StreamChunk(text=DSML_FETCH, done=False)
            else:
                yield StreamChunk(text="Arsenal 2-1 Chelsea; Real Madrid 3-0 Getafe.", done=False)
            yield StreamChunk(text="", done=True)

        return _stream()

    async def dispatch(*args, **kwargs):
        return ToolResult(source="web", content="Scores: Arsenal 2-1 Chelsea. Real Madrid 3-0 Getafe."), False, 0

    adapter = MagicMock()
    adapter.chat_with_tools = chat_with_tools
    adapter.chat = lambda *a, **k: iter(())
    obs = ObsCollector()

    async def go():
        with patch("core.agent.loop.dispatch_with_retry", dispatch):
            return [
                c
                async for c in AgentLoop(adapter=MagicMock()).run(
                    messages=[{"role": "user", "content": "today's livescore results"}],
                    intent=Intent.WEB_SEARCH,
                    initial_tool_result=None,
                    available_tools=[],
                    adapter=adapter,
                    obs=obs,
                    skip_planning=True,
                    plan_steps=list(LOOKUP_STEPS),
                )
            ]

    return asyncio.run(go()), obs, seen


def test_a_streamed_text_tool_call_does_not_crash_a_planned_turn():
    chunks, obs, seen = _run()
    assert not [c.error for c in chunks if c.error]
    assert seen["calls"] >= 3  # search -> streamed fetch -> answer
    assert "Arsenal" in "".join(c.text for c in chunks)


def test_the_streamed_tool_call_is_reported_like_any_other():
    _, obs, _ = _run()
    events = obs.drain_matching({"tool_call"})
    fetches = [e.data for e in events if e.data.get("tool") == "web_fetch"]
    assert {e.get("status") for e in fetches} >= {"started", "done"}


def test_plan_steps_tick_as_the_tools_finish():
    _, obs, _ = _run()
    completed = [e.data.get("id") for e in obs.drain_matching({"todo_completed"})]
    assert "plan-0" in completed  # search finished
    assert "plan-1" in completed  # the fetch finished


# ── no plan given (the request wording was not recognised): the first web tool seeds it ──


def _run_without_a_plan():
    from adapters.ollama import ToolCallResult

    seen = {"calls": 0}

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        seen["calls"] += 1
        if seen["calls"] == 1:
            return ToolCallResult(tool_name="web_search", tool_args={"query": "today's livescore results"})

        async def _stream():
            yield StreamChunk(text="Arsenal 2-1 Chelsea.", done=False)
            yield StreamChunk(text="", done=True)

        return _stream()

    async def dispatch(*args, **kwargs):
        return ToolResult(source="web", content="Scores: Arsenal 2-1 Chelsea."), False, 0

    adapter = MagicMock()
    adapter.chat_with_tools = chat_with_tools
    adapter.chat = lambda *a, **k: iter(())
    obs = ObsCollector()

    async def go():
        with patch("core.agent.loop.dispatch_with_retry", dispatch):
            return [
                c
                async for c in AgentLoop(adapter=MagicMock()).run(
                    messages=[{"role": "user", "content": "today's livescore results"}],
                    intent=Intent.WEB_SEARCH,
                    initial_tool_result=None,
                    available_tools=[],
                    adapter=adapter,
                    obs=obs,
                    skip_planning=True,
                )
            ]

    return asyncio.run(go()), obs


def test_the_first_web_tool_seeds_the_whole_plan_when_none_was_given():
    _, obs = _run_without_a_plan()
    created = [e.data for e in obs.drain_matching({"todo_created"})]
    texts = [c.get("text") for c in created if str(c.get("id", "")).startswith("plan-")]
    assert texts == list(LOOKUP_STEPS)
    # ...and not a lone synthetic per-tool task on top of it.
    assert not [c for c in created if str(c.get("id", "")).startswith("syn-")]


def test_the_seeded_plan_ticks_when_the_search_finishes():
    _, obs = _run_without_a_plan()
    completed = [e.data.get("id") for e in obs.drain_matching({"todo_completed"})]
    assert "plan-0" in completed
