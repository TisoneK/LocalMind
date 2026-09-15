"""Tests for the web search tool."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from tools.web_search import (
    DEFAULT_SEARXNG_FALLBACKS,
    MAX_SEARXNG_ATTEMPTS,
    _decode_bing_url,
    _format_results,
    _fallback_is_on_topic,
    _is_relevant_enough,
    _query_content_tokens,
    _relevance_coverage,
    _search_bing,
    _search_searxng,
    _search_searxng_single,
    _searxng_instance_list,
    web_search,
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
    # Result covers the query's distinctive terms (test, query) so it clears the
    # relevance gate — a realistic hit, not an off-topic set riding the fallback.
    mock_results = [
        {"title": "Test query result", "href": "https://test.com", "body": "About the test query"},
    ]
    # Mock ALL three providers (Bing too) so the race is deterministic and never
    # hits the real network — DDG is the only provider with results, so it wins
    # regardless of the relevance gate.
    with patch(
        "tools.web_search._search_ddg",
        new_callable=AsyncMock,
        return_value=(mock_results, "", ""),
    ), patch(
        "tools.web_search._search_bing",
        new_callable=AsyncMock,
        return_value=([], "network", "bing empty (mocked)"),
    ), patch(
        "tools.web_search._search_searxng",
        new_callable=AsyncMock,
        return_value=([], "network", "searxng empty (mocked)"),
    ):
        result = await web_search("test query")

    assert result.source == "web_search"
    assert "Test query result" in result.content
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
    urls = _searxng_instance_list(" https://my.instance.org, https://searx.be ")
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
    # Title covers the query term ("test") so the set clears the relevance gate.
    mock_results = [{"title": "Bing test hit", "href": "https://bing.example", "body": "body"}]
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
    assert "Bing test hit" in result.content
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


# ── Relevance gate for the provider race (Kitengela weather regression) ───────
# Root cause fixed here: the race was FIRST_COMPLETED (fastest wins), so a fast
# provider returning off-topic results (Bing latching onto the word "current"
# in "current weather Kitengela" → Current.com / dictionary hits, or returning
# Los-Angeles weather) beat DDG's correct Kitengela results. The gate lets a
# provider win immediately only when it covers the query's distinctive terms.

_BING_CURRENT_JUNK = [
    {"title": "Current | Future of Banking", "body": "banking app"},
    {"title": "Electric current - Wikipedia", "body": "flow of charge"},
    {"title": "current 是什么意思", "body": "dictionary"},
]
_BING_LA_WEATHER = [
    {"title": "10-Day Weather Forecast for Los Angeles", "body": "temperature and forecast"},
    {"title": "Los Angeles, CA - National Weather Service", "body": "weather"},
]
_DDG_KITENGELA = [
    {"title": "Weather today - Kitengela, Kenya", "body": "current temperature forecast"},
    {"title": "7-day weather forecast Kitengela", "body": "Kenya temperature"},
]


def test_query_content_tokens_drops_framing_and_temporal_words():
    toks = _query_content_tokens("current weather Kitengela Kenya right now")
    assert toks == ["weather", "kitengela", "kenya"]  # current/right/now dropped


def test_relevance_coverage_counts_distinct_terms():
    q = "current weather Kitengela Kenya right now"
    assert _relevance_coverage(q, _BING_CURRENT_JUNK) == 0
    assert _relevance_coverage(q, _DDG_KITENGELA) == 3


def test_bing_current_junk_is_not_relevant():
    q = "current weather Kitengela Kenya right now"
    assert _is_relevant_enough(q, _BING_CURRENT_JUNK) is False


def test_ddg_kitengela_is_relevant():
    q = "current weather Kitengela Kenya right now"
    assert _is_relevant_enough(q, _DDG_KITENGELA) is True


def test_wrong_location_weather_is_not_relevant():
    """Generic weather words alone (LA page) must NOT pass — the location
    (kitengela/kenya) is required."""
    q = "weather Kitengela Kenya current temperature forecast"
    assert _is_relevant_enough(q, _BING_LA_WEATHER) is False
    assert _is_relevant_enough(q, _DDG_KITENGELA) is True


def test_no_distinctive_terms_accepts_any_results():
    """A query of only framing/stopwords has nothing to judge on → take anything."""
    assert _is_relevant_enough("what is it right now", _BING_LA_WEATHER) is True


@pytest.mark.asyncio
async def test_race_relevance_beats_a_faster_offtopic_provider():
    """The regression: Bing returns junk FAST, DDG returns the correct results.
    The gate must return DDG (relevance), not Bing (speed)."""
    with patch(
        "tools.web_search._search_bing",
        new_callable=AsyncMock,
        return_value=(_BING_CURRENT_JUNK, "", ""),
    ), patch(
        "tools.web_search._search_ddg",
        new_callable=AsyncMock,
        return_value=(_DDG_KITENGELA, "", ""),
    ), patch(
        "tools.web_search._search_searxng",
        new_callable=AsyncMock,
        return_value=([], "network", "searxng empty (mocked)"),
    ):
        result = await web_search("current weather Kitengela Kenya right now")

    assert result.success is True
    assert "DuckDuckGo" in result.content
    assert "Kitengela" in result.content
    assert "Future of Banking" not in result.content


@pytest.mark.asyncio
async def test_race_discards_off_topic_fallback_below_floor():
    """If NO provider clears the bar AND the best held set is
    below the fallback floor (< half the distinctive terms), it is DISCARDED —
    returning off-topic junk (here: banking/electric-current pages for a weather
    query, coverage 0/3) is worse than no results. The old behavior surfaced it;
    the transcript (OnlyFans for a news query) proved that harmful.

    Brave is disabled so we exercise the pure free-tier path.
    """
    with patch(
        "tools.web_search._search_bing",
        new_callable=AsyncMock,
        return_value=(_BING_CURRENT_JUNK, "", ""),
    ), patch(
        "tools.web_search._search_ddg",
        new_callable=AsyncMock,
        return_value=([], "network", "ddg empty (mocked)"),
    ), patch(
        "tools.web_search._search_searxng",
        new_callable=AsyncMock,
        return_value=([], "network", "searxng empty (mocked)"),
    ), patch(
        "core.config.settings.brave_search_api_key",
        "",
    ):
        result = await web_search("current weather Kitengela Kenya right now")

    # Off-topic junk is NOT surfaced; the tool reports no relevant results so
    # the model can try another source.
    assert result.success is False
    assert "Future of Banking" not in result.content


# ── B-2026-09-04-3: off-topic fallback must be discarded, not surfaced ────────
# When no provider clears the near-full relevance bar, the best-effort held set
# is used ONLY if it still covers >= half the query's distinctive terms. Below
# that it is off-topic garbage — worse than nothing (wastes the turn, can expose
# adult content). Fixtures below are the EXACT failing result sets from the
# 2026-09-04 transcript.

# "top trending news stories today September 4 2026" -> dictionary defs of "top"
_BING_TOP_DICTIONARY = [
    {"title": "TOP | English meaning - Cambridge Dictionary",
     "body": "TOP definition: 1. the highest place or part"},
    {"title": "TOP Definition & Meaning - Merriam-Webster",
     "body": "the highest point, level, or part of something"},
    {"title": "Top - Wikipedia", "body": "Top most commonly refers to"},
    {"title": "top - Wiktionary, the free dictionary",
     "body": "Aug 27, 2026 - top (countable and uncountable, plural tops)"},
]

# "breaking news headlines today" -> OnlyFans blog/status (adult platform)
_BING_ONLYFANS = [
    {"title": "All - OnlyFans Blog", "body": "The official OnlyFans blog."},
    {"title": "Creator Center - OnlyFans Blog", "body": "Explore Creator Center posts"},
    {"title": "OnlyFans Status - Incident History", "body": "No incidents reported"},
]

# An on-topic PARTIAL match (covers >= half) must STILL be usable as a fallback.
_DDG_PARTIAL_NEWS = [
    {"title": "Trending news today - Reuters", "body": "Top stories and breaking news"},
    {"title": "Google News", "body": "Headlines and trending stories worldwide"},
]


def test_top_dictionary_fallback_is_off_topic():
    q = "top trending news stories today September 4 2026"
    # covers at most top/2026 (<= 2 of 6 distinctive terms) — below the half floor
    assert _relevance_coverage(q, _BING_TOP_DICTIONARY) < 3
    assert _fallback_is_on_topic(q, _BING_TOP_DICTIONARY) is False


def test_onlyfans_fallback_is_off_topic():
    q = "breaking news headlines today"
    assert _relevance_coverage(q, _BING_ONLYFANS) == 0
    assert _fallback_is_on_topic(q, _BING_ONLYFANS) is False


def test_on_topic_partial_match_survives_as_fallback():
    q = "breaking news headlines today"  # distinctive: breaking, news, headlines
    # Reuters/Google set covers news + breaking + headlines + trending -> >= half
    assert _fallback_is_on_topic(q, _DDG_PARTIAL_NEWS) is True


def test_no_distinctive_terms_any_set_is_on_topic():
    # A query with only stopwords has nothing to judge on — don't over-reject.
    assert _fallback_is_on_topic("what is it right now", _BING_ONLYFANS) is True


# ── B-2026-09-04-3: Brave is not exempt from the relevance floor ──────────────

@pytest.mark.asyncio
async def test_brave_off_topic_results_are_discarded():
    """When the free tiers fail and Brave returns off-topic junk (OnlyFans for a
    news query), it must be discarded like any other off-topic set — not used
    just because it came from the paid tier."""
    with patch("tools.web_search._search_ddg", new_callable=AsyncMock, return_value=([], "network", "x")), \
         patch("tools.web_search._search_bing", new_callable=AsyncMock, return_value=([], "network", "x")), \
         patch("tools.web_search._search_searxng", new_callable=AsyncMock, return_value=([], "network", "x")), \
         patch("core.config.settings.brave_search_api_key", "test-key"), \
         patch("tools.web_search._search_brave", new_callable=AsyncMock, return_value=(_BING_ONLYFANS, "", "")):
        result = await web_search("breaking news headlines today")

    assert result.success is False
    assert "onlyfans" not in result.content.lower()


@pytest.mark.asyncio
async def test_brave_relevant_results_are_used():
    """A relevant Brave result set (clears the floor) is still used normally."""
    hits = [{"title": "breaking news headlines roundup",
             "href": "https://news.example", "body": "today's top news headlines"}]
    with patch("tools.web_search._search_ddg", new_callable=AsyncMock, return_value=([], "network", "x")), \
         patch("tools.web_search._search_bing", new_callable=AsyncMock, return_value=([], "network", "x")), \
         patch("tools.web_search._search_searxng", new_callable=AsyncMock, return_value=([], "network", "x")), \
         patch("core.config.settings.brave_search_api_key", "test-key"), \
         patch("tools.web_search._search_brave", new_callable=AsyncMock, return_value=(hits, "", "")):
        result = await web_search("breaking news headlines today")

    assert result.success is True
    assert result.metadata["successful_provider"] == "brave"
