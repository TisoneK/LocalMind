"""
Storage tests for the durable per-turn execution trace
(``storage/db.py`` turn_traces, B-2026-11-01-26).

Contract locked here:
  - the full per-request event stream lands verbatim (turn_id + seq +
    emit-time ts), oldest first on read;
  - oversized event payloads are bounded with an explicit _truncated
    marker, never silently dropped;
  - retention keeps only the newest turns per session (prune on write);
  - the trace dies with its session (cascade delete).
"""

from __future__ import annotations

import json

import pytest

from core.obs import ObsCollector
from storage import db as db_mod
from storage.db import SessionStore


@pytest.fixture
def store(tmp_path):
    return SessionStore(str(tmp_path / "trace-test.db"))


def _collector_with(events: list[tuple[str, dict]]) -> ObsCollector:
    obs = ObsCollector()
    for etype, data in events:
        obs.emit(etype, **data)
    return obs


class TestAppendAndGet:
    def test_roundtrip_preserves_stream_order(self, store):
        sid = "sess-trace-store"
        obs = _collector_with(
            [
                ("path_selected", {"path": "fast_path", "lane": "trivial"}),
                ("model_call_started", {"call_id": "call-1", "payload_chars": 10}),
                ("model_call_completed", {"call_id": "call-1", "duration_ms": 42}),
            ]
        )
        turn_id = "turn-abc"
        written = store.append_turn_trace(sid, turn_id, obs.history())
        assert written == 3

        trace = store.get_turn_trace(sid, turn_id)
        assert trace is not None
        assert trace["eventCount"] == 3
        assert [e["seq"] for e in trace["events"]] == [0, 1, 2]
        assert [e["type"] for e in trace["events"]] == [
            "path_selected",
            "model_call_started",
            "model_call_completed",
        ]
        # Monotone emit-time timestamps, epoch-ms integers.
        ts_list = [e["ts"] for e in trace["events"]]
        assert all(isinstance(t, int) for t in ts_list)
        assert ts_list == sorted(ts_list)

    def test_missing_trace_returns_none(self, store):
        store.ensure_session("sess-empty")
        assert store.get_turn_trace("sess-empty", "turn-none") is None

    def test_empty_event_list_writes_nothing(self, store):
        sid = "sess-no-events"
        assert store.append_turn_trace(sid, "turn-x", []) == 0
        assert store.list_turn_traces(sid) == []


class TestBounds:
    def test_oversized_event_data_is_truncated_with_marker(self, store, monkeypatch):
        monkeypatch.setattr(db_mod, "_TRACE_EVENT_DATA_CAP_CHARS", 200)
        sid = "sess-truncate"
        obs = _collector_with([("tool_result", {"output": "x" * 5000})])
        store.append_turn_trace(sid, "turn-big", obs.history())

        trace = store.get_turn_trace(sid, "turn-big")
        data = trace["events"][0]["data"]
        assert data["_truncated"] is True
        assert data["original_chars"] > 200
        assert len(data["preview"]) == 200
        # The oversized original must not be in the store.
        assert "x" * 300 not in json.dumps(trace)

    def test_retention_prunes_oldest_turns(self, store, monkeypatch):
        monkeypatch.setattr(db_mod, "TRACE_TURNS_RETAINED", 2)
        sid = "sess-prune"
        for i in range(4):
            obs = _collector_with([("agent_runtime_start", {"n": i})])
            # Force distinct, ordered startedTs values (ts is epoch-ms; same-ms
            # writes would make the retention ordering ambiguous).
            for evt in obs.history():
                evt.ts = 1_700_000_000_000 + i * 1000
            store.append_turn_trace(sid, f"turn-{i}", obs.history())

        listed = store.list_turn_traces(sid)
        assert {t["turnId"] for t in listed} == {"turn-2", "turn-3"}
        assert listed[0]["turnId"] == "turn-3"  # newest first

    def test_list_is_newest_first_with_counts(self, store):
        sid = "sess-list"
        obs_a = _collector_with([("a", {}), ("b", {})])
        for evt in obs_a.history():
            evt.ts = 1_700_000_000_000
        obs_b = _collector_with([("c", {})])
        for evt in obs_b.history():
            evt.ts = 1_700_000_005_000
        store.append_turn_trace(sid, "turn-a", obs_a.history())
        store.append_turn_trace(sid, "turn-b", obs_b.history())

        listed = store.list_turn_traces(sid)
        assert [t["turnId"] for t in listed] == ["turn-b", "turn-a"]
        assert listed[1]["eventCount"] == 2


class TestSessionCascade:
    def test_trace_dies_with_session(self, store, tmp_path):
        sid = "sess-cascade"
        obs = _collector_with([("turn_complete", {})])
        store.append_turn_trace(sid, "turn-doomed", obs.history())
        assert store.get_turn_trace(sid, "turn-doomed") is not None

        store.delete_session(sid)
        assert store.get_turn_trace(sid, "turn-doomed") is None
        assert store.list_turn_traces(sid) == []
