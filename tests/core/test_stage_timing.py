"""
Tests for ADR-12 per-stage timing (B-2026-08-09-2).

The Observe panel's "Agent Pipeline" section previously derived stage status
from a frontend heuristic that left "Tool Select" orange forever on completed
no-tool turns and showed "Execute" as done with no tools. The engine's
_StageClock now emits real ``stage_timing`` obs events (stage, latency_ms,
status) so the panel renders truth (done/skipped) with real timings.

Covered here:
  - _StageClock unit behavior (start/end/skip/snapshot + obs events)
  - Engine emits stage_timing on trivial + conversational short-circuits
  - _store_observation folds stage_timings into the polling snapshot
  - The observability route exposes stage_timings to the frontend
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from core.obs import ObsCollector

# ── _StageClock unit tests ─────────────────────────────────────────────────

class TestStageClock:
    def _make_clock(self):
        obs = ObsCollector()
        from core.engine._pipeline import _StageClock
        clock = _StageClock(obs)
        return clock, obs

    def test_start_end_emits_done_with_latency(self):
        clock, obs = self._make_clock()
        clock.start("intent_classify")
        clock.end("intent_classify")

        events = [e for e in obs.history() if e.type == "stage_timing"]
        assert len(events) == 1
        assert events[0].data["stage"] == "intent_classify"
        assert events[0].data["status"] == "done"
        assert isinstance(events[0].data["latency_ms"], int)
        assert events[0].data["latency_ms"] >= 0

    def test_end_without_start_is_noop(self):
        clock, obs = self._make_clock()
        clock.end("never_started")
        assert [e for e in obs.history() if e.type == "stage_timing"] == []

    def test_skip_emits_skipped_with_zero_latency(self):
        clock, obs = self._make_clock()
        clock.skip("tool_select")

        events = [e for e in obs.history() if e.type == "stage_timing"]
        assert len(events) == 1
        assert events[0].data["status"] == "skipped"
        assert events[0].data["latency_ms"] == 0

    def test_snapshot_returns_all_stages(self):
        clock, _ = self._make_clock()
        clock.start("intent_classify")
        clock.end("intent_classify")
        clock.skip("tool_select")

        snap = clock.snapshot()
        assert set(snap.keys()) == {"intent_classify", "tool_select"}
        assert snap["tool_select"]["status"] == "skipped"
        assert "latency_ms" in snap["intent_classify"]

    def test_mark_records_explicit_latency(self):
        clock, obs = self._make_clock()
        clock.mark("execute", 123, "done")
        events = [e for e in obs.history() if e.type == "stage_timing"]
        assert events[0].data == {"stage": "execute", "latency_ms": 123, "status": "done"}


# ── Engine emission on short-circuits ──────────────────────────────────────

class TestEngineStageTiming:
    @pytest.mark.asyncio
    async def test_trivial_turn_emits_truthful_stage_timings(self):
        """A trivial greeting must report intent_classify/generate done and
        tool_select/execute SKIPPED — not stuck 'running' (ADR-12)."""
        from core.engine import Engine

        engine = Engine()
        obs = ObsCollector()

        async def mock_chat(messages, intent="chat", **kwargs):
            yield MagicMock(text="Hi! How can I help?", done=False, error=None)
            yield MagicMock(text="", done=True, error=None)

        mock_adapter = MagicMock()
        mock_adapter.chat = mock_chat

        with patch("core.engine.get_adapter", return_value=mock_adapter):
            chunks = [c async for c in engine.process("hi", "sess-stage-trivial", obs=obs)]

        assert any(getattr(c, "done", False) for c in chunks)

        timings = [e for e in obs.history() if e.type == "stage_timing"]
        by_stage = {e.data["stage"]: e.data for e in timings}

        # intent_classify + generate ran (done); no tools → skipped.
        assert by_stage["intent_classify"]["status"] == "done"
        assert by_stage["generate"]["status"] == "done"
        assert by_stage["tool_select"]["status"] == "skipped"
        assert by_stage["execute"]["status"] == "skipped"
        # No stage may report 'running' at completion — that was the bug.
        assert all(e.data["status"] != "running" for e in timings)

    @pytest.mark.asyncio
    async def test_conversational_question_emits_truthful_stage_timings(self):
        """Conversational-question short-circuit (ADR-11) also reports
        truthful stage timings (generate done, tools skipped)."""
        from core.engine import Engine

        engine = Engine()
        obs = ObsCollector()

        async def mock_chat(messages, intent="chat", **kwargs):
            yield MagicMock(text="I can help with code, files, and more!", done=False, error=None)
            yield MagicMock(text="", done=True, error=None)

        mock_adapter = MagicMock()
        mock_adapter.chat = mock_chat

        with patch("core.engine.get_adapter", return_value=mock_adapter):
            chunks = [c async for c in engine.process("What can you do?", "sess-stage-conv", obs=obs)]

        assert any(getattr(c, "done", False) for c in chunks)

        timings = [e for e in obs.history() if e.type == "stage_timing"]
        by_stage = {e.data["stage"]: e.data for e in timings}

        assert by_stage["intent_classify"]["status"] == "done"
        assert by_stage["generate"]["status"] == "done"
        assert by_stage["tool_select"]["status"] == "skipped"
        assert by_stage["execute"]["status"] == "skipped"


# ── _store_observation folding ─────────────────────────────────────────────

class TestStoreObservationFolding:
    def test_store_observation_folds_stage_timings(self):
        """_store_observation must fold stage_timing events from the request
        collector so the polling observability endpoint returns them too."""
        from core.engine import Engine

        engine = Engine()
        engine._last_observation = {}  # isolate from other tests

        obs = ObsCollector()
        obs.emit("stage_timing", stage="intent_classify", latency_ms=42, status="done")
        obs.emit("stage_timing", stage="tool_select", latency_ms=0, status="skipped")

        engine._store_observation("sess-fold", obs, intent="chat", latency_ms=50)

        stored = engine._last_observation["sess-fold"]
        assert stored["stage_timings"]["intent_classify"] == {"latency_ms": 42, "status": "done"}
        assert stored["stage_timings"]["tool_select"] == {"latency_ms": 0, "status": "skipped"}
        # Existing fields still stored
        assert stored["intent"] == "chat"
        assert stored["latency_ms"] == 50

    def test_store_observation_without_stage_events_keeps_shape(self):
        """Turns without stage_timing events must not gain an empty key."""
        from core.engine import Engine

        engine = Engine()
        engine._last_observation = {}

        obs = ObsCollector()
        engine._store_observation("sess-plain", obs, intent="chat", latency_ms=10)

        stored = engine._last_observation["sess-plain"]
        assert "stage_timings" not in stored


# ── Observability route exposure ───────────────────────────────────────────

class TestObservabilityStageTimings:
    def test_observability_data_model_accepts_stage_timings(self):
        from api.routes.observability import ObservabilityData

        data = ObservabilityData(
            session_id="s1",
            intent="chat",
            stage_timings={"intent_classify": {"latency_ms": 42, "status": "done"}},
        )
        dumped = data.model_dump()
        assert dumped["stage_timings"]["intent_classify"]["latency_ms"] == 42

    @pytest.mark.asyncio
    async def test_observability_route_returns_stage_timings(self, monkeypatch):
        from api.routes import observability

        class _Metrics:
            def get_all_metrics(self):
                return {}

        class _Engine:
            def __init__(self):
                self._last_observation = {
                    "session-1": {
                        "intent": "chat",
                        "confidence": 0.9,
                        "tools_used": "",
                        "memory_hits": 0,
                        "context_tokens": 10,
                        "latency_ms": 50,
                        "stage_timings": {
                            "intent_classify": {"latency_ms": 30, "status": "done"},
                            "generate": {"latency_ms": 20, "status": "done"},
                            "tool_select": {"latency_ms": 0, "status": "skipped"},
                            "execute": {"latency_ms": 0, "status": "skipped"},
                        },
                    }
                }
                self._last_observation_snapshots = {}
                self._metrics = _Metrics()

        engine = _Engine()
        monkeypatch.setattr(observability, "_get_engine", lambda: engine)

        response = await observability.get_observability("session-1")

        assert response.stage_timings is not None
        assert response.stage_timings["tool_select"]["status"] == "skipped"
        assert response.stage_timings["generate"]["latency_ms"] == 20
