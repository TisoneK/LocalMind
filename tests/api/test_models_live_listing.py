"""The model picker lists the provider's real models for EVERY provider, not an allowlist."""

import pytest
from fastapi.testclient import TestClient


class _Adapter:
    async def list_models(self):
        return ["deepseek-flash", "deepseek-v4-pro"]

    context_window = 64000


@pytest.fixture
def client(monkeypatch):
    from api.app import create_app
    from api.routes import models as models_route
    from core.config import settings

    monkeypatch.setattr(settings, "localmind_adapter", "deepseek", raising=False)
    monkeypatch.setattr(models_route, "get_adapter", lambda *a, **k: _Adapter(), raising=False)
    return TestClient(create_app())


def test_deepseek_lists_the_plan_models_beside_the_default(client):
    body = client.get("/api/models").json()
    ids = [m["id"] for m in body["models"]]
    assert "deepseek-flash" in ids and "deepseek-v4-pro" in ids
    assert "deepseek-chat" in ids  # the configured default stays selectable


def test_hidden_models_leave_the_picker_and_added_ones_join_it(monkeypatch):
    from api.app import create_app
    from api.routes import models as models_route
    from core.config import settings
    from core.connections import Connection

    conn = Connection(
        id="deepseek", name="DeepSeek", base_url="https://api.deepseek.com",
        hidden_models=["deepseek-flash"], extra_models=["my-finetune"],
    )
    monkeypatch.setattr(settings, "localmind_adapter", "deepseek", raising=False)
    monkeypatch.setattr(models_route, "get_adapter", lambda *a, **k: _Adapter(), raising=False)
    import core.connections as cm

    monkeypatch.setattr(cm, "get_connection_registry", lambda: type("R", (), {"get": lambda self, i: conn, "all": lambda self: [conn], "ids": lambda self: ["deepseek"]})())
    ids = [m["id"] for m in TestClient(create_app()).get("/api/models").json()["models"]]
    assert "deepseek-flash" not in ids  # turned off
    assert "my-finetune" in ids and "deepseek-v4-pro" in ids


def test_the_model_in_use_is_never_hidden():
    from api.routes.models import _apply_model_prefs
    from core.connections import Connection

    conn = Connection(id="x", name="X", hidden_models=["m1"])
    opts = [{"id": "m1", "name": "m1", "provider": "x"}]
    assert [o["id"] for o in _apply_model_prefs(list(opts), conn, "m1", keep_hidden=False)] == ["m1"]
    flagged = _apply_model_prefs(list(opts), conn, "other", keep_hidden=True)
    assert flagged[0]["hidden"] is True
