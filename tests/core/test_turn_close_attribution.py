"""Turn-close attribution tests.

The owner filmed a turn where the reply was fully on screen while the panel
still reported Working/Deep diving and Stop stayed live: the loop's
post-answer lanes (acceptance gate, completion judge, rescue/synthesis)
held the tail after the last token, and nothing on the wire distinguished
"the answer is final" from "the answer is still being written".

Contract under test:
  1. A plain reply turn yields a `response_ready` marker chunk BEFORE the
     terminal done chunk, and the terminal usage carries `turn_stages`
     (turn_started → response_ready) plus the `post_answer_lanes` record.
  2. The completion judge's verdict fact carries its own wall time
     (elapsed_ms), so the judge's share of the post-answer window is
     attributable instead of unexplained silence.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from core.agent.completion_judge import SOURCE, reply_is_pending
from core.agent.loop import AgentLoop
from core.agent.turn_bus import TurnBus
from core.models import Intent, StreamChunk


def _stub_adapter(reply: str) -> MagicMock:
    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        async def _stream():
            yield StreamChunk(text=reply, done=False)
            yield StreamChunk(text="", done=True)

        return _stream()

    async def chat(messages, temperature=0.4):
        return
        yield

    adapter = MagicMock()
    adapter.chat_with_tools = chat_with_tools
    adapter.chat = chat
    return adapter


async def _collect(loop: AgentLoop, adapter) -> list:
    chunks = []
    with patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
         patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x):
        async for chunk in loop.run(
            messages=[{"role": "user", "content": "check git status"}],
            intent=Intent.SHELL,
            initial_tool_result=None,
            available_tools=[],
            adapter=adapter,
        ):
            chunks.append(chunk)
    return chunks


class TestResponseReadyMarker:
    @pytest.mark.asyncio
    async def test_marker_precedes_done_and_usage_carries_stages(self):
        loop = AgentLoop(adapter=MagicMock())
        chunks = await _collect(loop, _stub_adapter("All good - nothing to do."))

        marker_idx = next(
            (i for i, c in enumerate(chunks) if c.metadata.get("response_ready")),
            None,
        )
        done_idx = next((i for i, c in enumerate(chunks) if c.done), None)
        assert done_idx is not None, "turn never terminated"
        assert marker_idx is not None, "no response_ready marker on the wire"
        assert marker_idx < done_idx, "response_ready must precede the terminal done"

        marker = chunks[marker_idx].metadata["response_ready"]
        stages = marker.get("stages") or {}
        assert "turn_started" in stages, "turn_started missing from the stage map"
        assert "response_ready" in stages, "response_ready missing from the stage map"
        assert stages["turn_started"] <= stages["response_ready"]
        assert isinstance(marker.get("lanes"), dict)

        final_usage = chunks[done_idx].usage
        assert final_usage.get("turn_stages"), "terminal usage must carry turn_stages"
        assert final_usage.get("post_answer_lanes") is not None
        # The same attribution rides the usage channel that reaches the done
        # payload and the turn_complete metrics — keys must match the marker.
        assert final_usage["turn_stages"].get("response_ready") == stages["response_ready"]

    @pytest.mark.asyncio
    async def test_marker_stages_are_monotonic(self):
        loop = AgentLoop(adapter=MagicMock())
        chunks = await _collect(loop, _stub_adapter("Short answer."))
        marker = next(c.metadata["response_ready"] for c in chunks if c.metadata.get("response_ready"))
        stages = marker["stages"]
        stamps = [stages[k] for k in ("turn_started", "response_ready") if k in stages]
        assert stamps == sorted(stamps), "stage stamps must be monotonic"


class TestJudgeAttribution:
    @pytest.mark.asyncio
    async def test_verdict_fact_carries_elapsed_ms(self):
        async def judge_chat(messages, temperature=0.0, intent=None):
            yield StreamChunk(text="DONE", done=True)

        adapter = MagicMock()
        adapter.chat = judge_chat
        bus = TurnBus()
        pending = await reply_is_pending(bus, adapter, "check git status", "All done, nothing to do.")
        assert pending is False
        fact = bus.latest("verdict", source=SOURCE, step=0)
        assert fact is not None, "judge published no verdict fact"
        assert fact.value.get("verdict") == "done"
        assert isinstance(fact.value.get("elapsed_ms"), int), (
            "the verdict fact must carry the lane's wall time (elapsed_ms)"
        )
        assert fact.value["elapsed_ms"] >= 0
