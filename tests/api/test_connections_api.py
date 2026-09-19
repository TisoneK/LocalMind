"""API tests for the AI-connections endpoints (api/routes/config.py).

POST /settings/connections creates custom endpoints and stores preset
overrides; DELETE removes/resets them; the test endpoint probes an
endpoint and stores what it learns. All transport is faked — the probe's
job is honest reporting, and its network behavior is exercised live in
the verification harness.
"""

import types

import pytest

from api.routes import config as config_mod


def _fake_settings(connections=None, api_keys=None, adapter="ollama"):
    captured = {}

    def save_connection_record(record):
        captured["record"] = record

    def delete_connection_record(connection_id):
        captured["deleted"] = connection_id
        return True

    def get_api_key(provider):
        return (api_keys or {}).get(provider)

    def save_runtime_settings(**kwargs):
        captured.setdefault("runtime", {}).update(kwargs)

    ns = types.SimpleNamespace(
        localmind_adapter=adapter,
        get_api_key=get_api_key,
        save_connection_record=save_connection_record,
        delete_connection_record=delete_connection_record,
        save_runtime_settings=save_runtime_settings,
        _runtime_connections=connections or [],
        _captured=captured,
        # Legacy model fields the probe/update paths may read for presets,
        # plus the Ollama fields get_settings reads.
        zai_model="",
        ollama_model="",
        ollama_embed_model="",
        ollama_num_ctx=0,
        localmind_shell_enabled=False,
        localmind_thinking="enabled",
        localmind_reasoning_timeout_secs=180.0,
        localmind_reasoning_plan_timeout_secs=30.0,
        localmind_reasoning_max_wall_clock_secs=360.0,
        localmind_reasoning_effort="",
        localmind_startup_session="new",
        localmind_chat_mode="auto",
        localmind_permissions={},
        _load_json_file=lambda path: {},
        _runtime_settings_path=lambda: "unused",
        _secure_write_json=lambda path, data: None,
    )
    return ns


@pytest.fixture
def no_adapter_cache(monkeypatch):
    monkeypatch.setattr(config_mod, "clear_adapter_cache", lambda *a, **k: None)


@pytest.fixture
def stub_registry(monkeypatch):
    """Route the endpoints' registry lookups through the fake's stored records.

    The endpoints import get_connection_registry from core.connections at
    call time; that module-level function reads the REAL settings singleton,
    so the tests patch it to a registry built from the fake settings.
    """
    import core.connections as connections_mod

    monkeypatch.setattr(
        connections_mod,
        "get_connection_registry",
        lambda: connections_mod.ConnectionRegistry(list(config_mod.settings._runtime_connections)),
    )
    monkeypatch.setattr(connections_mod, "invalidate_connection_registry", lambda: None)


# ── POST /settings/connections ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_custom_connection(monkeypatch, no_adapter_cache):
    from api.routes.config import ConnectionSaveRequest, save_connection

    fake = _fake_settings()
    monkeypatch.setattr(config_mod, "settings", fake)

    result = await save_connection(
        ConnectionSaveRequest(
            id="atria-proxy",
            name="Atria Local Proxy",
            base_url="http://localhost:4000/v1",
            model="atria-dawn-preview",
        )
    )
    record = result["connection"]
    assert record["id"] == "atria-proxy"
    assert record["name"] == "Atria Local Proxy"
    assert record["base_url"] == "http://localhost:4000/v1"
    assert record["model"] == "atria-dawn-preview"
    assert record["enabled"] is True
    assert fake._captured["record"]["id"] == "atria-proxy"


@pytest.mark.asyncio
async def test_create_connection_rejects_bad_ids(monkeypatch, no_adapter_cache):
    from api.routes.config import ConnectionSaveRequest, save_connection
    from fastapi import HTTPException

    fake = _fake_settings()
    monkeypatch.setattr(config_mod, "settings", fake)

    for bad_id in ("Atria", "has space", "-lead", "a--b", ""):
        with pytest.raises(HTTPException) as exc:
            await save_connection(
                ConnectionSaveRequest(id=bad_id, name="X", base_url="http://h/v1", model="m")
            )
        assert exc.value.status_code == 400, bad_id


@pytest.mark.asyncio
async def test_create_connection_requires_name_url_and_model(monkeypatch, no_adapter_cache):
    from api.routes.config import ConnectionSaveRequest, save_connection
    from fastapi import HTTPException

    fake = _fake_settings()
    monkeypatch.setattr(config_mod, "settings", fake)

    with pytest.raises(HTTPException):
        await save_connection(ConnectionSaveRequest(id="x-1"))
    with pytest.raises(HTTPException):
        await save_connection(ConnectionSaveRequest(id="x-1", name="X"))
    with pytest.raises(HTTPException):
        await save_connection(
            ConnectionSaveRequest(id="x-1", name="X", base_url="http://localhost:4000/v1")
        )


