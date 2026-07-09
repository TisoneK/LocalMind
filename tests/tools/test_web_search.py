"""Tests for the web search tool."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, patch
from tools.web_search import web_search, _format_results


def test_format_results_basic():
    results = [
        {"title": "Test", "href": "https://example.com", "body": "Some snippet"},
    ]
    formatted = _format_results(results)
    # v8 format: numbered markdown list with bold title, url, snippet
    assert "1." in formatted
    assert "Test" in formatted
    assert "example.com" in formatted
    assert "Some snippet" in formatted


def test_format_results_empty():
    formatted = _format_results([])
    # v8: empty results return a clear "no results" message
    assert "No results" in formatted or "no results" in formatted


@pytest.mark.asyncio
async def test_web_search_returns_tool_result_on_success():
    """web_search() returns a ToolResult with source='web_search' on success.

    The v8 racing architecture fires DDG and SearXNG in parallel. We mock
    _search_ddg to return results and _search_searxng to return empty so
    DDG wins the race deterministically.
    """
    mock_results = [
        {"title": "Result", "href": "https://test.com", "body": "Body text"},
    ]
    with patch(
        "tools.web_search._search_ddg",
        new_callable=AsyncMock,
        return_value=(mock_results, "", ""),
    ), patch(
        "tools.web_search._search_searxng",
        new_callable=AsyncMock,
        return_value=([], "network", "searxng empty (mocked)"),
    ):
        result = await web_search("test query")

    assert result.source == "web_search"
    assert "Result" in result.content
    assert result.risk.value == "low"
    assert result.success is True


@pytest.mark.asyncio
async def test_web_search_all_providers_fail_returns_graceful_error():
    """When all search providers fail, web_search() returns a ToolResult
    with success=False and an error message — never raises.

    Replaces the old test_run_no_query_returns_error which tested dict-input
    validation that no longer exists (web_search now takes a str query).
    """
    with patch(
        "tools.web_search._search_ddg",
        new_callable=AsyncMock,
        return_value=([], "network", "ddg failed (mocked)"),
    ), patch(
        "tools.web_search._search_searxng",
        new_callable=AsyncMock,
        return_value=([], "network", "searxng failed (mocked)"),
    ), patch(
        "core.config.settings.brave_search_api_key",
        "",
    ):
        result = await web_search("test")

    assert result.source == "web_search"
    assert result.success is False
    assert "failed" in result.content.lower() or "no results" in result.content.lower()


@pytest.mark.asyncio
async def test_web_search_exception_returns_graceful_error():
    """Exceptions inside a search provider are caught by the race loop
    (see lines 291-293) and treated as empty results — never propagated."""
    with patch(
        "tools.web_search._search_ddg",
        side_effect=Exception("network error"),
    ), patch(
        "tools.web_search._search_searxng",
        new_callable=AsyncMock,
        return_value=([], "network", "searxng failed (mocked)"),
    ), patch(
        "core.config.settings.brave_search_api_key",
        "",
    ):
        result = await web_search("test")

    assert result.source == "web_search"
    assert result.success is False
