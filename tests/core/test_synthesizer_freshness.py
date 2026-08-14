"""Regression tests for freshness-aware current-data synthesis."""

from __future__ import annotations

from datetime import date

import pytest
from core.agent.synthesizer import (
    AnswerSynthesizer,
    _check_sufficiency,
    _extract_web_search,
)
from core.models import Intent, RiskLevel, StreamChunk, ToolResult


_CURRENT_QUERY = "What's the weather like in Kitengela now?"
_SEARCH_RESULTS = """1. **Weather Kitengela today - Meteobox.ca**
   https://today.example/weather
   Weather forecast Kitengela Aug. 14, 2026. Clear morning, 19°C.

2. **WindBorne Systems current conditions**
   https://old.example/weather
   Current conditions: 19°C, partly cloudy. Updated Saturday, August 8, 2026.
"""


class _RecordingAdapter:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def chat(self, messages, temperature=0.3, intent="chat"):
        self.messages = messages
        yield StreamChunk(
            text="Current conditions are 19°C and clear. Source: https://today.example/weather",
            done=False,
        )
        yield StreamChunk(text="", done=True)


@pytest.mark.parametrize("query", [_CURRENT_QUERY, "current temperature in Kitengela"])
def test_current_search_filters_older_dated_result_blocks(query: str) -> None:
    extracted = _extract_web_search(
        _SEARCH_RESULTS,
        today=date(2026, 8, 14),
        user_question=query,
    )

    assert "August 8, 2026" not in extracted.raw_content
    assert "Aug. 14, 2026" in extracted.raw_content
    assert extracted.fields["freshness"]["current_blocks"] == 1
    assert extracted.fields["freshness"]["stale_blocks"] == 1
    assert extracted.fields["freshness"]["filtered_blocks"] == 1


@pytest.mark.asyncio
async def test_synthesis_uses_current_result_without_stale_competitor() -> None:
    adapter = _RecordingAdapter()
    synthesizer = AnswerSynthesizer()
    result = await synthesizer.synthesize(
        tool_results=[
            ToolResult(
                content=_SEARCH_RESULTS,
                risk=RiskLevel.LOW,
                source="web_search",
            )
        ],
        intent=Intent.WEB_SEARCH,
        user_question=_CURRENT_QUERY,
        adapter=adapter,
    )

    prompt = adapter.messages[0]["content"]
    assert "August 8, 2026" not in prompt
    assert "Aug. 14, 2026" in prompt
    assert "19°C" in result.answer


@pytest.mark.asyncio
async def test_synthesis_refuses_stale_only_current_data() -> None:
    stale_only = """1. **WindBorne Systems current conditions**
   https://old.example/weather
   Current conditions: 19°C, partly cloudy. Updated Saturday, August 8, 2026.
"""
    adapter = _RecordingAdapter()
    extracted = _extract_web_search(
        stale_only,
        today=date(2026, 8, 14),
        user_question=_CURRENT_QUERY,
    )
    sufficiency = _check_sufficiency(extracted, _CURRENT_QUERY)

    assert sufficiency.reason.endswith("current data was not verified")

    result = await AnswerSynthesizer().synthesize(
        tool_results=[ToolResult(content=stale_only, risk=RiskLevel.LOW, source="web_search")],
        intent=Intent.WEB_SEARCH,
        user_question=_CURRENT_QUERY,
        adapter=adapter,
    )

    assert result.is_gap_report is True
    assert "current data was not verified" in result.answer
    assert adapter.messages == []
