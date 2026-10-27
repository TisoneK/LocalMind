"""Evidence-grounding check tests.

Covers core.agent.evidence_grounding (the deterministic figure-presence
check) and its wiring into the acceptance gate's final-answer path.

The fixture answer is the real reply from the failed weather turn: a
forecast asserted after the only fetched page yielded navigation chrome
(language lists, promos, other cities' temperatures). Every figure in it
must either exist in the evidence or be flagged.
"""

from __future__ import annotations

import pytest
from core.agent.evidence_grounding import (
    check_answer_grounding,
    collect_evidence_text,
)
from core.agent.models import AgentStep, AgentTrace

# Navigation chrome like the one the failed fetch produced: temperatures
# exist, but only for OTHER places; no wind, sunshine, or rain-band figures.
METEOBLUE_STYLE_CHROME = """
Weather Kitengela - meteoblue
Get the meteoblue app
Download
AD FREE Remove ads for 9 € per year
News KijaniSpace: field progress and new talent in East Africa
Weather for popular places around Kitengela
Nairobi
26 °C /
18 °C
Kiambu
22 °C /
16 °C
Machakos
24 °C /
15 °C
Kajiado
25 °C /
16 °C
Ruiru
24 °C /
17 °C
More weather data
Wind Map
Meteograms
Back to top
© 2026 meteoblue
"""

FAILED_ANSWER = (
    "The weather in Kitengela today is expected to be 26°C high and 17°C low, "
    "with a wind speed of 24 km/h and 4 hours of sunshine. There is no "
    "precipitation expected today.\n\n"
    "Here's a brief outlook for the rest of the week:\n"
    "*   **Wednesday:** High 27°C, Low 18°C, 0-5 mm precipitation.\n"
    "*   **Thursday:** High 27°C, Low 18°C, 0-10 mm precipitation.\n"
    "*   **Friday:** High 25°C, Low 18°C, 10-20 mm precipitation.\n"
)


def test_failed_weather_answer_is_flagged_against_chrome():
    report = check_answer_grounding(FAILED_ANSWER, METEOBLUE_STYLE_CHROME)
    assert not report.grounded
    # 27°C appears nowhere; "0-5"/"0-10"/"10-20" bands appear nowhere as
    # standalone numbers; "4 hours" of sunshine appears nowhere.
    assert "27°C" in report.ungrounded
    assert any("0-5" in span for span in report.ungrounded)
    assert any("0-10" in span for span in report.ungrounded)
    assert any("10-20" in span for span in report.ungrounded)
    assert any("4 hours" in span for span in report.ungrounded)


def test_single_digit_runs_need_standalone_numbers():
    # "0-5 mm" must NOT pass because "2026" contains a 0 and "25 °C" a 5.
    evidence = "© 2026 meteoblue\nKajiado\n25 °C\n"
    report = check_answer_grounding("Expect 0-5 mm of rain.", evidence)
    assert not report.grounded
    # But a genuine "0-5" row in the evidence grounds it.
    ok = check_answer_grounding("Expect 0-5 mm of rain.", "Precipitation 0-5 mm today")
    assert ok.grounded


def test_figures_present_in_evidence_pass():
    evidence = (
        "Kitengela today: high 27°C, low 17°C, wind 12 km/h, "
        "chance of rain 20%, 8 hours of sunshine, 0-5 mm."
    )
    answer = (
        "Kitengela today: high 27°C, low 17°C, wind 12 km/h, "
        "chance of rain 20%, 8 hours of sunshine, 0-5 mm of rain."
    )
    report = check_answer_grounding(answer, evidence)
    assert report.grounded, report.ungrounded


def test_rounded_quotation_passes():
    # 27.5 in the evidence, "28°C" quoted... must FLAG (28 nowhere).
    # But "27°C" quoted from "27.5" passes (rounded down keeps the digits).
    evidence = "maxtempC: 27.5"
    assert check_answer_grounding("High of 27°C.", evidence).grounded
    assert not check_answer_grounding("High of 28°C.", evidence).grounded


def test_prices_and_humidity_checked():
    assert not check_answer_grounding("It costs $45 now.", "price list: $12.50, €9").grounded
    assert check_answer_grounding("It costs $12.50 now.", "price list: $12.50, €9").grounded
    assert not check_answer_grounding(
        "Humidity is 85% today.", "humidity around the lake: 70%"
    ).grounded


def test_no_figures_means_no_flags():
    report = check_answer_grounding(
        "The sources did not contain a forecast for Kitengela.", METEOBLUE_STYLE_CHROME
    )
    assert report.grounded
    assert report.checked == 0


def test_empty_inputs_are_safe():
    assert check_answer_grounding("", METEOBLUE_STYLE_CHROME).grounded
    # No evidence at all: every asserted figure is ungrounded by definition.
    assert not check_answer_grounding("26°C", "").grounded


