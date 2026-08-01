"""Lifecycle coverage for the autonomous objective supervisor."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app
from core.config import settings
from core.objective_runtime import ObjectiveRuntime


def test_objective_runtime_starts_and_stops_with_app_lifespan(tmp_db, monkeypatch):
    started = False
    stopped = False

    async def fake_start(self):
        nonlocal started
        started = True

    async def fake_stop(self):
        nonlocal stopped
        stopped = True

    monkeypatch.setattr(settings, "localmind_adapter", "openai")
    monkeypatch.setattr(settings, "localmind_db_path", tmp_db)
    monkeypatch.setattr(ObjectiveRuntime, "start", fake_start)
    monkeypatch.setattr(ObjectiveRuntime, "stop", fake_stop)
    monkeypatch.setattr("core.knowledge_writer.update_knowledge_doc", lambda: None)
    monkeypatch.setattr("api.routes.health.set_engine_ready", lambda: None)

    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/api/objectives").status_code == 200
        assert started is True
        assert stopped is False

    assert stopped is True
