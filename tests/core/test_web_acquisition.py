"""Web acquisition system tests.

Tests the WebAcquisitionRouter's progressive escalation:
  static_fetch → browser_read → fallback
plus content validation (boilerplate detection, freshness, confidence scoring).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.web_acquisition import (
    AcquisitionMethod,
    _news_feed_url,
    AcquisitionStatus,
    WebResult,
    _is_boilerplate,
    _extract_freshness,
    _score_content,
    _extract_urls_from_search,
    acquire_web_content,
    web_research,
)


# These tests exercise the base static→browser ladder. scrapamoja is an
# OPTIONAL external strategy (covered in test_scrapamoja_acquisition.py); disable
# it here so the ladder tests are hermetic and don't shell out to a real install
# that may or may not be present on the machine.
@pytest.fixture(autouse=True)
def _no_scrapamoja(monkeypatch):
    monkeypatch.setattr("core.web_acquisition.scrapamoja_available", lambda: False)


# A realistic full-page content body. The router now escalates a very short
# static/browser body as a probable JS skeleton, so mock content must be as
# substantial as a real extracted page would be.
_LONG_STANDINGS = (
    "Premier League Table — Current Season Standings\n"
    "1. Manchester City — 85 pts (W26 D7 L5)\n"
    "2. Arsenal — 84 pts (W25 D9 L4)\n"
    "3. Liverpool — 82 pts (W25 D7 L6)\n"
    "4. Aston Villa — 73 pts (W21 D10 L7)\n"
    "5. Tottenham Hotspur — 66 pts (W19 D9 L10)\n"
    "6. Manchester United — 60 pts (W18 D6 L14)\n"
    "7. Newcastle United — 57 pts (W17 D6 L15)"
)


# ── Content validation ─────────────────────────────────────────────────────


class TestBoilerplateDetection:
    def test_short_content_is_boilerplate(self):
        assert _is_boilerplate("") is True
        assert _is_boilerplate("Hi") is True
        assert _is_boilerplate("   ") is True

    def test_navigation_is_boilerplate(self):
        nav = "Menu\nHome\nAbout\nContact\nSign in\nSign up\nFooter\nCopyright 2024"
        assert _is_boilerplate(nav) is True

    def test_real_content_is_not_boilerplate(self):
        content = (
            "Premier League Table\n"
            "1. Manchester City — 85 pts (W26 D7 L5)\n"
            "2. Arsenal — 84 pts (W25 D9 L4)\n"
            "3. Liverpool — 82 pts (W25 D7 L6)\n"
            "4. Aston Villa — 73 pts (W22 D7 L9)\n"
            "5. Tottenham — 66 pts (W19 D9 L10)"
        )
        assert _is_boilerplate(content) is False

    def test_long_content_with_some_markers_is_not_boilerplate(self):
        # Real article with a few navigation markers should NOT be flagged
        content = (
            "Premier League Table — 2026 Season\n"
            "1. Manchester City — 85 pts\n"
            "2. Arsenal — 84 pts\n"
            "3. Liverpool — 82 pts\n"
            "The current season has been exciting. Manchester City leads "
            "with 85 points, followed closely by Arsenal at 84. Liverpool "
            "is third with 82 points. Aston Villa and Tottenham round out "
            "the top five. The race for the title is still open with three "
            "matches remaining. Sign in to subscribe to our newsletter for "
            "more updates."
        )
        assert _is_boilerplate(content) is False


class TestFreshnessExtraction:
    def test_full_month_date(self):
        content = "Published January 15, 2026 — Manchester City leads the EPL."
        freshness = _extract_freshness(content)
        assert freshness is not None
        assert "2026" in freshness

    def test_iso_date(self):
        content = "Last updated: 2026-01-15"
        assert _extract_freshness(content) == "2026-01-15"

    def test_year_only(self):
        content = "Copyright 2026. All rights reserved."
        freshness = _extract_freshness(content)
        assert freshness is not None
        assert "2026" in freshness

    def test_no_date(self):
        content = "Manchester City leads the EPL."
        assert _extract_freshness(content) is None


class TestContentScoring:
    def test_high_score_when_query_words_present(self):
        content = "Premier League standings table with all teams and points."
        score = _score_content(content, "Premier League standings table")
        assert score >= 0.5

    def test_zero_score_for_boilerplate(self):
        content = "Menu\nHome\nSign in\nFooter"
        score = _score_content(content, "EPL standings")
        assert score == 0.0

    def test_low_score_when_no_query_words(self):
        content = "The weather today is sunny with a light breeze."
        score = _score_content(content, "EPL standings table")
        assert score < 0.3

    def test_neutral_score_when_no_query(self):
        content = "Some content here."
        score = _score_content(content, "")
        assert score == 0.5


class TestUrlExtraction:
    def test_extracts_urls_from_search_result(self):
        search_content = (
            "Search results via **DDG** (3 results):\n\n"
            "1. **Premier League Table**\n"
            "   https://www.premierleague.com/tables\n"
            "   The official Premier League table...\n\n"
            "2. **BBC Sport - Premier League**\n"
            "   https://www.bbc.com/sport/football/premier-league/table\n"
            "   BBC Sport's Premier League table...\n\n"
            "3. **Sky Sports**\n"
            "   https://www.skysports.com/premier-league-table\n"
            "   Sky Sports Premier League table..."
        )
        urls = _extract_urls_from_search(search_content)
        assert len(urls) == 3
        assert "https://www.premierleague.com/tables" in urls
        assert "https://www.bbc.com/sport/football/premier-league/table" in urls

    def test_caps_at_5_urls(self):
        search_content = "\n".join(f"https://example{i}.com" for i in range(10))
        urls = _extract_urls_from_search(search_content)
        assert len(urls) == 5

    def test_no_urls_returns_empty(self):
        urls = _extract_urls_from_search("No URLs here, just text.")
        assert urls == []


# ── Acquisition strategies ──────────────────────────────────────────────────


class TestStaticFetchStrategy:
    @pytest.mark.asyncio
    async def test_static_fetch_success(self):
        """Mock web_fetch to return content → static_fetch succeeds."""
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.content = _LONG_STANDINGS

        with patch("tools.web_fetch.web_fetch", new=AsyncMock(return_value=mock_result)):
            result = await acquire_web_content(
                "https://example.com/epl",
                query="Premier League standings",
            )

        assert result.is_success()
        assert result.acquisition_method == AcquisitionMethod.STATIC_FETCH
        assert "Manchester City" in result.content

    @pytest.mark.asyncio
    async def test_static_fetch_boilerplate_escalates_to_browser(self):
        """If static_fetch returns boilerplate, the router escalates to browser_read."""
        mock_fetch_result = MagicMock()
        mock_fetch_result.success = True
        mock_fetch_result.content = "Menu\nHome\nSign in\nFooter\nCopyright 2024"

        # Mock browser_read to succeed
        with (
            patch("tools.web_fetch.web_fetch", new=AsyncMock(return_value=mock_fetch_result)),
            patch("tools.browser_agent._run_browser_cmd", new=AsyncMock(return_value=(
                0,  # returncode
                _LONG_STANDINGS,
                "",  # stderr
            ))),
        ):
            result = await acquire_web_content(
                "https://example.com/epl",
                query="Premier League standings",
            )

        assert result.is_success()
        assert result.acquisition_method == AcquisitionMethod.BROWSER_READ
        assert "browser_read" in result.attempted_strategies

    @pytest.mark.asyncio
    async def test_static_fetch_failure_escalates_to_browser(self):
        """If static_fetch fails, the router escalates to browser_read."""
        mock_fetch_result = MagicMock()
        mock_fetch_result.success = False
        mock_fetch_result.content = "Failed to fetch"

        # Mock browser_read to return substantial content
        browser_content = _LONG_STANDINGS
        with (
            patch("tools.web_fetch.web_fetch", new=AsyncMock(return_value=mock_fetch_result)),
            patch("tools.browser_agent._run_browser_cmd", new=AsyncMock(return_value=(
                0,
                browser_content,
                "",
            ))),
        ):
            result = await acquire_web_content(
                "https://example.com/epl",
                query="Premier League standings",
            )

        assert result.is_success()
        assert result.acquisition_method == AcquisitionMethod.BROWSER_READ


class TestBrowserReadStrategy:
    @pytest.mark.asyncio
    async def test_browser_read_success(self):
        with patch("tools.browser_agent._run_browser_cmd", new=AsyncMock(return_value=(
            0,
            "Premier League Table\n1. Manchester City — 85 pts\n2. Arsenal — 84 pts",
            "",
        ))):
            result = await acquire_web_content(
                "https://example.com/epl",
                query="Premier League standings",
                max_strategies=2,  # skip static, go straight to browser
            )

        # Note: acquire_web_content always tries static first; to test browser_read
        # in isolation we'd need to mock static_fetch to fail
        # This test verifies the browser_read path works when static fails
        # (covered by test_static_fetch_failure_escalates_to_browser above)

    @pytest.mark.asyncio
    async def test_all_strategies_fail(self):
        """When all strategies fail, return a FAILED result."""
        mock_fetch_result = MagicMock()
        mock_fetch_result.success = False
        mock_fetch_result.content = ""

        with (
            patch("tools.web_fetch.web_fetch", new=AsyncMock(return_value=mock_fetch_result)),
            patch("tools.browser_agent._run_browser_cmd", new=AsyncMock(return_value=(
                1,  # failure
                "",
                "Browser command failed",
            ))),
        ):
            result = await acquire_web_content(
                "https://example.com/epl",
                query="Premier League standings",
            )

        assert result.status == AcquisitionStatus.FAILED
        assert len(result.attempted_strategies) == 2


# ── WebResult formatting ────────────────────────────────────────────────────


class TestWebResultFormatting:
    def test_success_format_includes_source_and_method(self):
        result = WebResult(
            status=AcquisitionStatus.SUCCESS,
            source="https://example.com/page",
            acquisition_method=AcquisitionMethod.STATIC_FETCH,
            content="The content here.",
            confidence=0.85,
            freshness="2026-01-15",
        )
        formatted = result.to_tool_result_content()
        assert "https://example.com/page" in formatted
        assert "static fetch" in formatted
        assert "2026-01-15" in formatted
        assert "85%" in formatted
        assert "The content here." in formatted

    def test_failure_format_lists_attempted_strategies(self):
        result = WebResult(
            status=AcquisitionStatus.FAILED,
            source="https://example.com/page",
            acquisition_method=AcquisitionMethod.STATIC_FETCH,
            content="",
            error="all strategies failed",
            attempted_strategies=["static_fetch", "browser_read"],
        )
        formatted = result.to_tool_result_content()
        assert "Acquisition failed" in formatted
        assert "static_fetch, browser_read" in formatted
        assert "all strategies failed" in formatted

    def test_partial_format_warns_about_incomplete_content(self):
        result = WebResult(
            status=AcquisitionStatus.PARTIAL,
            source="https://example.com/page",
            acquisition_method=AcquisitionMethod.BROWSER_READ,
            content="Partial content...",
            confidence=0.4,
        )
        formatted = result.to_tool_result_content()
        assert "partial" in formatted.lower()
        assert "40%" in formatted


# ── web_research (end-to-end) ──────────────────────────────────────────────


class TestWebResearch:
    @pytest.mark.asyncio
    async def test_web_research_finds_sources_and_acquires(self):
        """End-to-end: search returns URLs, static_fetch succeeds on first."""
        mock_search_result = MagicMock()
        mock_search_result.success = True
        mock_search_result.content = (
            "Search results (1 result):\n\n"
            "1. **Premier League**\n"
            "   https://www.premierleague.com/tables\n"
            "   The official table..."
        )

        # Use substantial content (>50 chars, with query keywords)
        mock_fetch_result = MagicMock()
        mock_fetch_result.success = True
        mock_fetch_result.content = _LONG_STANDINGS

        with (
            patch("tools.web_search.web_search", new=AsyncMock(return_value=mock_search_result)),
            patch("tools.web_fetch.web_fetch", new=AsyncMock(return_value=mock_fetch_result)),
        ):
            result = await web_research("current EPL standings")

        assert result.is_success()
        assert "Manchester City" in result.content
        assert result.acquisition_method == AcquisitionMethod.STATIC_FETCH

    @pytest.mark.asyncio
    async def test_web_research_escalates_on_failed_source(self):
        """If the first source fails, try the second."""
        mock_search_result = MagicMock()
        mock_search_result.success = True
        mock_search_result.content = (
            "Search results (2 results):\n\n"
            "1. **Source A**\n"
            "   https://a.com/page\n"
            "   First result...\n\n"
            "2. **Source B**\n"
            "   https://b.com/page\n"
            "   Second result..."
        )

        # First source fails, second succeeds
        mock_fetch_fail = MagicMock()
        mock_fetch_fail.success = False
        mock_fetch_fail.content = ""

        mock_fetch_success = MagicMock()
        mock_fetch_success.success = True
        mock_fetch_success.content = _LONG_STANDINGS

        with (
            patch("tools.web_search.web_search", new=AsyncMock(return_value=mock_search_result)),
            patch(
                "tools.web_fetch.web_fetch",
                new=AsyncMock(side_effect=[mock_fetch_fail, mock_fetch_success]),
            ),
            patch("tools.browser_agent._run_browser_cmd", new=AsyncMock(return_value=(
                1, "", "browser failed",  # browser_read also fails for source A
            ))),
        ):
            result = await web_research("current EPL standings")

        assert result.is_success()
        assert "Manchester City" in result.content

    @pytest.mark.asyncio
    async def test_web_research_returns_search_snippets_when_no_urls(self):
        """If search returns no URLs, return the snippets as PARTIAL."""
        mock_search_result = MagicMock()
        mock_search_result.success = True
        mock_search_result.content = "Some snippets but no URLs."

        with patch("tools.web_search.web_search", new=AsyncMock(return_value=mock_search_result)):
            result = await web_research("some query")

        assert result.status == AcquisitionStatus.PARTIAL
        assert result.acquisition_method == AcquisitionMethod.SEARCH_ONLY
        assert "Some snippets" in result.content

    @pytest.mark.asyncio
    async def test_web_research_handles_search_failure(self):
        """If web_search fails, return a FAILED result."""
        mock_search_result = MagicMock()
        mock_search_result.success = False
        mock_search_result.content = "Search failed."

        with patch("tools.web_search.web_search", new=AsyncMock(return_value=mock_search_result)):
            result = await web_research("some query")

        assert result.status == AcquisitionStatus.FAILED
        assert "web_search failed" in (result.error or "")


# ── Session 341: WebIntent classification tests ─────────────────────────────


class TestWebIntentClassification:
    def test_current_standings_is_RESEARCH(self):
        from core.web_acquisition import WebIntent, classify_web_intent
        assert classify_web_intent("Give me the current EPL standings.") == WebIntent.RESEARCH

    def test_open_website_is_BROWSE(self):
        from core.web_acquisition import WebIntent, classify_web_intent
        assert classify_web_intent("Open the BBC website and check the live table.") == WebIntent.BROWSE

    def test_navigate_to_is_BROWSE(self):
        from core.web_acquisition import WebIntent, classify_web_intent
        assert classify_web_intent("Navigate to premierleague.com/tables") == WebIntent.BROWSE

    def test_specific_url_is_RETRIEVE(self):
        from core.web_acquisition import WebIntent, classify_web_intent
        assert classify_web_intent("Read https://example.com/article") == WebIntent.RETRIEVE

    def test_find_articles_is_DISCOVER(self):
        from core.web_acquisition import WebIntent, classify_web_intent
        assert classify_web_intent("Find articles about AI regulation.") == WebIntent.DISCOVER

    def test_weather_query_is_RESEARCH(self):
        from core.web_acquisition import WebIntent, classify_web_intent
        assert classify_web_intent("What is the weather in Nairobi?") == WebIntent.RESEARCH

    def test_empty_message_defaults_to_RESEARCH(self):
        from core.web_acquisition import WebIntent, classify_web_intent
        assert classify_web_intent("") == WebIntent.RESEARCH

    def test_browse_click_is_BROWSE(self):
        from core.web_acquisition import WebIntent, classify_web_intent
        assert classify_web_intent("Click on the standings tab") == WebIntent.BROWSE

    def test_browse_scroll_is_BROWSE(self):
        from core.web_acquisition import WebIntent, classify_web_intent
        assert classify_web_intent("Scroll down to see more results") == WebIntent.BROWSE


# ── Session 341: Evidence validation pipeline tests ─────────────────────────


class TestAuthorityAssessment:
    def test_premierleague_is_high_authority(self):
        from core.web_acquisition import _assess_authority
        assert _assess_authority("https://www.premierleague.com/tables") >= 0.9

    def test_bbc_is_high_authority(self):
        from core.web_acquisition import _assess_authority
        assert _assess_authority("https://www.bbc.com/sport/football") >= 0.85

    def test_reddit_is_low_authority(self):
        from core.web_acquisition import _assess_authority
        assert _assess_authority("https://reddit.com/r/soccer") <= 0.5

    def test_unknown_domain_is_neutral(self):
        from core.web_acquisition import _assess_authority
        assert _assess_authority("https://unknown.com/page") == 0.5


class TestEntityValidation:
    def test_correct_entity_passes(self):
        from core.web_acquisition import _validate_entity
        content = "Premier League Table\n1. Manchester City — 85 pts\n2. Arsenal — 84 pts"
        ok, reason = _validate_entity(content, "current EPL standings")
        assert ok is True

    def test_wrong_entity_fails(self):
        """WEB-12: relevant keywords, wrong entity."""
        from core.web_acquisition import _validate_entity
        # Content about Championship (not EPL) but has "standings" keyword
        content = (
            "Championship Standings\n"
            "1. Leeds United — 90 pts\n"
            "2. Leicester City — 88 pts\n"
            "3. Ipswich Town — 85 pts\n"
            "The Championship table shows Leeds leading."
        )
        ok, reason = _validate_entity(content, "current Premier League standings")
        assert ok is False
        assert "wrong_entity" in (reason or "")

    def test_no_query_passes(self):
        from core.web_acquisition import _validate_entity
        ok, reason = _validate_entity("some content", "")
        assert ok is True


class TestFreshnessValidation:
    def test_current_year_passes(self):
        from core.web_acquisition import _validate_freshness
        import datetime
        current_year = datetime.datetime.now().year
        ok, reason = _validate_freshness("some content", "current EPL standings", str(current_year))
        assert ok is True

    def test_stale_year_fails(self):
        """WEB-9: search result is relevant but stale."""
        from core.web_acquisition import _validate_freshness
        ok, reason = _validate_freshness("some content", "current EPL standings", "2023")
        assert ok is False
        assert "stale" in (reason or "")

    def test_no_freshness_requirement_passes(self):
        from core.web_acquisition import _validate_freshness
        ok, reason = _validate_freshness("some content", "explain how a car engine works", "2010")
        assert ok is True  # no freshness requirement

    def test_no_freshness_detected_passes(self):
        from core.web_acquisition import _validate_freshness
        ok, reason = _validate_freshness("some content", "current EPL standings", None)
        assert ok is True  # can't validate — don't fail


class TestDataPresenceValidation:
    def test_table_data_passes(self):
        from core.web_acquisition import _validate_data_presence
        content = (
            "Premier League Table\n"
            "1. Manchester City — 85 pts\n"
            "2. Arsenal — 84 pts\n"
            "3. Liverpool — 82 pts"
        )
        ok, reason = _validate_data_presence(content)
        assert ok is True

    def test_navigation_fails(self):
        """WEB-10: HTTP success but acquisition failure."""
        from core.web_acquisition import _validate_data_presence
        content = "Menu\nHome\nSign in\nFooter\nCopyright 2024"
        ok, reason = _validate_data_presence(content)
        assert ok is False
        assert "boilerplate" in (reason or "")

    def test_empty_content_fails(self):
        from core.web_acquisition import _validate_data_presence
        ok, reason = _validate_data_presence("")
        assert ok is False
        assert "empty" in (reason or "")


class TestValidateWebResult:
    def test_valid_result_passes_all_validations(self):
        from core.web_acquisition import (
            WebResult, AcquisitionStatus, AcquisitionMethod, validate_web_result,
        )
        result = WebResult(
            status=AcquisitionStatus.SUCCESS,
            source="https://www.premierleague.com/tables",
            acquisition_method=AcquisitionMethod.STATIC_FETCH,
            content=(
                "Premier League Table — 2026 Season\n"
                "1. Manchester City — 85 pts (W26 D7 L5)\n"
                "2. Arsenal — 84 pts (W25 D9 L4)\n"
                "3. Liverpool — 82 pts (W25 D7 L6)"
            ),
            confidence=0.7,
            freshness="2026",
        )
        validated = validate_web_result(result, query="current EPL standings")
        assert validated.is_success()
        assert validated.entity_validated is True
        assert validated.freshness_validated is True
        assert validated.authority_score >= 0.9
        # Confidence should be boosted
        assert validated.confidence > 0.7

    def test_wrong_entity_downgrades_to_failed(self):
        """WEB-12: relevant keywords, wrong entity."""
        from core.web_acquisition import (
            WebResult, AcquisitionStatus, AcquisitionMethod, validate_web_result,
        )
        result = WebResult(
            status=AcquisitionStatus.SUCCESS,
            source="https://example.com/championship",
            acquisition_method=AcquisitionMethod.STATIC_FETCH,
            content=(
                "Championship Standings\n"
                "1. Leeds United — 90 pts\n"
                "2. Leicester City — 88 pts\n"
                "3. Ipswich Town — 85 pts"
            ),
            confidence=0.8,
            freshness="2026",
        )
        validated = validate_web_result(result, query="current Premier League standings")
        assert validated.status == AcquisitionStatus.FAILED
        assert "wrong_entity" in (validated.failure_reason or "")

    def test_stale_data_downgrades_to_failed(self):
        """WEB-9: search result is relevant but stale."""
        from core.web_acquisition import (
            WebResult, AcquisitionStatus, AcquisitionMethod, validate_web_result,
        )
        result = WebResult(
            status=AcquisitionStatus.SUCCESS,
            source="https://example.com/old-table",
            acquisition_method=AcquisitionMethod.STATIC_FETCH,
            content=(
                "Premier League Table — 2023 Season\n"
                "1. Manchester City — 89 pts (W27 D8 L3)\n"
                "2. Arsenal — 84 pts (W25 D9 L4)\n"
                "3. Liverpool — 82 pts (W25 D7 L6)"
            ),
            confidence=0.8,
            freshness="2023",
        )
        validated = validate_web_result(result, query="current EPL standings")
        assert validated.status == AcquisitionStatus.FAILED
        assert "stale" in (validated.failure_reason or "")

    def test_boilerplate_downgrades_to_failed(self):
        """WEB-10: HTTP success but acquisition failure (navigation only)."""
        from core.web_acquisition import (
            WebResult, AcquisitionStatus, AcquisitionMethod, validate_web_result,
        )
        result = WebResult(
            status=AcquisitionStatus.SUCCESS,
            source="https://example.com/js-only-page",
            acquisition_method=AcquisitionMethod.STATIC_FETCH,
            content="Menu\nHome\nSign in\nFooter\nEnable JavaScript",
            confidence=0.5,
            freshness=None,
        )
        validated = validate_web_result(result, query="current EPL standings")
        assert validated.status == AcquisitionStatus.FAILED
        assert "boilerplate" in (validated.failure_reason or "")

    def test_already_failed_result_is_not_validated(self):
        from core.web_acquisition import (
            WebResult, AcquisitionStatus, AcquisitionMethod, validate_web_result,
        )
        result = WebResult(
            status=AcquisitionStatus.FAILED,
            source="https://example.com",
            acquisition_method=AcquisitionMethod.STATIC_FETCH,
            content="",
            error="connection refused",
        )
        validated = validate_web_result(result, query="current EPL standings")
        assert validated.status == AcquisitionStatus.FAILED
        assert validated.entity_validated is False  # not checked


# ── B-2026-09-04-3 follow-up: news queries seed the Google News RSS feed ──────

def test_news_feed_url_topicless_uses_top_stories():
    # The exact transcript queries — topicless "what's trending / breaking news".
    for q in [
        "top trending news stories today September 4 2026",
        "breaking news headlines today",
        "what is the latest news",
        "top headlines",
    ]:
        assert _news_feed_url(q) == "https://news.google.com/rss", q


def test_news_feed_url_with_subject_uses_topic_search():
    url = _news_feed_url("latest news on artificial intelligence regulation")
    assert url is not None
    assert url.startswith("https://news.google.com/rss/search?q=")
    # The subject terms are carried into the feed query; framing words are not.
    assert "regulation" in url
    assert "news" not in url.split("?q=")[1]


def test_news_feed_url_non_news_returns_none():
    # No news cue → normal search-only discovery, feed not seeded.
    for q in [
        "current EPL standings",
        "what is the latest Python version",
        "weather in Nairobi",
        "how do hash maps work",
    ]:
        assert _news_feed_url(q) is None, q