def test_collect_evidence_text_covers_steps_and_messages():
    trace = AgentTrace(
        steps=[
            AgentStep(
                iteration=1,
                thought="",
                tool_name="web_fetch",
                tool_input="https://example.com",
                observation="page says maxtempC: 27.5 and mintempC: 17.1",
            )
        ]
    )
    messages = [
        {"role": "user", "content": "weather in Kitengela"},
        {"role": "assistant", "content": "earlier verified: wind 12 km/h"},
    ]
    pool = collect_evidence_text(trace, messages)
    assert "maxtempc: 27.5" in pool  # lowercased
    assert "https://example.com" in pool  # tool inputs included
    assert "wind 12 km/h" in pool  # conversation messages included


def test_collect_evidence_text_handles_non_dict_and_non_str():
    pool = collect_evidence_text(AgentTrace(), [None, {"role": "tool", "content": 123}, "raw str? no"])
    assert pool == ""


# ── Gate wiring ──────────────────────────────────────────────────────────────


def _gate_kwargs(trace, loop_messages, iteration=1, max_iter=8):
    """Build the acceptance gate's argument surface for a parent turn."""
    from core.agent.loop import AgentLoop

    loop = AgentLoop.__new__(AgentLoop)  # gate method needs no __init__ state
    return loop, dict(
        trace=trace,
        iteration=iteration,
        effective_max_iter=max_iter,
        loop_messages=loop_messages,
        observation_log="",
        active_adapter=None,
        intent=None,
        obs=None,
        is_parent=True,
        reformulated_message="whats the weather like in Kitengela",
    )


@pytest.mark.asyncio
async def test_gate_replans_on_ungrounded_answer():
    from core.models import Intent

    intent = Intent.WEB_SEARCH
    trace = AgentTrace(
        steps=[
            AgentStep(
                iteration=1,
                thought="",
                tool_name="web_fetch",
                tool_input="https://www.meteoblue.com/en/weather/week/kitengela_kenya_7931934",
                observation=METEOBLUE_STYLE_CHROME,
            )
        ],
        final_response=FAILED_ANSWER,
    )
    # Production appends the answer to loop_messages only AFTER the gate
    # passes — at gate time the pool holds tool results and history, so the
    # answer cannot ground its own figures.
    loop_messages = [
        {"role": "user", "content": "whats the weather like in Kitengela"},
    ]
    loop, kwargs = _gate_kwargs(trace, loop_messages)
    kwargs["intent"] = intent
    suffix, is_final = await loop._acceptance_gate_at_final_answer(**kwargs)
    assert is_final is False
    assert suffix == ""
    # The nudge names the invented figures and is one-shot marked.
    injected = loop_messages[-1]["content"]
    assert "[EVIDENCE GROUNDING]" in injected
    assert "27°C" in injected
    # A second gated attempt with the marker present no longer replans.
    suffix2, is_final2 = await loop._acceptance_gate_at_final_answer(**kwargs)
    assert is_final2 is True


@pytest.mark.asyncio
async def test_answer_as_trace_step_cannot_ground_itself():
    """The loop records the final answer as a tool-less step BEFORE gating;
    that record must never serve as evidence for the answer's own figures."""
    trace = AgentTrace(
        steps=[
            AgentStep(
                iteration=2,
                thought=FAILED_ANSWER[:500],
                tool_name=None,
                tool_input=None,
                observation=None,
            )
        ],
        final_response=FAILED_ANSWER,
    )
    pool = collect_evidence_text(trace, [])
    report = check_answer_grounding(FAILED_ANSWER, pool)
    assert not report.grounded


@pytest.mark.asyncio
async def test_gate_accepts_grounded_answer():
    from core.models import Intent

    intent = Intent.WEB_SEARCH
    grounded_answer = (
        "Kitengela today: high 26°C, low 18°C (meteoblue regional table). "
        "I could not find a Kitengela-specific forecast in the fetched page."
    )
    trace = AgentTrace(
        steps=[
            AgentStep(
                iteration=1,
                thought="",
                tool_name="web_fetch",
                tool_input="https://www.meteoblue.com/en/weather/week/kitengela_kenya_7931934",
                observation=METEOBLUE_STYLE_CHROME,
            )
        ],
        final_response=grounded_answer,
    )
    loop_messages = [
        {"role": "user", "content": "whats the weather like in Kitengela"},
    ]
    loop, kwargs = _gate_kwargs(trace, loop_messages)
    kwargs["intent"] = intent
    suffix, is_final = await loop._acceptance_gate_at_final_answer(**kwargs)
    assert is_final is True


@pytest.mark.asyncio
async def test_gate_skips_zero_tool_turns():
    from core.models import Intent

    intent = Intent.CHAT
    trace = AgentTrace(final_response="Sure — I can help with that tomorrow at 9:00.")
    loop_messages = [{"role": "user", "content": "thanks"}]
    loop, kwargs = _gate_kwargs(trace, loop_messages)
    kwargs["intent"] = intent
    _suffix, is_final = await loop._acceptance_gate_at_final_answer(**kwargs)
    assert is_final is True
