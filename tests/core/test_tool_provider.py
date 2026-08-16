"""Tests for the loop's ``_tool_provider`` metadata hook (Session 271).

The Actions card shows which backend engine answered (e.g. web_search's
winning search engine) as a badge. The provider is read from the tool result's
metadata by the loop and carried on the tool_call obs event.
"""

from core.agent.loop import _tool_provider
from core.models import RiskLevel, ToolResult


def _result(metadata=None):
    return ToolResult(content="x", risk=RiskLevel.LOW, source="web_search", metadata=metadata or {})


def test_provider_reads_successful_provider_key():
    assert _tool_provider(_result({"successful_provider": "bing"})) == "bing"


def test_provider_prefers_generic_provider_key():
    assert _tool_provider(_result({"provider": "serper", "successful_provider": "bing"})) == "serper"


def test_provider_none_when_no_metadata():
    assert _tool_provider(_result()) is None
    assert _tool_provider(_result({})) is None


def test_provider_none_when_no_result():
    assert _tool_provider(None) is None
