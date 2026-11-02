"""The provider-timing fold: turn events → the first-token/decode pair.

The observability investigation's finding 5c/5d: tokens-per-second used the
whole-turn wall clock as its denominator (making latency ≈ completion ÷
tok/s circular arithmetic), and the pre-generation wait was unmeasured on
every path. The fix is a pure fold over the turn's model-call stamps:
``derive_call_timing`` returns the FIRST call's submit→first-byte window and
the FINAL call's first-byte→last-byte decode window — the honest pair the
persisted metrics, the done payload and the history surface all consume.
"""

from __future__ import annotations

from core.obs import ObsCollector
from core.turn_trace import derive_call_timing


def _seed(*pairs) -> ObsCollector:
    obs = ObsCollector()
    for etype, data in pairs:
        obs.emit(etype, **data)
    return obs


class TestDeriveCallTiming:
    def test_full_stream_yields_both_windows(self):
        obs = _seed(
            ("model_call_started", {"call_id": "c1", "submitted_at": 1_000}),
            ("model_call_first_byte", {"call_id": "c1", "first_byte_at": 1_400}),
            ("model_call_completed", {"call_id": "c1", "last_byte_at": 3_400}),
        )
        timing = derive_call_timing(obs.history())
        assert timing == {"first_token_ms": 400, "decode_ms": 2_000}

    def test_first_token_comes_from_the_first_call_decode_from_the_last(self):
        obs = _seed(
            ("model_call_started", {"call_id": "c1", "submitted_at": 1_000}),
            ("model_call_first_byte", {"call_id": "c1", "first_byte_at": 1_900}),
            ("model_call_completed", {"call_id": "c1", "last_byte_at": 2_400}),
            ("model_call_started", {"call_id": "c2", "submitted_at": 5_000}),
            ("model_call_first_byte", {"call_id": "c2", "first_byte_at": 5_200}),
            ("model_call_completed", {"call_id": "c2", "last_byte_at": 7_200}),
        )
        timing = derive_call_timing(obs.history())
        assert timing["first_token_ms"] == 900  # c1's submit→first byte
        assert timing["decode_ms"] == 2_000  # c2's first→last byte

    def test_a_call_that_never_streamed_yields_no_decode_window(self):
        obs = _seed(
            ("model_call_started", {"call_id": "c1", "submitted_at": 1_000}),
            ("model_call_failed", {"call_id": "c1", "failed_at": 1_100}),
        )
        assert derive_call_timing(obs.history()) == {}

    def test_non_model_call_events_are_ignored(self):
        obs = _seed(
            ("path_selected", {"path": "fast_path"}),
            ("turn_complete", {"total_latency_ms": 9_000}),
        )
        assert derive_call_timing(obs.history()) == {}

    def test_persisted_trace_rows_fold_the_same_way(self):
        """The same fold serves the live collector history and the persisted
        trace rows ({"type", "data"} dicts) — replayed turns get identical
        numbers."""
        rows = [
            {"type": "model_call_started", "data": {"call_id": "c1", "submitted_at": 1_000}},
            {"type": "model_call_first_byte", "data": {"call_id": "c1", "first_byte_at": 1_400}},
            {"type": "model_call_completed", "data": {"call_id": "c1", "last_byte_at": 3_400}},
        ]
        assert derive_call_timing(rows) == {"first_token_ms": 400, "decode_ms": 2_000}

    def test_same_instant_stamps_report_zero_windows_honestly(self):
        """A same-instant first byte (a cache-served reply) is a REAL 0 ms
        measurement — reported as 0, never inflated, never dropped. The
        display layer treats 0 as 'no usable window' and falls back to the
        labelled wall-clock basis; the record itself does not editorialize."""
        obs = _seed(
            ("model_call_started", {"call_id": "c1", "submitted_at": 1_000}),
            ("model_call_first_byte", {"call_id": "c1", "first_byte_at": 1_000}),
            ("model_call_completed", {"call_id": "c1", "last_byte_at": 1_000}),
        )
        assert derive_call_timing(obs.history()) == {"first_token_ms": 0, "decode_ms": 0}
