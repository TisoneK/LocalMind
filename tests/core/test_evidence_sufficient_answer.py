"""Evidence-sufficient → answer-only call.

Live baseline (bankofai/qwen3.8-flash, weather turn): after web_fetch put the
wttr.in JSON in the transcript, the loop still burned a full tool-schema-bearing
reasoning call (38s) deciding to answer, and weak models re-plan acquisition
instead of synthesizing. The fix: when the last successful real tool on a
web-acquisition intent was a substantive page fetch, the NEXT model call runs
without tool schemas (the adapter omits the tools key, so a native tool call is
impossible) plus a one-shot answer directive.

Contract under test:
  1. After a successful substantive web_fetch, the next call gets tools=[] and
     the [EVIDENCE SUFFICIENT] directive (obs: agent_loop_evidence_answer_call).
  2. The optimization does NOT fire for a failed fetch or a stub-sized fetch,
     for non-fetch tools, for non-web intents, or when the request is a
     multi-step task (save/write the fetched data…).
  3. The flag reflects the LAST tool: a later non-fetch tool clears it.
  4. If the answer-only reply narrates a further action, the turn-outcome
     recovery is FORCE_TOOL (restore tools), not SYNTHESIZE — and the next
     iteration receives its tool schemas again.
  5. classify_turn_outcome: tools_withheld flips the post-evidence-narration
     recovery to FORCE_TOOL; hedge/empty keep their documented recovery.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from adapters.ollama import ToolCallResult
from core.agent.loop import AgentLoop
from core.agent.turn_outcome import Recovery, TurnOutcome, classify_turn_outcome
from core.models import Intent, RiskLevel, StreamChunk, ToolResult
from core.obs import ObsCollector

_PAGE = (
    '{"current_condition": [{"observation_time": "08:08 AM", "temp_C": "26", '
    '"temp_F": "79", "weatherCode": "113", "lang_en": [{"value": "Sunny"}], '
    '"weatherDesc": [{"value": "Sunny"}], "windspeedKmph": "12", '
    '"winddir16Point": "ESE", "humidity": "30", "visibility": "10", '
    '"pressure": "1015", "cloudcover": "18", "FeelsLikeC": "23", '
    '"FeelsLikeF": "73", "uvIndex": "9"}], '
    '"weather": [{"date": "2026-09-07", "mintempC": "13", "maxtempC": "27", '
    '"hourly": [{"time": "900", "tempC": "24", "chanceofrain": "0"}, '
    '{"time": "1200", "tempC": "26", "chanceofrain": "2"}]}], '
    '"nearest_area": [{"areaName": [{"value": "Nairobi"}], '
    '"country": [{"value": "Kenya"}], "latitude": "-1.283", "longitude": "36.817"}]}'
)


def _answer_stream(text: str):
    async def _stream():
        yield StreamChunk(text=text, done=False)
        yield StreamChunk(text="", done=True)

    return _stream()


async def _run_turn(
    *,
    intent: Intent,
    user_message: str,
    chat_with_tools,
    dispatch,
    thinker,
    agent_config=None,
):
    """Shared harness: run one loop turn with fakes; return (obs, chunks, calls)."""
    loop = AgentLoop(adapter=MagicMock())
    mock_adapter = MagicMock()
    mock_adapter.chat_with_tools = chat_with_tools
    mock_adapter.chat = lambda *a, **k: iter(())
    mock_adapter.thinking_enabled = True
    obs = ObsCollector()
    calls: list[dict] = []

    async def _recording_chat(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        calls.append({"tools": list(tools), "messages": list(messages)})
        return await chat_with_tools(messages, tools, temperature, intent, tool_choice)

    mock_adapter.chat_with_tools = _recording_chat
    chunks = []
    with patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
         patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x), \
         patch("core.agent.loop.dispatch_with_retry", side_effect=dispatch), \
         patch("core.agent.thinker.Thinker", thinker):
        async for chunk in loop.run(
            messages=[{"role": "user", "content": user_message}],
            intent=intent,
            initial_tool_result=None,
            available_tools=[],
            adapter=mock_adapter,
            obs=obs,
            agent_config=agent_config,
            skip_planning=True,
        ):
            chunks.append(chunk)
    return obs, chunks, calls


def _thinker_stub():
    class _Noop:
        def __init__(self, timeout_secs=30.0):
            self.last_analysis = None

        async def consult(self, evidence, adapter, temperature=0.4):
            if False:
                yield  # pragma: no cover

    return _Noop


# ── 1. The core behavior ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_next_call_after_substantive_fetch_is_answer_only():
    """After a successful ~substantive web_fetch, the next model call must
    carry NO tool schemas and the [EVIDENCE SUFFICIENT] directive — the model
    synthesizes instead of re-reasoning over the tool roster."""
    turn_calls: dict[str, list] = {"n": 0}

    async def chat(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        turn_calls["n"] += 1
        if turn_calls["n"] == 1:
            return ToolCallResult(
                tool_name="web_fetch",
                tool_args={"url": "https://wttr.in/Nairobi?format=j1"},
                raw_content="",
            )
        return _answer_stream("**26°C (79°F)** in Nairobi right now — sunny.")

    async def dispatch(intent_name, raw_input, allowed_tool_names=None, adapter=None, **kwargs):
        return (
            ToolResult(content=_PAGE, risk=RiskLevel.LOW, source="web_fetch"),
            False,
            0,
        )

    obs, chunks, calls = await _run_turn(
        intent=Intent.WEB_FETCH,
        user_message="What's the weather in Nairobi today?",
        chat_with_tools=chat,
        dispatch=dispatch,
        thinker=_thinker_stub(),
    )

    assert len(calls) >= 2
    first, second = calls[0], calls[1]
    assert first["tools"], "the first call must offer tools (the fetch)"
    assert second["tools"] == [], (
        "the call after a substantive fetch must be answer-only (no tool schemas)"
    )
    second_user_text = " ".join(
        str(m.get("content", "")) for m in second["messages"] if m.get("role") == "user"
    )
    assert "[EVIDENCE SUFFICIENT]" in second_user_text
    assert any(
        e.type == "agent_loop_evidence_answer_call" for e in obs.history()
    ), "the answer-only call must be observable"
    user_text = "".join(c.text for c in chunks)
    assert "26°C" in user_text, "the turn must end with the fetched answer"
    assert "[EVIDENCE SUFFICIENT]" not in user_text, "the directive must never leak to the user"


# ── 2. The exclusions ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_answer_only_call_after_failed_fetch():
    async def chat(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        return _answer_stream("The fetch failed; here's what I know.")

    async def dispatch(intent_name, raw_input, allowed_tool_names=None, adapter=None, **kwargs):
        return (
            ToolResult(content="[Tool 'web_fetch' failed: timeout]", risk=RiskLevel.LOW, source="web_fetch"),
            True,  # FAILED
            0,
        )

    _obs, _chunks, calls = await _run_turn(
        intent=Intent.WEB_FETCH,
        user_message="Fetch https://example.com/page",
        chat_with_tools=chat,
        dispatch=dispatch,
        thinker=_thinker_stub(),
    )
    assert calls[0]["tools"], "tools must be offered on the first call"
    assert all(c["tools"] for c in calls), "a failed fetch must never suppress the tool surface"


@pytest.mark.asyncio
async def test_no_answer_only_call_for_stub_sized_fetch():
    async def chat(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        return _answer_stream("Redirect stub only — trying another source.")

    async def dispatch(intent_name, raw_input, allowed_tool_names=None, adapter=None, **kwargs):
        return (
            ToolResult(content="Moved permanently.", risk=RiskLevel.LOW, source="web_fetch"),
            False,
            0,
        )

    _obs, _chunks, calls = await _run_turn(
        intent=Intent.WEB_FETCH,
        user_message="Fetch https://example.com/redirect",
        chat_with_tools=chat,
        dispatch=dispatch,
        thinker=_thinker_stub(),
    )
    assert all(c["tools"] for c in calls), "a stub-sized fetch is not evidence"


@pytest.mark.asyncio
async def test_no_answer_only_call_for_non_fetch_tool():
    """sysinfo/calculator-style tools don't mark evidence-complete, even on a
    web intent with a large observation."""
    async def chat(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        return _answer_stream("Here is the system overview.")

    async def dispatch(intent_name, raw_input, allowed_tool_names=None, adapter=None, **kwargs):
        return (
            ToolResult(content=_PAGE, risk=RiskLevel.LOW, source="sysinfo"),
            False,
            0,
        )

    _obs, _chunks, calls = await _run_turn(
        intent=Intent.WEB_SEARCH,
        user_message="What's the weather like and how is my CPU doing?",
        chat_with_tools=chat,
        dispatch=dispatch,
        thinker=_thinker_stub(),
    )
    assert all(c["tools"] for c in calls), "only fetch-class tools mark evidence-complete"


@pytest.mark.asyncio
async def test_answer_only_call_keys_on_the_tool_not_the_declared_intent():
    """The parent path enters the loop with a fixed generic intent, so the
    optimization must key on WHAT RAN (a substantive page fetch), not on the
    declared intent."""
    step = {"n": 0}

    async def chat(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        step["n"] += 1
        if step["n"] == 1:
            return ToolCallResult(
                tool_name="web_fetch",
                tool_args={"url": "https://wttr.in/Nairobi?format=j1"},
                raw_content="",
            )
        return _answer_stream("Nairobi is 26°C and sunny.")

    async def dispatch(intent_name, raw_input, allowed_tool_names=None, adapter=None, **kwargs):
        return (
            ToolResult(content=_PAGE, risk=RiskLevel.LOW, source="web_fetch"),
            False,
            0,
        )

    _obs, _chunks, calls = await _run_turn(
        intent=Intent.ANALYZE,
        user_message="Summarize https://wttr.in/Nairobi?format=j1",
        chat_with_tools=chat,
        dispatch=dispatch,
        thinker=_thinker_stub(),
    )
    assert len(calls) >= 2
    assert calls[0]["tools"], "the fetch call must offer tools"
    assert calls[1]["tools"] == [], (
        "a fetch under the generic ANALYZE intent still marks evidence-complete"
    )


@pytest.mark.asyncio
async def test_no_answer_only_call_when_request_continues_past_answer():
    """'fetch … and save it to a file' is a mid-task fetch — tools stay."""
    async def chat(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        return _answer_stream("Saving the fetched data now.")

    async def dispatch(intent_name, raw_input, allowed_tool_names=None, adapter=None, **kwargs):
        return (
            ToolResult(content=_PAGE, risk=RiskLevel.LOW, source="web_fetch"),
            False,
            0,
        )

    _obs, _chunks, calls = await _run_turn(
        intent=Intent.WEB_FETCH,
        user_message="Fetch https://wttr.in/Nairobi?format=j1 and save the JSON to weather.json",
        chat_with_tools=chat,
        dispatch=dispatch,
        thinker=_thinker_stub(),
    )
    assert all(c["tools"] for c in calls), "a save/write request must keep its tools"


@pytest.mark.asyncio
async def test_later_non_fetch_tool_clears_the_flag():
    """fetch → sysinfo → call: the last successful tool is sysinfo, so the
    final call keeps its tools (the flag reflects the LAST tool, not the best
    fetch in history)."""
    calls_seen: list[list] = []
    step = {"n": 0}

    async def chat(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        step["n"] += 1
        calls_seen.append(list(tools))
        if step["n"] == 1:
            return ToolCallResult(
                tool_name="web_fetch",
                tool_args={"url": "https://wttr.in/Nairobi?format=j1"},
                raw_content="",
            )
        if step["n"] == 2:
            return ToolCallResult(
                tool_name="sysinfo",
                tool_args={"query": "cpu"},
                raw_content="",
            )
        return _answer_stream("Weather is 26C; CPU load is normal.")

    async def dispatch(intent_name, raw_input, allowed_tool_names=None, adapter=None, **kwargs):
        if "wttr" in str(raw_input):
            return (
                ToolResult(content=_PAGE, risk=RiskLevel.LOW, source="web_fetch"),
                False,
                0,
            )
        return (
            ToolResult(content="CPU: 12% utilized", risk=RiskLevel.LOW, source="sysinfo"),
            False,
            0,
        )

    _obs, _chunks, calls = await _run_turn(
        intent=Intent.WEB_SEARCH,
        user_message="What's the weather and my CPU load?",
        chat_with_tools=chat,
        dispatch=dispatch,
        thinker=_thinker_stub(),
    )
    assert len(calls) >= 3
    assert calls[-1]["tools"], "a later non-fetch tool must clear the answer-only state"


# ── 3. The FORCE_TOOL escape hatch ───────────────────────────────────────────


def test_tools_withheld_flips_post_evidence_narration_to_force_tool():
    a = classify_turn_outcome(
        has_tool_calls=False,
        final_text="Let me fetch the forecast from another source.",
        tools_ran_this_turn=True,
        is_post_evidence_narration=True,
    )
    assert a.recovery is Recovery.SYNTHESIZE, "baseline unchanged without suppression"

    b = classify_turn_outcome(
        has_tool_calls=False,
        final_text="Let me fetch the forecast from another source.",
        tools_ran_this_turn=True,
        is_post_evidence_narration=True,
        tools_withheld=True,
    )
    assert b.outcome is TurnOutcome.INCOMPLETE
    assert b.recovery is Recovery.FORCE_TOOL, (
        "narration under withheld tools means the model NEEDS a tool"
    )


def test_tools_withheld_keeps_other_recoveries_unchanged():
    hedge = classify_turn_outcome(
        has_tool_calls=False,
        final_text="Would you like me to also check the weekend?",
        tools_ran_this_turn=True,
        is_hedge_after_evidence=True,
        tools_withheld=True,
    )
    assert hedge.recovery is Recovery.SYNTHESIZE, "hedges still want synthesis"

    empty = classify_turn_outcome(
        has_tool_calls=False,
        final_text="",
        tools_ran_this_turn=True,
        tools_withheld=True,
    )
    assert empty.recovery is Recovery.SYNTHESIZE, "empty with evidence still synthesizes"

    pending = classify_turn_outcome(
        has_tool_calls=False,
        final_text="Now deleting the file.",
        tools_ran_this_turn=True,
        is_pending_action_narration=True,
        tools_withheld=True,
    )
    assert pending.recovery is Recovery.FORCE_TOOL, "pending actions always force the tool"


@pytest.mark.asyncio
async def test_narrated_answer_only_reply_restores_tools_next_iteration():
    """End-to-end: the answer-only reply narrates a second fetch → the gate
    rejects it (FORCE_TOOL), the text is withheld, and the NEXT call has its
    tool schemas again."""
    from agents.base_agent import AgentConfig
    from core.agent.constants import AGENT_ALLOWED_TOOLS

    step = {"n": 0}
    calls_seen: list[list] = []

    async def chat(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        step["n"] += 1
        calls_seen.append(list(tools))
        if step["n"] == 1:
            return ToolCallResult(
                tool_name="web_fetch",
                tool_args={"url": "https://wttr.in/Nairobi?format=j1"},
                raw_content="",
            )
        if step["n"] == 2:
            # Narration under withheld tools: wants another fetch it can't name.
            return _answer_stream("Let me fetch the coastal radar for rainfall too.")
        # After FORCE_TOOL: give a grounded final answer.
        return _answer_stream("26°C and sunny; no rain expected today.")

    async def dispatch(intent_name, raw_input, allowed_tool_names=None, adapter=None, **kwargs):
        return (
            ToolResult(content=_PAGE, risk=RiskLevel.LOW, source="web_fetch"),
            False,
            0,
        )

    obs, chunks, calls = await _run_turn(
        intent=Intent.WEB_FETCH,
        user_message="What's the weather in Nairobi today?",
        chat_with_tools=chat,
        dispatch=dispatch,
        thinker=_thinker_stub(),
        agent_config=AgentConfig(
            name="parent",
            max_iterations=20,
            allowed_tools=AGENT_ALLOWED_TOOLS,
        ),
    )

    assert len(calls) >= 3, f"expected 3+ model calls, got {len(calls)}"
    assert calls[1]["tools"] == [], "call 2 was the answer-only call"
    assert calls[2]["tools"], "FORCE_TOOL must restore the tool schemas"
    user_text = "".join(c.text for c in chunks)
    assert "Let me fetch the coastal radar" not in user_text, (
        "the narrated iteration must be withheld from the user stream"
    )
    assert any(
        e.type == "agent_loop_iteration_discarded" for e in obs.history()
    ), "the discarded iteration must be observable"
    assert "26°C and sunny" in user_text, "the turn ends with the grounded answer"
