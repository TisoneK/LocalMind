"""Tests for the hedge detector + recovery-nudge context fix (B-2026-08-20-13, Session 314).

Covers:
- ``answer_hedges_after_evidence`` positive/negative cases
- the gate's new branch: when tools ran + answer hedges → re-prompt
- the one-shot guard: a second hedge doesn't re-nudge
- the recovery nudge now includes the user's original question
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.agent.loop import AgentLoop, answer_hedges_after_evidence


# ── Detector unit tests ─────────────────────────────────────────────────────


def test_hedge_positive_would_you_like():
    """The exact live-trace hedge from the user's transcript."""
    text = (
        "I found several weather sources for Kitengela, Kenya, but I can't "
        "access the detailed current weather information without fetching the "
        "specific pages. Would you like me to get the current weather from "
        "weather-atlas.com, or would you prefer a different source?"
    )
    assert answer_hedges_after_evidence(text) is True


def test_hedge_positive_which_source():
    text = "I found 3 sources. Which source would you prefer?"
    assert answer_hedges_after_evidence(text) is True


def test_hedge_positive_do_you_want_me_to():
    text = "Do you want me to fetch that page for you?"
    assert answer_hedges_after_evidence(text) is True


def test_hedge_positive_i_would_need_to_fetch():
    text = "I would need to fetch one of these pages to get the details."
    assert answer_hedges_after_evidence(text) is True


def test_hedge_negative_direct_answer():
    """A real synthesized answer must NOT trigger."""
    text = (
        "The current weather in Kitengela is 16°C and overcast, based on "
        "the search results. Humidity is at 65% with light winds from the east."
    )
    assert answer_hedges_after_evidence(text) is False


def test_hedge_negative_empty():
    assert answer_hedges_after_evidence("") is False
    assert answer_hedges_after_evidence(None) is False  # type: ignore[arg-type]


def test_hedge_negative_short_text():
    assert answer_hedges_after_evidence("ok") is False


# ── Gate integration tests ──────────────────────────────────────────────────


def _make_trace_with_tools(final_response: str):
    """Build a trace with tool evidence + a final-answer step."""
    return SimpleNamespace(
        steps=[
            # The observation is the evidence the answer's figures came from —
            # the grounding criterion reads it, so an answer quoting "16°C"
            # needs the results to actually contain 16°.
            SimpleNamespace(
                tool_name="web_search",
                tool_input="weather Kitengela",
                tool_failed=False,
                observation="8 results: Kitengela 16°C, overcast, humidity 70%",
            ),
            SimpleNamespace(tool_name="", tool_input=None, tool_failed=False),
        ],
        success_criteria=[],
        final_response=final_response,
        gate_summary="",
    )


@pytest.mark.asyncio
async def test_gate_reprompts_on_hedge_after_evidence():
    """Parent hedges after tools ran → gate injects [SYNTHESIZE] re-prompt."""
    loop = AgentLoop(adapter=None)
    trace = _make_trace_with_tools(
        "Would you like me to fetch the weather page for you?"
    )
    loop_messages = [{"role": "user", "content": "weather in Kitengela"}]

    suffix, is_final = await loop._acceptance_gate_at_final_answer(
        trace=trace, iteration=0, effective_max_iter=10,
        loop_messages=loop_messages, observation_log="[web_search] 8 results...",
        active_adapter=None, intent=None, obs=None, is_parent=True,  # type: ignore[arg-type]
    )

    assert is_final is False
    assert suffix == ""
    assert any("[SYNTHESIZE]" in str(m.get("content", "")) for m in loop_messages)


