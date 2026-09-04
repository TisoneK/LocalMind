"""P0 Context Engineering Step 1 — per-call usage accumulation tests.

Pins `_merge_call_usage` semantics: occupancy fields keep LAST-CALL values
(the context meter must reflect what the next call carries), while the
`total_*` fields accumulate across every call in a turn and `llm_calls`
counts the calls that reported usage. Also pins the MetricsStore pass-through
of `cached_tokens` / `llm_calls` to /api/metrics.
"""

import pytest

from core.agent.loop import _merge_call_usage
from core.metrics import MetricsStore


class TestMergeCallUsage:
    def test_two_calls_accumulate_totals_and_keep_last_occupancy(self):
        accum: dict[str, int] = {}
        _merge_call_usage(accum, {"prompt_tokens": 1000, "completion_tokens": 50, "cached_tokens": 800})
        _merge_call_usage(accum, {"prompt_tokens": 1200, "completion_tokens": 80, "cached_tokens": 1000})

        # Occupancy = last call (what the next call will carry).
        assert accum["prompt_tokens"] == 1200
        assert accum["completion_tokens"] == 80
        assert accum["cached_tokens"] == 1000
        # Totals = sum across calls (real per-turn cost).
        assert accum["total_prompt_tokens"] == 2200
        assert accum["total_completion_tokens"] == 130
        assert accum["total_cached_tokens"] == 1800
        # Both calls reported prompt usage.
        assert accum["llm_calls"] == 2

    def test_no_usage_reported_leaves_accumulator_empty(self):
        accum: dict[str, int] = {}
        _merge_call_usage(accum, {"other": 1})
        assert accum == {"other": 1}
        _merge_call_usage(accum, {})
        assert accum.get("llm_calls") is None

    def test_zero_and_negative_values_are_ignored(self):
        accum: dict[str, int] = {}
        _merge_call_usage(accum, {"prompt_tokens": 0, "cached_tokens": -5, "completion_tokens": 10})
        assert "total_prompt_tokens" not in accum
        assert "total_cached_tokens" not in accum
        assert accum["total_completion_tokens"] == 10
        # A call that reports no prompt tokens does not count as a call.
        assert accum.get("llm_calls") is None

    def test_cache_miss_field_accumulates(self):
        accum: dict[str, int] = {}
        _merge_call_usage(accum, {"prompt_tokens": 100, "cache_miss_tokens": 100})
        _merge_call_usage(accum, {"prompt_tokens": 100, "cache_miss_tokens": 50})
        assert accum["total_cache_miss_tokens"] == 150

    def test_float_values_are_coerced_to_int(self):
        accum: dict[str, int] = {}
        _merge_call_usage(accum, {"prompt_tokens": 100.0, "completion_tokens": 5.0})
        assert accum["total_prompt_tokens"] == 100
        assert isinstance(accum["total_prompt_tokens"], int)


class TestMetricsStoreCacheTelemetry:
    def test_record_streaming_complete_stores_cache_fields(self):
        store = MetricsStore()
        store.start_request()
        store.record_streaming_complete(
            total_tokens=1300,
            prompt_tokens=1250,
            completion_tokens=50,
            cached_tokens=1024,
            llm_calls=3,
        )
        m = store.get_streaming_metrics()
        assert m["cachedTokens"] == 1024
        assert m["llmCalls"] == 3

    def test_defaults_are_zero_when_provider_omits_cache(self):
        store = MetricsStore()
        store.start_request()
        store.record_streaming_complete(total_tokens=100, prompt_tokens=90, completion_tokens=10)
        m = store.get_streaming_metrics()
        assert m["cachedTokens"] == 0
        assert m["llmCalls"] == 0

    def test_start_request_resets_cache_fields(self):
        store = MetricsStore()
        store.start_request()
        store.record_streaming_complete(total_tokens=100, prompt_tokens=90, completion_tokens=10, cached_tokens=80, llm_calls=2)
        store.start_request()
        m = store.get_streaming_metrics()
        assert m["cachedTokens"] == 0
        assert m["llmCalls"] == 0

    def test_none_values_are_treated_as_zero(self):
        store = MetricsStore()
        store.start_request()
        store.record_streaming_complete(
            total_tokens=100, prompt_tokens=90, completion_tokens=10,
            cached_tokens=None, llm_calls=None,
        )
        m = store.get_streaming_metrics()
        assert m["cachedTokens"] == 0
        assert m["llmCalls"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
