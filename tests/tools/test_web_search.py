"""Tests for the web search tool."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, patch
from tools.web_search import (
    web_search,
    _format_results,
    _searxng_instance_list,
    _search_searxng,
    _search_searxng_single,
    _search_bing,
    _decode_bing_url,
    DEFAULT_SEARXNG_FALLBACKS,
    MAX_SEARXNG_ATTEMPTS,
)


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
    # The winning provider is named in the content (model + user can see it).
    assert "DuckDuckGo" in result.content


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
        "tools.web_search._search_bing",
        new_callable=AsyncMock,
        return_value=([], "network", "bing failed (mocked)"),
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
        "tools.web_search._search_bing",
        new_callable=AsyncMock,
        return_value=([], "network", "bing failed (mocked)"),
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


# ── Session 268: SearXNG fallback chain + challenge detection ────────────────

def test_searxng_instance_list_expands_and_dedupes():
    """The configured URL (comma-separated supported) is tried first, then the
    curated public fallbacks — deduped, configured wins ordering."""
    urls = _searxng_instance_list(" https://my.instance.org , https://searx.be ")
    assert urls[:2] == ["https://my.instance.org", "https://searx.be"]
    # Curated fallbacks follow, without duplicating configured entries.
    for fb in DEFAULT_SEARXNG_FALLBACKS:
        assert fb in urls
    assert len(urls) == len(set(urls))


def test_searxng_instance_list_default_fallbacks_only():
    urls = _searxng_instance_list(None)
    assert urls == DEFAULT_SEARXNG_FALLBACKS


def test_searxng_instance_list_strips_trailing_slashes():
    urls = _searxng_instance_list("https://my.instance.org/")
    assert urls[0] == "https://my.instance.org"


@pytest.mark.asyncio
async def test_search_searxng_walks_fallback_chain():
    """A challenge/rate-limited/dead instance must not kill the tier — the
    chain moves to the next instance until one returns JSON results."""
    chain = [
        ("https://a.example", [], "challenge", "anti-bot page"),
        ("https://b.example", [], "rate_limit", "HTTP 429"),
        (
            "https://c.example",
            [{"title": "Hit", "href": "https://hit.example", "body": "body"}],
            "",
            "",
        ),
    ]
    async def _fake_single(query: str, url: str):
        for cand_url, res, err_type, err_msg in chain:
            if url == cand_url:
                return res, err_type, err_msg
        return [], "network", "unexpected url"

    with patch(
        "tools.web_search._search_searxng_single", new=_fake_single
    ), patch(
        "tools.web_search._searxng_instance_list",
        return_value=[u for u, *_ in chain],
    ):
        results, err_type, err_msg = await _search_searxng("query", "https://a.example")

    assert err_type == ""
    assert len(results) == 1
    assert results[0]["title"] == "Hit"


@pytest.mark.asyncio
async def test_search_searxng_all_instances_fail_reports_chain():
    """When every instance fails, the error aggregates per-instance reasons
    instead of leaking a raw JSONDecodeError."""
    async def _fake_single(query: str, url: str):
        return [], "challenge", f"anti-bot page at {url}"

    with patch("tools.web_search._search_searxng_single", new=_fake_single):
        results, err_type, err_msg = await _search_searxng("query", "https://a.example")

    assert results == []
    assert err_type == "network"
    assert "a.example" in err_msg
    assert "JSONDecodeError" not in err_msg
    assert "Expecting value" not in err_msg


@pytest.mark.asyncio
async def test_search_searxng_respects_attempt_cap():
    """The chain is capped at MAX_SEARXNG_ATTEMPTS so a long list of dead
    instances never produces an unbounded latency."""
    seen: list[str] = []

    async def _fake_single(query: str, url: str):
        seen.append(url)
        return [], "network", f"dead: {url}"

    urls = [f"https://inst-{i}.example" for i in range(10)]
    with patch("tools.web_search._search_searxng_single", new=_fake_single):
        await _search_searxng("query", ",".join(urls))

    assert len(seen) == min(MAX_SEARXNG_ATTEMPTS, len(urls))
    assert seen == urls[:MAX_SEARXNG_ATTEMPTS]


# ── Session 268 follow-up: Bing scraped tier ────────────────────────────────

_BING_RESULT_HTML = """
<ol id="b_results">
  <li class="b_algo" data-id iid=SERP.5001>
    <h2><a target="_blank" href="https://www.bing.com/ck/a?!&amp;&amp;p=abc&amp;u=a1aHR0cHM6Ly93d3cucHl0aG9uLm9yZy8=" h="ID=SERP,5001.1">Welcome to Python.org</a></h2>
    <div class="b_caption"><p>Experienced programmers can pick up Python very quickly.</p></div>
  </li>
  <li class="b_algo" data-id iid=SERP.5002>
    <h2><a target="_blank" href="https://www.python.org/downloads/">Download Python</a></h2>
    <div class="b_caption"><p>Download the latest version of Python.</p></div>
  </li>
