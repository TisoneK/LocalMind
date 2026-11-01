"""
API tests for the durable per-turn execution trace (B-2026-11-01-26).

Contract locked here:
  - GET /api/observability/{sid}/traces lists the retained turns, newest
    first, with event counts and wall-clock bounds;
  - GET /api/observability/{sid}/trace/{turn_id} replays the stream
    oldest-first; an unknown turn is an honest 404, never a guess;
  - the history payload exposes the persisted-but-previously-unreturned
    telemetry (cached tokens, llm calls, stage map, context composition,
    post-answer lanes) and the execution-trace link (traceId).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core.obs import ObsCollector
from storage.db import SessionStore


@pytest.fixture
def trace_api(tmp_path, monkeypatch):
    """A minimal app with the observability + sessions routers, both stores
    pointed at an isolated tmp DB."""
    from fastapi import FastAPI
    from api.routes import observability, sessions

    store = SessionStore(str(tmp_path / "api-trace.db"))

    class _StubEngine:
        _store = store

    monkeypatch.setattr(observability, "_get_engine", lambda: _StubEngine())
    monkeypatch.setattr(sessions, "_store", store, raising=False)

    app = FastAPI()
    app.include_router(observability.router, prefix="/api")
    app.include_router(sessions.router, prefix="/api")
    return app, store


def test_trace_list_and_replay_endpoints(trace_api):
    app, store = trace_api
    sid = "sess-api-trace"

    obs = ObsCollector()
    obs.emit("path_selected", path="fast_path", lane="trivial")
    obs.emit("model_call_started", call_id="call-1", payload_chars=100)
    for evt in obs.history():
        evt.ts = 1_700_000_000_000  # distinct, ordered wall-clock bounds
    store.append_turn_trace(sid, "turn-1", obs.history())
    obs2 = ObsCollector()
    obs2.emit("turn_complete", total_latency_ms=5)
    for evt in obs2.history():
        evt.ts = 1_700_000_005_000
    store.append_turn_trace(sid, "turn-2", obs2.history())

    with TestClient(app) as client:
        listed = client.get(f"/api/observability/{sid}/traces").json()
        assert [t["turnId"] for t in listed["traces"]] == ["turn-2", "turn-1"]
        assert listed["traces"][1]["eventCount"] == 2

        replay = client.get(f"/api/observability/{sid}/trace/turn-1").json()
        assert replay["turnId"] == "turn-1"
        assert [e["type"] for e in replay["events"]] == [
            "path_selected",
            "model_call_started",
        ]
        assert replay["events"][0]["data"]["lane"] == "trivial"

        missing = client.get(f"/api/observability/{sid}/trace/turn-none")
        assert missing.status_code == 404


def test_history_exposes_persisted_telemetry_and_trace_link(trace_api):
    app, store = trace_api
    sid = "sess-api-history"

    metrics = {
        "prompt_tokens": 564,
        "completion_tokens": 90,
        "latency_ms": 25_900,
        "cached_tokens": 560,
        "llm_calls": 4,
        "model": "glm-4.5-flash",
        "provider": "zai",
        "turn_stages": {"first_token": 1234, "turn_completed": 5678},
        "context_breakdown": {"system_prompt": 400, "history": 164},
        "post_answer_lanes": {"reflection": {"ms": 120}},
        "trace_id": "turn-hist-1",
    }
    from core.models import Message, Role

    store.append(
        sid,
        Message(role=Role.ASSISTANT, content="the answer", metrics=metrics),
    )

    with TestClient(app) as client:
        history = client.get(f"/api/sessions/{sid}/history").json()

    perf = history["history"][0]["performance"]
    assert perf["cachedTokens"] == 560
    assert perf["llmCalls"] == 4
    assert perf["turnStages"]["first_token"] == 1234
    assert perf["contextBreakdown"]["system_prompt"] == 400
    assert perf["postAnswerLanes"]["reflection"]["ms"] == 120
    assert perf["traceId"] == "turn-hist-1"
    # Legacy fields unchanged.
    assert perf["latencyMs"] == 25_900
    assert perf["promptTokens"] == 564
