"""Regression tests for freshness-aware current-data synthesis."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from core.agent.synthesizer import (
    AnswerSynthesizer,
    _check_sufficiency,
    _extract_web_search,
)
from core.models import Intent, RiskLevel, StreamChunk, ToolResult


_CURRENT_QUERY = "What's the weather like in Kitengela now?"

# Fixture dates are relative to today so the tests stay green on any calendar
# day: the "current" block is dated today and the "stale" block is 6 days old.
# (The synthesizer computes freshness against `date.today()` internally, so a
# hardcoded "current" date silently rots the moment the calendar rolls over.)
_TODAY = date.today()
_STALE = _TODAY - timedelta(days=6)


def _block_date(d: date, month_fmt: str) -> str:
    """Format a date without zero-padded days (matches real-world snippets)."""
    return f"{d.strftime(month_fmt)} {d.day}, {d.year}"


_SEARCH_RESULTS = f"""1. **Weather Kitengela today - Meteobox.ca**
   https://today.example/weather
   Weather forecast Kitengela {_block_date(_TODAY, '%b.')}. Clear morning, 19°C.

2. **WindBorne Systems current conditions**
   https://old.example/weather
   Current conditions: 19°C, partly cloudy. Updated Saturday, {_block_date(_STALE, '%B')}.
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
        today=_TODAY,
        user_question=query,
    )

    assert _block_date(_STALE, '%B') not in extracted.raw_content
    assert _block_date(_TODAY, '%b.') in extracted.raw_content
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
    assert _block_date(_STALE, '%B') not in prompt
    assert _block_date(_TODAY, '%b.') in prompt
    assert "19°C" in result.answer


@pytest.mark.asyncio
async def test_synthesis_refuses_stale_only_current_data() -> None:
    stale_only = f"""1. **WindBorne Systems current conditions**
   https://old.example/weather
   Current conditions: 19°C, partly cloudy. Updated Saturday, {_block_date(_STALE, '%B')}.
"""
    adapter = _RecordingAdapter()
    extracted = _extract_web_search(
        stale_only,
        today=_TODAY,
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
