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
