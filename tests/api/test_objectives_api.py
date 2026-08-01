"""API tests for user-controlled autonomous objectives."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app
from core.objective_runtime import ObjectiveRuntime


def _client(tmp_db):
    app = create_app()
    # Test the route contract without starting a real worker or LLM adapter.
    app.state.objective_runtime = ObjectiveRuntime.__new__(ObjectiveRuntime)
    app.state.objective_runtime._store = __import__("storage.objectives", fromlist=["ObjectiveStore"]).ObjectiveStore(tmp_db)
    app.state.objective_runtime.interrupt = lambda _objective_id: None
    return TestClient(app, raise_server_exceptions=False)


def test_create_list_and_get_objective(tmp_db):
    client = _client(tmp_db)
    response = client.post(
        "/api/objectives",
        json={"session_id": "session-api", "prompt": "Research the FastAPI lifespan API"},
    )
    assert response.status_code == 202
    objective = response.json()
    assert objective["status"] == "queued"
    assert objective["session_id"] == "session-api"

    listed = client.get("/api/objectives?session_id=session-api")
    assert listed.status_code == 200
    assert listed.json()["objectives"][0]["id"] == objective["id"]

    fetched = client.get(f"/api/objectives/{objective['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["prompt"] == objective["prompt"]


def test_pause_resume_cancel_objective(tmp_db):
    client = _client(tmp_db)
    objective = client.post(
        "/api/objectives",
        json={"session_id": "session-api", "prompt": "Inspect the project"},
    ).json()
    objective_id = objective["id"]

    # Pause is valid for queued work and prevents the worker from claiming it.
    paused = client.post(f"/api/objectives/{objective_id}/pause")
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"

    resumed = client.post(f"/api/objectives/{objective_id}/resume", json={})
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "queued"

    canceled = client.post(f"/api/objectives/{objective_id}/cancel")
    assert canceled.status_code == 200
    assert canceled.json()["status"] == "canceled"


def test_objective_validation_and_missing_id(tmp_db):
    client = _client(tmp_db)
    assert client.post("/api/objectives", json={"session_id": "s", "prompt": ""}).status_code == 422
    assert client.get("/api/objectives/not-found").status_code == 404
