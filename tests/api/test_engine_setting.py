"""The agent-engine setting: Classic (default) or State (experimental, ADR-71)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from core.config import settings


@pytest.fixture()
def client(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(settings, "_runtime_settings_path", lambda: path)
    return TestClient(create_app()), path


def test_default_engine_is_classic(client):
    c, _ = client
    assert c.get("/api/settings").json()["engine"] == "classic"


def test_choosing_state_is_persisted_and_reported(client):
    c, path = client
    r = c.post("/api/settings/engine", json={"engine": "State"})
    assert r.status_code == 200 and r.json()["engine"] == "state"
    assert json.loads(path.read_text())["engine"] == "state"
    assert c.get("/api/settings").json()["engine"] == "state"
    assert c.post("/api/settings/engine", json={"engine": "classic"}).json()["engine"] == "classic"


def test_unknown_engine_is_rejected_and_setting_unchanged(client):
    c, _ = client
    assert c.post("/api/settings/engine", json={"engine": "quantum"}).status_code == 400
    assert c.get("/api/settings").json()["engine"] == "classic"