@pytest.mark.asyncio
async def test_create_connection_rejects_non_http_base_url(monkeypatch, no_adapter_cache):
    from api.routes.config import ConnectionSaveRequest, save_connection
    from fastapi import HTTPException

    fake = _fake_settings()
    monkeypatch.setattr(config_mod, "settings", fake)

    with pytest.raises(HTTPException, match="http://"):
        await save_connection(
            ConnectionSaveRequest(
                id="x-1", name="X", base_url="file:///etc/passwd", model="m"
            )
        )


@pytest.mark.asyncio
async def test_update_preset_stores_override(monkeypatch, no_adapter_cache):
    from api.routes.config import ConnectionSaveRequest, save_connection

    fake = _fake_settings()
    monkeypatch.setattr(config_mod, "settings", fake)

    result = await save_connection(
        ConnectionSaveRequest(id="zai", base_url="https://proxy.example.com/v1")
    )
    record = result["connection"]
    assert record["id"] == "zai"
    assert record["base_url"] == "https://proxy.example.com/v1"
    # Preset seeds still flow through: name kept from the registry.
    assert record["name"] == "Z.ai (GLM)"
    assert record["model"] == ""


@pytest.mark.asyncio
async def test_update_validates_capabilities(monkeypatch, no_adapter_cache):
    from api.routes.config import ConnectionSaveRequest, save_connection

    fake = _fake_settings()
    monkeypatch.setattr(config_mod, "settings", fake)

    result = await save_connection(
        ConnectionSaveRequest(
            id="zai",
            capabilities={"tool_calling": False, "context_window": "200000", "junk": 1},
        )
    )
    caps = result["connection"]["capabilities"]
    assert caps["tool_calling"] is False
    assert caps["context_window"] == 200000
    assert "junk" not in caps


# ── DELETE /settings/connections/{id} ───────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_custom_connection_resets_active_adapter(monkeypatch, no_adapter_cache, stub_registry):
    from api.routes.config import delete_connection

    fake = _fake_settings(
        connections=[
            {
                "id": "atria-proxy",
                "name": "Atria",
                "base_url": "http://localhost:4000/v1",
                "model": "atria-dawn-preview",
            }
        ],
        adapter="atria-proxy",
    )
    monkeypatch.setattr(config_mod, "settings", fake)

    result = await delete_connection("atria-proxy")
    assert result["deleted"] is True
    assert result["adapter"] == "ollama"  # never points at a deleted endpoint
    assert fake.localmind_adapter == "ollama"


@pytest.mark.asyncio
async def test_delete_preset_is_a_reset(monkeypatch, no_adapter_cache):
    from api.routes.config import delete_connection

    fake = _fake_settings()
    monkeypatch.setattr(config_mod, "settings", fake)

    result = await delete_connection("zai")
    assert result["deleted"] is True
    assert "Reset" in result["message"]


@pytest.mark.asyncio
async def test_delete_unknown_and_ollama(monkeypatch, no_adapter_cache, stub_registry):
    from api.routes.config import delete_connection
    from fastapi import HTTPException

    fake = _fake_settings()
    monkeypatch.setattr(config_mod, "settings", fake)

    with pytest.raises(HTTPException) as exc:
        await delete_connection("nope")
    assert exc.value.status_code == 404

    with pytest.raises(HTTPException) as exc:
        await delete_connection("ollama")
    assert exc.value.status_code == 400


# ── POST /settings/connections/{id}/test ────────────────────────────────────


class _FakeResponse:
    def __init__(self, status_code, text="", payload=None):
        self.status_code = status_code
        self.text = text
        self._payload = payload or {}

    def json(self):
        return self._payload


class _FakeStream:
    def __init__(self, status_code=200, frames=("data: {\"choices\":[{\"delta\":{\"content\":\"p\"}}]}", "data: [DONE]")):
        self.status_code = status_code
        self._frames = frames

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def aiter_lines(self):
        for frame in self._frames:
            yield frame


class _FakeClient:
    """Fake httpx.AsyncClient for the probe endpoint."""

    def __init__(self, get_response=None, post_response=None, stream=None):
        self._get_response = get_response or _FakeResponse(200)
        self._post_response = post_response or _FakeResponse(200, payload={"ok": True})
        self._stream = stream or _FakeStream()
        self.requests = []

    async def get(self, url, headers=None, timeout=None):
        self.requests.append(("get", url, headers))
        return self._get_response

    async def post(self, url, json=None, headers=None, timeout=None):
        self.requests.append(("post", url, headers, json))
        return self._post_response

    def stream(self, method, url, json=None, headers=None):
        self.requests.append(("stream", url, headers, json))
        return self._stream

    async def aclose(self):
        pass


