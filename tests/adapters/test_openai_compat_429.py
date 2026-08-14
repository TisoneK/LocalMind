"""Regression tests for the 429 permanent-vs-transient classifier (ADR-32).

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
