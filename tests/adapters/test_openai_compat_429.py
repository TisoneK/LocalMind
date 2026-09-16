"""Regression tests for the 429 permanent-vs-transient classifier.

A permanent quota / billing 429 (daily or free-tier limit, out of credits)
must NOT be retried — retrying only burns the backoff window and, across an
agent loop, tens of seconds, before surfacing an error the user could have
seen in the first round-trip. A transient per-minute burst 429 should still
retry.
"""

from adapters.openai_compat import OpenAICompatAdapter as A


class TestPermanent429Classifier:
    def test_insufficient_quota_is_permanent(self):
        assert A._is_permanent_429('{"error":{"code":"insufficient_quota"}}', None) is True

    def test_free_daily_limit_is_permanent(self):
        assert A._is_permanent_429("You have exceeded your current free daily quota", None) is True

    def test_billing_credits_is_permanent(self):
        assert A._is_permanent_429("Out of credits. Please add credits to continue.", None) is True

    def test_quota_wins_over_rate_limit_phrasing(self):
        # A body that says both "rate limit" and "daily quota" is permanent.
        assert A._is_permanent_429("free daily rate limit exceeded — quota reached", "5") is True

    def test_transient_burst_is_not_permanent(self):
        assert A._is_permanent_429("Rate limit: too many requests per minute", "3") is False

    def test_plain_burst_without_body_is_not_permanent(self):
        assert A._is_permanent_429("", None) is False

    def test_long_retry_after_is_permanent(self):
        # A >=10 minute Retry-After signals a quota window, not a burst.
        assert A._is_permanent_429("rate limited", "900") is True

    def test_short_retry_after_is_transient(self):
        assert A._is_permanent_429("slow down", "30") is False

    def test_http_date_retry_after_does_not_crash(self):
        # Non-numeric Retry-After (HTTP-date) must not raise; falls back to body.
        assert A._is_permanent_429("temporary", "Wed, 21 Oct 2026 07:28:00 GMT") is False

    def test_gemini_per_minute_free_tier_is_transient(self):
        # Session 240 regression: gemini's per-minute free-tier 429 contains
        # "quota" + "free_tier" + "exceeded your current" AND embeds a short
        # retry window in the BODY (no retry-after header). It must be treated
        # as transient (recoverable), not hard-failed as permanent.
        body = (
            "You exceeded your current quota. "
            "Quota exceeded for metric: generate_content_free_tier_requests, "
            "limit: 20, model: gemini-2.5-flash. Please retry in 48.865624513s."
        )
        assert A._is_permanent_429(body, None) is False

    def test_gemini_billing_boilerplate_is_transient(self):
        # The EXACT real body — gemini says "check your plan and
        # billing details" on a 2.8s per-minute throttle. The generic "billing"
        # phrase must NOT hard-fail a recoverable window.
        body = (
            "You exceeded your current quota, please check your plan and billing "
            "details. Quota exceeded for metric: generate_content_free_tier_requests, "
            "limit: 20, model: gemini-2.5-flash. Please retry in 2.839669179s."
        )
        assert A._is_permanent_429(body, None) is False

    def test_gemini_retrydelay_field_is_transient(self):
        body = '{"error":{"code":429}, "retryDelay": "37s"}'
        assert A._is_permanent_429(body, None) is False

    def test_long_body_retry_window_is_permanent(self):
        # A long retry window embedded in the body is a quota window.
        assert A._is_permanent_429("please retry in 900s", None) is True


class TestParseRetryDelay:
    def test_header_numeric_wins(self):
        assert A._parse_retry_delay_seconds("ignored body", "12") == 12.0

    def test_body_retry_in_seconds(self):
        assert A._parse_retry_delay_seconds("Please retry in 48.865624513s.", None) == 48.865624513

    def test_body_retrydelay_field(self):
        assert A._parse_retry_delay_seconds('"retryDelay": "37s"', None) == 37.0

    def test_no_delay_returns_none(self):
        assert A._parse_retry_delay_seconds("no numbers here", None) is None

    def test_http_date_header_falls_back_to_body(self):
        assert A._parse_retry_delay_seconds("retry in 5s", "Wed, 21 Oct 2026 07:28:00 GMT") == 5.0