def _models_response():
    return _FakeResponse(
        200,
        payload={
            "data": [
                {
                    "id": "atria-dawn-preview",
                    "context_length": 131072,
                }
            ]
        },
    )


@pytest.mark.asyncio
async def test_connection_probe_reports_and_stores_capabilities(monkeypatch, stub_registry):
    from api.routes.config import test_connection

    client = _FakeClient(get_response=_models_response())
    monkeypatch.setattr(config_mod.httpx, "AsyncClient", lambda *a, **k: client)
    fake = _fake_settings(
        connections=[
            {
                "id": "atria-proxy",
                "name": "Atria",
                "base_url": "http://localhost:4000/v1",
                "model": "atria-dawn-preview",
            }
        ],
        api_keys={"atria-proxy": "sk-test"},
    )
    monkeypatch.setattr(config_mod, "settings", fake)
    monkeypatch.setattr(config_mod, "clear_adapter_cache", lambda *a, **k: None)

    result = await test_connection("atria-proxy")
    assert result["ok"] is True
    assert result["reachable"] is True
    assert result["auth_ok"] is True
    assert result["chat_ok"] is True
    assert result["streaming_ok"] is True
    assert result["tools"] == "accepted"
    assert result["context_window"] == 131072
    assert result["models_count"] == 1
    # Discovered facts are stored back on the connection.
    assert result["stored"]["context_window"] == 131072
    assert fake._captured["record"]["id"] == "atria-proxy"
    # The probe request carried the connection's key as a Bearer header.
    assert client.requests[0][2]["Authorization"] == "Bearer sk-test"


@pytest.mark.asyncio
async def test_connection_probe_reports_rejected_key(monkeypatch, stub_registry):
    from api.routes.config import test_connection

    client = _FakeClient(
        get_response=_FakeResponse(401, text="invalid api key"),
        post_response=_FakeResponse(401, text="invalid api key sk-test"),
    )
    monkeypatch.setattr(config_mod.httpx, "AsyncClient", lambda *a, **k: client)
    fake = _fake_settings(
        connections=[
            {"id": "gw", "name": "GW", "base_url": "http://localhost:4000/v1", "model": "m"}
        ],
        api_keys={"gw": "sk-test"},
    )
    monkeypatch.setattr(config_mod, "settings", fake)
    monkeypatch.setattr(config_mod, "clear_adapter_cache", lambda *a, **k: None)

    result = await test_connection("gw")
    assert result["ok"] is False
    assert result["auth_ok"] is False
    assert result["chat_ok"] is False
    # The key value never leaks back to the client, even from a provider echo.
    assert "sk-test" not in json_dumps(result)


def json_dumps(value):
    import json

    return json.dumps(value)


@pytest.mark.asyncio
async def test_connection_probe_connect_error_is_honest(monkeypatch, stub_registry):
    from api.routes.config import test_connection

    class _ConnectErrorClient:
        async def get(self, *a, **k):
            import httpx

            raise httpx.ConnectError("refused")

        async def aclose(self):
            pass

    monkeypatch.setattr(config_mod.httpx, "AsyncClient", lambda *a, **k: _ConnectErrorClient())
    fake = _fake_settings(
        connections=[{"id": "gw", "name": "GW", "base_url": "http://localhost:9/v1", "model": "m"}]
    )
    monkeypatch.setattr(config_mod, "settings", fake)

    result = await test_connection("gw")
    assert result["ok"] is False
    assert result["reachable"] is False
    assert "Could not connect" in result["error"]
    assert result["stored"] is None  # nothing learned, nothing stored


@pytest.mark.asyncio
async def test_connection_probe_needs_a_model(monkeypatch, stub_registry):
    from api.routes.config import test_connection
    from fastapi import HTTPException

    fake = _fake_settings(
        connections=[{"id": "gw", "name": "GW", "base_url": "http://localhost:4000/v1"}]
    )
    monkeypatch.setattr(config_mod, "settings", fake)

    with pytest.raises(HTTPException) as exc:
        await test_connection("gw")
    assert exc.value.status_code == 400


# ── GET /settings connections shape ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_settings_lists_connections_active_first(monkeypatch, stub_registry):
    from api.routes.config import get_settings

    fake = _fake_settings(adapter="zai")
    monkeypatch.setattr(config_mod, "settings", fake)

    result = await get_settings()
    ids = [c["id"] for c in result.connections]
    assert ids[0] == "zai"  # active first
    assert "ollama" in ids
    assert "bankofai" in ids
    zai = next(c for c in result.connections if c["id"] == "zai")
    assert zai["preset"] is True
    assert set(zai["capabilities"]) == {
        "streaming",
        "context_window",
        "vision",
        "tool_calling",
        "structured_output",
    }
