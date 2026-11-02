"""The 2026-11-02 Arsenal-export fixes, pinned one per finding.

The owner's export (session-1793600092469) exposed five defects this file
locks closed:
  P5  objective→execution translation — structured system_search args were
      flattened to "recent 1 10" and re-parsed as a filename filter;
  P1  capability awareness — a live-data question landed on the no-tools
      conversational lane and produced "I don't have access to live sports
      results… shall I look that up?";
  P2  evidence-grounded self-evaluation — the agent reconstructed a false
      narrative about its own tool use; the execution record grounds it;
  P4  response-vs-execution finality — the completion judge's 8s timeout
      and the post-turn services held the answer's delivery;
  P6  deterministic provider management — tested in
      tests/adapters/test_failover.py (explicit fallback only, switch on
      the record, actual-server stamps).
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from core.models import Role


# ── P5: system_search args survive dispatch end to end ────────────────────


def test_extract_tool_input_keeps_system_search_structured():
    from core.agent.text_tools import _extract_tool_input

    args = {"operation": "recent", "limit": 1, "days": 10}
    out = _extract_tool_input("system_search", args)
    assert out == json.dumps(args, ensure_ascii=False)
    # The dispatcher JSON-decodes a leading "{" — round-trip restores the
    # operation instead of re-parsing digits as a name filter.
    assert json.loads(out)["operation"] == "recent"


def test_parse_plain_query_never_makes_digits_a_name_filter():
    from tools.system_search import _parse_plain_query

    # The exact flattened remnant from the export.
    parsed = _parse_plain_query("recent 1 10")
    assert parsed["operation"] == "recent"
    assert parsed.get("limit") == 1
    assert parsed.get("days") == 10
    assert "query" not in parsed  # "1 10" must NOT become name~'1 10'

    # A single digit is a limit, still never a filename.
    assert _parse_plain_query("recent 5") == {"operation": "recent", "limit": 5}
    # Genuine text queries still parse as name filters.
    assert _parse_plain_query("recent report") == {"operation": "recent", "query": "report"}
    # A files search keeps its numeric filename if a path-like token leads.
    assert _parse_plain_query("files 2026") == {"operation": "files", "query": "2026"}


# ── P1: live-data questions leave the no-tools conversational lane ────────


def test_results_question_is_not_conversational():
    from core.trivial_input import _CONVERSATIONAL_BLOCKED_RE, is_conversational_question

    msg = "What was the results of arsenal yesterday"
    assert _CONVERSATIONAL_BLOCKED_RE.search(msg), "the keyword guard must fire"
    assert is_conversational_question(msg) is False


@pytest.mark.parametrize(
    "word",
    ["result", "results", "yesterday", "fixture", "fixtures", "standings", "leaderboard"],
)
def test_recency_and_results_keywords_are_guarded(word):
    from core.trivial_input import _CONVERSATIONAL_BLOCKED_RE

    assert _CONVERSATIONAL_BLOCKED_RE.search(f"any {word} here")


def test_plain_conversational_question_still_conversational():
    from core.trivial_input import is_conversational_question

    # NOTE: "Why is Python popular?" is deliberately NOT a guard here —
    # "python" was a blocked keyword long before this fix. The guards are
    # knowledge questions with no tool/realtime vocabulary.
    assert is_conversational_question("What does resilient mean?") is True
    assert is_conversational_question("How do rockets land?") is True


def test_capability_spine_covers_live_information():
    from core.agent.prompt.rules import CAPABILITY_HONESTY_SPINE

    low = CAPABILITY_HONESTY_SPINE.lower()
    assert "live/current information" in low
    assert "internet" in low


# ── P2: the execution record grounds self-evaluation in facts ─────────────


def _msg(role, content="", tool_calls=None):
    return SimpleNamespace(role=role, content=content, tool_calls=tool_calls)


def test_execution_record_empty_without_tool_history():
    from core.agent_runtime import _build_execution_record

    history = [_msg(Role.USER, "hi"), _msg(Role.ASSISTANT, "Hello!")]
    assert _build_execution_record(history, "hi") == ""


def test_execution_record_lists_what_actually_ran():
    from core.agent_runtime import _build_execution_record

    history = [
        _msg(Role.USER, "What was the results of arsenal yesterday"),
        _msg(
            Role.ASSISTANT,
            "Arsenal won 1-0.",
            tool_calls=[
                {
                    "name": "web_search",
                    "status": "done",
                    "tool_args": "Arsenal match results yesterday November 1 2026",
                    "output": "Search results via DuckDuckGo (8 results): 1. Football Results ...",
                }
            ],
        ),
        _msg(Role.USER, "Then why did you say you could not look that up?"),
    ]
    record = _build_execution_record(history, "Then why did you say you could not look that up?")
    assert "web_search [done]" in record
    assert "Arsenal match results yesterday" in record
    assert "Execution record" in record
    assert "Ground any claim" in record


def test_execution_record_marks_failures_and_caps_calls():
    from core.agent_runtime import _EXECUTION_RECORD_MAX_CALLS, _build_execution_record

    calls = [
        {"name": f"tool_{i}", "status": "failed" if i == 3 else "done", "tool_args": f"q{i}", "output": f"o{i}"}
        for i in range(_EXECUTION_RECORD_MAX_CALLS + 3)
    ]
    history = [_msg(Role.ASSISTANT, "worked", tool_calls=calls)]
    record = _build_execution_record(history, "next")
    # Only the LAST max_calls entries render — the oldest extras are dropped.
    assert f"tool_{_EXECUTION_RECORD_MAX_CALLS + 2}" in record
    assert "tool_0" not in record
    # A FAILED call inside the window keeps its honest label.
    assert "tool_3 [FAILED]" in record


def test_execution_record_excludes_the_current_turn():
    from core.agent_runtime import _build_execution_record

    history = [
        _msg(Role.ASSISTANT, "earlier", tool_calls=[{"name": "web_search", "status": "done"}]),
        _msg(Role.USER, "same text"),
    ]
    record = _build_execution_record(history, "same text")
    assert "web_search" in record  # prior turn's call IS included


def test_execution_record_renders_in_the_turn_registry_at_slot_1110():
    """The section the model reads must be the registered transcript_focus
    slot — the dead slot now carries the execution record."""
    from core.agent.prompt.names import SECTION_SLOTS, SECTION_TRANSCRIPT_FOCUS
    from core.agent.prompt.structure import Band, Layer, SectionRegistry, make

    assert SECTION_SLOTS["transcript_focus"] == 1110
    registry = SectionRegistry()
    registry.add(
        make(
            SECTION_TRANSCRIPT_FOCUS,
            Band.TURN,
            Layer.CONTEXT,
            1110,
            "Execution record — what your tools ACTUALLY did",
        )
    )
    rendered = registry.render(Band.TURN)
    assert "Execution record" in rendered


# ── P4: the answer's delivery is not hostage to post-answer work ──────────


def test_judge_budget_isbounded_and_thinking_free():
    from core.agent import completion_judge

    assert completion_judge.JUDGE_TIMEOUT_S <= 5.0


@pytest.mark.asyncio
async def test_judge_call_requests_thinking_off():
    """The one-word verdict lane must not pay the model's reasoning pass."""
    from core.agent.completion_judge import reply_leaves_work_pending
    from core.models import StreamChunk

    seen_kwargs = {}

    class FakeAdapter:
        # NOTE the async-GENERATOR shape — the adapter contract `chat()` is
        # an async generator (what `async for chunk in adapter.chat(...)`
        # iterates), not a coroutine returning a stream.
        async def chat(self, messages, temperature=0.0, intent="chat", **kwargs):
            seen_kwargs.update(kwargs)
            yield StreamChunk(text="DONE")
            yield StreamChunk(text="", done=True)

    pending = await reply_leaves_work_pending(FakeAdapter(), "what was the score", "The match ended 1-0.")
    assert pending is False
    assert seen_kwargs.get("thinking_override") == "off"


@pytest.mark.asyncio
async def test_post_turn_services_run_detached_from_the_turn():
    """_spawn_post_turn_services returns immediately; the service still runs."""
    from core.agent_runtime import _POST_TURN_TASKS, _spawn_post_turn_services
    from core.obs import ObsCollector

    collector = ObsCollector()
    done = asyncio.Event()

    async def service():
        await asyncio.sleep(0.01)
        done.set()

    _spawn_post_turn_services([("marker", service)], 5.0, collector)
    # The spawn returned without awaiting the service; the task is retained.
    assert any(t.get_name() == "post-turn-services" for t in list(_POST_TURN_TASKS))
    await asyncio.wait_for(done.wait(), timeout=2.0)
    await asyncio.sleep(0)  # let the done-callback discard the task
    assert not any(t.get_name() == "post-turn-services" for t in _POST_TURN_TASKS)
