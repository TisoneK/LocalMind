"""Tests for the post-loop evidence synthesis safety net (B-2026-08-20-7, Session 308).

Covers:
- ``_post_loop_synthesis_from_evidence`` fires when tools ran + final text empty
- It does NOT fire when no tools ran (no evidence to synthesize from)
- It does NOT fire when observation_log is empty
- It yields the synthesized text when the synthesis returns non-empty (>= 20 chars)
- It yields nothing when the synthesis returns empty/trivial (caller falls through)
- The integration: the empty-response fallthrough path calls the post-loop synthesis
  before yielding the empty-message fallback
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.agent.loop import AgentLoop
from core.models import StreamChunk


def _make_trace(*, has_tool_step: bool = True, final_response: str = ""):
    """Build a minimal trace-like object."""
    steps = []
    if has_tool_step:
        steps.append(
            SimpleNamespace(
                tool_name="shell",
                tool_input="ls /tmp",
                tool_failed=False,
                observation="file1.txt\nfile2.txt\nfile3.txt",
            )
        )
    steps.append(SimpleNamespace(tool_name="", tool_input=None, tool_failed=False, observation=""))
    return SimpleNamespace(
        steps=steps,
        success_criteria=[],
        final_response=final_response,
        gate_summary="",
        empty_reasoning_recoveries=2,  # cap hit
        tool_talk_recoveries=0,
        empty_response=True,
        hit_limit=False,
        iterations_used=6,
    )


def _make_loop_with_synth(synth_text: str = ""):
    """Build an AgentLoop with a mocked _force_final_answer that yields synth_text."""
    loop = AgentLoop(adapter=None)

    async def _fake_force(*args, **kwargs):
        if synth_text:
            yield StreamChunk(text=synth_text, done=False)

    loop._force_final_answer = _fake_force
    return loop


@pytest.mark.asyncio
async def test_post_loop_synthesis_fires_when_tools_ran_and_text_empty():
    """Tools ran + empty final text → synthesis fires and yields the synthesized text."""
    loop = _make_loop_with_synth("The /tmp directory contains file1.txt, file2.txt, and file3.txt.")
    trace = _make_trace(has_tool_step=True, final_response="")
    obs = MagicMock()

    chunks = []
    async for chunk in loop._post_loop_synthesis_from_evidence(
        loop_messages=[{"role": "user", "content": "list /tmp"}],
        observation_log="[shell] ls /tmp → file1.txt\nfile2.txt\nfile3.txt",
        active_adapter=MagicMock(),
        trace=trace,
        provider_usage={},
        intent=None,
        obs=obs,
    ):
        chunks.append(chunk)

    assert len(chunks) == 1
    assert "file1.txt" in chunks[0].text
    obs.emit.assert_called_with("post_loop_synthesis", intent="", chars=pytest.approx(len(chunks[0].text), abs=50))


@pytest.mark.asyncio
async def test_post_loop_synthesis_does_not_fire_when_no_tools_ran():
    """No tools ran → no evidence to synthesize from → yields nothing."""
    loop = _make_loop_with_synth("This should not be yielded.")
    trace = _make_trace(has_tool_step=False, final_response="")

    chunks = []
    async for chunk in loop._post_loop_synthesis_from_evidence(
        loop_messages=[{"role": "user", "content": "hi"}],
        observation_log="",
        active_adapter=MagicMock(),
        trace=trace,
        provider_usage={},
        intent=None,
        obs=None,
    ):
        chunks.append(chunk)

    assert chunks == []


@pytest.mark.asyncio
async def test_post_loop_synthesis_does_not_fire_when_observation_log_empty():
    """Tools ran but observation_log is empty → nothing to synthesize from."""
    loop = _make_loop_with_synth("This should not be yielded.")
    trace = _make_trace(has_tool_step=True, final_response="")

    chunks = []
    async for chunk in loop._post_loop_synthesis_from_evidence(
        loop_messages=[{"role": "user", "content": "list /tmp"}],
        observation_log="",
        active_adapter=MagicMock(),
        trace=trace,
        provider_usage={},
        intent=None,
        obs=None,
    ):
        chunks.append(chunk)

    assert chunks == []


@pytest.mark.asyncio
async def test_post_loop_synthesis_yields_nothing_when_synth_empty():
    """Synthesis returned empty → yields nothing (caller falls through to empty-message)."""
    loop = _make_loop_with_synth("")  # empty synthesis
    trace = _make_trace(has_tool_step=True, final_response="")

    chunks = []
    async for chunk in loop._post_loop_synthesis_from_evidence(
        loop_messages=[{"role": "user", "content": "list /tmp"}],
        observation_log="[shell] ls /tmp → file1.txt",
        active_adapter=MagicMock(),
        trace=trace,
        provider_usage={},
        intent=None,
        obs=None,
    ):
        chunks.append(chunk)

    assert chunks == []


@pytest.mark.asyncio
async def test_post_loop_synthesis_yields_nothing_when_synth_trivial():
    """Synthesis returned < 20 chars → too trivial, yields nothing."""
    loop = _make_loop_with_synth("ok")  # 2 chars — trivial
    trace = _make_trace(has_tool_step=True, final_response="")

    chunks = []
    async for chunk in loop._post_loop_synthesis_from_evidence(
        loop_messages=[{"role": "user", "content": "list /tmp"}],
        observation_log="[shell] ls /tmp → file1.txt",
        active_adapter=MagicMock(),
        trace=trace,
        provider_usage={},
        intent=None,
        obs=None,
    ):
        chunks.append(chunk)

    assert chunks == []


@pytest.mark.asyncio
async def test_post_loop_synthesis_sets_one_shot_thinking_off():
    """The synthesis call disables thinking (plain synthesis, not tool loop)."""
    loop = _make_loop_with_synth("A real synthesized answer from the evidence gathered.")
    trace = _make_trace(has_tool_step=True, final_response="")
    adapter = MagicMock()

    chunks = []
    async for chunk in loop._post_loop_synthesis_from_evidence(
        loop_messages=[{"role": "user", "content": "list /tmp"}],
        observation_log="[shell] ls /tmp → file1.txt",
        active_adapter=adapter,
        trace=trace,
        provider_usage={},
        intent=None,
        obs=None,
    ):
        chunks.append(chunk)

    # The adapter had _one_shot_thinking_off set to True (a real attribute on
    # the OpenAI-compat adapter; MagicMock accepts any attribute set).
    assert adapter._one_shot_thinking_off is True
    assert len(chunks) == 1


@pytest.mark.asyncio
async def test_post_loop_synthesis_handles_synthesis_exception():
    """If _force_final_answer raises, the method yields nothing (defensive)."""
    loop = AgentLoop(adapter=None)

    async def _raising_force(*args, **kwargs):
        raise RuntimeError("synthesis provider error")
        yield  # pragma: no cover — never reached

    loop._force_final_answer = _raising_force
    trace = _make_trace(has_tool_step=True, final_response="")

    chunks = []
    async for chunk in loop._post_loop_synthesis_from_evidence(
        loop_messages=[{"role": "user", "content": "list /tmp"}],
        observation_log="[shell] ls /tmp → file1.txt",
        active_adapter=MagicMock(),
        trace=trace,
        provider_usage={},
        intent=None,
        obs=None,
    ):
        chunks.append(chunk)

    assert chunks == []  # exception caught, nothing yielded


# ── B-2026-09-05-5: _force_final_answer must stream thinking LIVE ────────────
# The old implementation buffered thinking chunks in _final_chunks and flushed
# them after the whole synthesis stream completed. The frontend's thinking
# timer (first→last thinking_token wall time) then measured ~1ms for a full
# paragraph of reasoning — the hit-limit transcript case ("Thinking 1ms").
# Regression: the FIRST thinking chunk must arrive while the adapter stream is
# still unconsumed — i.e. streamed as the model produces it, not held back.

@pytest.mark.asyncio
async def test_force_final_answer_streams_thinking_live():
    loop = AgentLoop(adapter=None)

    class _TrackingAdapter:
        """Fake synthesis adapter that records when its stream is exhausted."""

        def __init__(self):
            self.exhausted = False

        async def chat(self, messages, temperature=0.4, **_kw):
            yield StreamChunk(text="", thinking="start", done=False)
            yield StreamChunk(text="", thinking="I should report the observed tool outputs honestly.", done=False)
            yield StreamChunk(text="Here is what I found.", done=False)
            yield StreamChunk(text="", done=True)
            self.exhausted = True

    adapter = _TrackingAdapter()
    collected: list[str] = []
    thinking_seen_before_exhaustion = False
    async for chunk in loop._force_final_answer(
        loop_messages=[{"role": "user", "content": "wrap up"}],
        observation_log="[shell] ls /tmp → file1.txt",
        active_adapter=adapter,
        trace=None,
        provider_usage={},
    ):
        if getattr(chunk, "thinking", ""):
            collected.append(("thinking", chunk.thinking))
            if not adapter.exhausted:
                thinking_seen_before_exhaustion = True
        elif chunk.text:
            collected.append(("text", chunk.text))

    kinds = [k for k, _ in collected]
    assert "thinking" in kinds, f"thinking chunks must still be forwarded, got {kinds}"
    assert thinking_seen_before_exhaustion, (
        "the first thinking chunk arrived only after the adapter stream was "
        "fully consumed — thinking is being buffered to the flush again"
    )
    # Reasoning must still precede the answer text (ThinkingBlock before body).
    first_thinking = kinds.index("thinking")
    texts = [i for i, k in enumerate(kinds) if k == "text" and collected[i][1]]
    assert texts and first_thinking < texts[0]
