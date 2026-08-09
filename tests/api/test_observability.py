"""Tests for the additive observability API snapshot projection."""

from __future__ import annotations

import pytest
from api.routes import observability
from core.obs import ObsCollector
from core.observation import ObservationSnapshot
from core.workspace_state import WorkspaceSnapshot
from fastapi import FastAPI
from fastapi.testclient import TestClient


class _Metrics:
    def get_all_metrics(self):
        return {}


class _Engine:
    def __init__(self, snapshot=None):
        self._last_observation = {
            "session-1": {
                "intent": "shell",
                "confidence": 0.9,
                "tools_used": "shell",
                "memory_hits": 2,
                "context_tokens": 120,
                "latency_ms": 45,
            }
        }
        self._last_observation_snapshots = {}
        if snapshot is not None:
            self._last_observation_snapshots["session-1"] = snapshot
        self._metrics = _Metrics()


@pytest.mark.asyncio
async def test_observability_includes_bounded_structured_snapshot(monkeypatch):
    """The new field is additive and contains a bounded public projection."""
    collector = ObsCollector()
    collector.emit("tool_status", tool="shell", output="x" * 5000)
    snapshot = ObservationSnapshot.from_events(
        WorkspaceSnapshot(
            git_available=True,
            git_branch="main",
            git_head="a" * 40,
            git_status="M " + "x" * 5000,
            open_files=["report.md"],
        ),
        collector.history(),
    )
    engine = _Engine(snapshot)
    monkeypatch.setattr(observability, "_get_engine", lambda: engine)

    response = await observability.get_observability("session-1")

    assert response.intent == "shell"
    assert response.observation is not None
    assert response.observation.workspace.git_branch == "main"
    assert len(response.observation.workspace.git_status) == 4000
    assert len(response.observation.recent_events) == 1
    event_data = response.observation.recent_events[0].data
    assert event_data["truncated"] is True
    assert len(event_data["preview"]) <= 500


@pytest.mark.asyncio
async def test_observability_without_snapshot_preserves_legacy_shape(monkeypatch):
    """Sessions created before structured capture still return valid data."""
    engine = _Engine()
    monkeypatch.setattr(observability, "_get_engine", lambda: engine)

    response = await observability.get_observability("session-1")

    assert response.intent == "shell"
    assert response.observation is None
    assert response.tools_used == "shell"


def test_observability_response_keeps_optional_snapshot_nullable():
    """Legacy callers can ignore the additive nullable snapshot field."""
    route = next(
        route
        for route in observability.router.routes
        if getattr(route, "path", "") == "/observability/{session_id}"
    )
    response = observability.ObservabilityData(session_id="legacy")

    assert route.response_model is observability.ObservabilityData
    assert response.model_dump()["observation"] is None
    assert response.model_dump()["intent"] is None


def test_observability_wire_response_preserves_nullable_legacy_fields(monkeypatch):
    """FastAPI serialization keeps old null fields and adds observation null."""
    engine = _Engine()
    engine._last_observation = {}
    monkeypatch.setattr(observability, "_get_engine", lambda: engine)
    app = FastAPI()
    app.include_router(observability.router, prefix="/api")

    with TestClient(app) as client:
        payload = client.get("/api/observability/unknown").json()

    assert payload["intent"] is None
    assert payload["confidence"] is None
    assert payload["observation"] is None
    assert payload["tool_timeline"] == []


@pytest.mark.asyncio
async def test_observability_without_any_data_returns_empty_optional_field(monkeypatch):
    """The existing empty response remains stable for unknown sessions."""
    engine = _Engine()
    engine._last_observation = {}
    monkeypatch.setattr(observability, "_get_engine", lambda: engine)

    response = await observability.get_observability("unknown")

    assert response.session_id == "unknown"
    assert response.observation is None
    assert response.intent is None


@pytest.mark.asyncio
async def test_fallback_never_leaks_cross_session_metrics(monkeypatch):
    """B-2026-08-09-5: with no per-session observation, the endpoint must NOT
    return another session's intent/latency from the intent-keyed MetricsStore
    aggregate (the old fallback returned the first intent with any requests)."""
    class _Metrics:
        def get_all_metrics(self):
            # Intent-keyed aggregate that WOULD have leaked under the old fallback.
            return {"web_search": {"total_requests": 5, "p50_latency_ms": 1234.0}}

    class _Engine:
        def __init__(self):
            self._last_observation = {}
            self._last_observation_snapshots = {}
            self._metrics = _Metrics()

    engine = _Engine()
    monkeypatch.setattr(observability, "_get_engine", lambda: engine)

    response = await observability.get_observability("some-session")

    assert response.session_id == "some-session"
    assert response.intent is None
    assert response.confidence is None
    assert response.tools_used == ""
    assert response.latency_ms == 0
    assert response.memory_hits == 0