</ol>
"""


def test_decode_bing_url_decodes_redirect():
    """Bing wraps organic results in /ck/a redirect URLs with the real URL
    base64url-encoded in the `u` param (prefixed a1) — HTML-escaped on the way
    in. The decoder must unescape and decode to the real destination."""
    href = "https://www.bing.com/ck/a?!&amp;&amp;p=abc&amp;u=a1aHR0cHM6Ly93d3cucHl0aG9uLm9yZy8="
    assert _decode_bing_url(href) == "https://www.python.org/"


def test_decode_bing_url_falls_back_to_raw_href():
    # Direct URLs (no /ck/a wrapper) and malformed payloads pass through.
    assert _decode_bing_url("https://www.python.org/downloads/") == "https://www.python.org/downloads/"
    assert _decode_bing_url("https://x.com/a?u=a1!!!not-base64") == "https://x.com/a?u=a1!!!not-base64"


class _BingFakeResponse:
    def __init__(self, body: str, content_type: str = "text/html; charset=utf-8", status: int = 200):
        self._body = body
        self.headers = {"content-type": content_type}
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=None, response=self
            )

    @property
    def text(self):
        return self._body


class _BingFakeClient:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, *args, **kwargs):
        return self._response


@pytest.mark.asyncio
async def test_search_bing_parses_organic_results_and_decodes_urls():
    with patch("httpx.AsyncClient", lambda *a, **k: _BingFakeClient(_BingFakeResponse(_BING_RESULT_HTML))):
        results, err_type, err_msg = await _search_bing("python")

    assert err_type == ""
    assert len(results) == 2
    assert results[0]["title"] == "Welcome to Python.org"
    # The /ck/a redirect is decoded back to the real destination.
    assert results[0]["href"] == "https://www.python.org/"
    assert "Python very quickly" in results[0]["body"]
    # Direct hrefs pass through untouched.
    assert results[1]["href"] == "https://www.python.org/downloads/"


@pytest.mark.asyncio
async def test_search_bing_detects_captcha_page():
    captcha = "<html><body>Please verify you are a human ... captcha</body></html>"
    with patch("httpx.AsyncClient", lambda *a, **k: _BingFakeClient(_BingFakeResponse(captcha))):
        results, err_type, err_msg = await _search_bing("python")

    assert results == []
    assert err_type == "challenge"
    assert "captcha" in err_msg.lower()


@pytest.mark.asyncio
async def test_search_bing_detects_non_html_block_page():
    with patch(
        "httpx.AsyncClient",
        lambda *a, **k: _BingFakeClient(_BingFakeResponse("denied", content_type="text/plain")),
    ):
        results, err_type, err_msg = await _search_bing("python")

    assert results == []
    assert err_type == "challenge"


@pytest.mark.asyncio
async def test_web_search_race_bing_wins():
    """Bing is a racing tier — when it returns first with results it wins."""
    mock_results = [{"title": "Bing Hit", "href": "https://bing.example", "body": "body"}]
    with patch(
        "tools.web_search._search_ddg",
        new_callable=AsyncMock,
        return_value=([], "network", "ddg empty (mocked)"),
    ), patch(
        "tools.web_search._search_bing",
        new_callable=AsyncMock,
        return_value=(mock_results, "", ""),
    ), patch(
        "tools.web_search._search_searxng",
        new_callable=AsyncMock,
        return_value=([], "network", "searxng empty (mocked)"),
    ):
        result = await web_search("test")

    assert result.success is True
    assert result.metadata["successful_provider"] == "bing"
    assert "Bing Hit" in result.content
    # The winning provider is named in the content.
    assert "Search results via **Bing**" in result.content


@pytest.mark.asyncio
async def test_search_searxng_single_detects_challenge_page():
    """The root bug: searx.be answers HTTP 200 + HTML (Anubis anti-bot). The
    single-instance call must detect the non-JSON Content-Type and report it
    as a challenge — not raise JSONDecodeError."""
    class _FakeResponse:
        status_code = 200
        headers = {"content-type": "text/html; charset=utf-8"}

        def raise_for_status(self):
            return None

        def json(self):
            raise ValueError("not JSON")

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, *args, **kwargs):
            return _FakeResponse()

    with patch("httpx.AsyncClient", _FakeClient):
        results, err_type, err_msg = await _search_searxng_single(
            "query", "https://searx.be"
        )

    assert results == []
    assert err_type == "challenge"
    assert "anti-bot" in err_msg
    assert "JSONDecodeError" not in err_msg