@pytest.mark.asyncio
async def test_gate_oneshot_guard_does_not_renudge_hedge_twice():
    """A second consecutive hedge does NOT re-nudge (one-shot bound)."""
    loop = AgentLoop(adapter=None)
    trace = _make_trace_with_tools("Would you like me to fetch it?")
    loop_messages = [
        {"role": "user", "content": "weather in Kitengela"},
        {"role": "assistant", "content": "Would you like me to fetch it?"},
        {"role": "user", "content": "\n[SYNTHESIZE] You gathered evidence but asked the user..."},
        {"role": "assistant", "content": "Would you like me to fetch it?"},
    ]
    original_len = len(loop_messages)

    suffix, is_final = await loop._acceptance_gate_at_final_answer(
        trace=trace, iteration=1, effective_max_iter=10,
        loop_messages=loop_messages, observation_log="[web_search] results",
        active_adapter=None, intent=None, obs=None, is_parent=True,  # type: ignore[arg-type]
    )

    assert is_final is True
    assert len(loop_messages) == original_len  # no new nudge


@pytest.mark.asyncio
async def test_gate_does_not_trigger_hedge_when_no_tools_ran():
    """No tools ran → hedge detector skipped (prose-commitment path owns that)."""
    loop = AgentLoop(adapter=None)
    trace = SimpleNamespace(
        steps=[SimpleNamespace(tool_name="", tool_input=None, tool_failed=False)],
        success_criteria=[], final_response="Would you like me to search?",
        gate_summary="",
    )
    loop_messages = [{"role": "user", "content": "hi"}]
    original_len = len(loop_messages)

    suffix, is_final = await loop._acceptance_gate_at_final_answer(
        trace=trace, iteration=0, effective_max_iter=10,
        loop_messages=loop_messages, observation_log="",
        active_adapter=None, intent=None, obs=None, is_parent=True,  # type: ignore[arg-type]
    )

    # No tools ran → no hedge nudge; the prose-commitment path may or may not
    # fire depending on the text. Either way, no [SYNTHESIZE] nudge.
    assert not any("[SYNTHESIZE]" in str(m.get("content", "")) for m in loop_messages)


@pytest.mark.asyncio
async def test_gate_does_not_trigger_hedge_on_direct_answer():
    """A direct synthesized answer after tools → accepted, no nudge."""
    loop = AgentLoop(adapter=None)
    trace = _make_trace_with_tools(
        "The weather in Kitengela is 16°C and overcast."
    )
    loop_messages = [{"role": "user", "content": "weather?"}]
    original_len = len(loop_messages)

    suffix, is_final = await loop._acceptance_gate_at_final_answer(
        trace=trace, iteration=0, effective_max_iter=10,
        loop_messages=loop_messages, observation_log="[web_search] results",
        active_adapter=None, intent=None, obs=None, is_parent=True,  # type: ignore[arg-type]
    )

    assert is_final is True
    assert len(loop_messages) == original_len


@pytest.mark.asyncio
async def test_gate_hedge_respects_iteration_cap():
    """At the iteration cap, the hedge detector does NOT re-nudge."""
    loop = AgentLoop(adapter=None)
    trace = _make_trace_with_tools("Would you like me to fetch it?")
    loop_messages = [{"role": "user", "content": "weather?"}]
    original_len = len(loop_messages)

    suffix, is_final = await loop._acceptance_gate_at_final_answer(
        trace=trace, iteration=9, effective_max_iter=10,  # iteration + 1 >= max
        loop_messages=loop_messages, observation_log="[web_search] results",
        active_adapter=None, intent=None, obs=None, is_parent=True,  # type: ignore[arg-type]
    )

    assert is_final is True
    assert len(loop_messages) == original_len


# ── Recovery nudge context test ─────────────────────────────────────────────


def test_recovery_nudge_includes_original_question():
    """The empty-reasoning recovery nudge must include
    the user's original question so the model can re-anchor. The old
    generic nudge caused the model to lose context ('I don't have any
    information about what the original task was')."""
    # Read the source to verify the nudge includes the question.
    import inspect

    source = inspect.getsource(AgentLoop.run)
    # The nudge must reference the user's original question.
    assert "_original_question" in source or "user's request was" in source, (
        "the recovery nudge must include the user's original question"
    )
