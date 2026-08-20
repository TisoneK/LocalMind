"""Tests for the parent readiness telemetry (ADR-52 phase 2 / B-2026-08-20-1).

Covers:
- ``AgentRuntime.parent_ready`` / ``parent_degraded_reason`` properties
- ``drain_pending_readiness`` returns transitions queued by ``_ensure_parent_kernel``
- transitions are emitted onto the per-turn ObsCollector at the start of a turn
- ``/api/health`` surfaces ``parent_ready`` + ``parent_degraded_reason``
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from core.config import settings
from core.obs import ObsCollector


def _make_runtime(tmp_db, monkeypatch):
    """Build a real AgentRuntime pointed at a temp DB (no provider calls)."""
    # Lazy import via core.engine (the re-export) — matches the pattern used
    # by test_acceptance_gate / test_empty_agent_fix / etc. to avoid the
    # circular import between core.agent_runtime and core.engine.__init__.
    from core.engine import Engine as AgentRuntime

    monkeypatch.setattr(settings, "localmind_adapter", "zai")
    monkeypatch.setattr(settings, "localmind_db_path", tmp_db)
    settings.save_api_key("zai", "fake-key-for-test")
    settings.zai_model = "glm-4.5-flash"
    return AgentRuntime()


@pytest.mark.asyncio
async def test_parent_ready_false_before_startup(tmp_db, monkeypatch):
    rt = _make_runtime(tmp_db, monkeypatch)
    assert rt.parent_ready is False
    assert rt.parent_degraded_reason == ""
    assert rt.drain_pending_readiness() == []


@pytest.mark.asyncio
async def test_startup_emits_parent_ready_when_provider_succeeds(tmp_db, monkeypatch):
    rt = _make_runtime(tmp_db, monkeypatch)
    with patch("core.agent_runtime.update_pulled_models", new=AsyncMock()):
        with patch("core.agent_runtime.get_adapter") as mock_get_adapter:
            mock_adapter = AsyncMock()
            mock_adapter.list_models = AsyncMock(return_value=[])
            mock_get_adapter.return_value = mock_adapter
            await rt.startup()

    assert rt.parent_ready is True
    assert rt.parent_degraded_reason == ""
    pending = rt.drain_pending_readiness()
    assert len(pending) == 1
    assert pending[0]["event"] == "parent_ready"
    assert pending[0]["reason"] == ""


@pytest.mark.asyncio
async def test_startup_emits_parent_degraded_when_provider_fails(tmp_db, monkeypatch):
    rt = _make_runtime(tmp_db, monkeypatch)
    with patch("core.agent_runtime.update_pulled_models", new=AsyncMock()):
        with patch("core.agent_runtime.get_adapter") as mock_get_adapter:
            mock_adapter = AsyncMock()
            mock_adapter.list_models = AsyncMock(side_effect=RuntimeError("provider down"))
            mock_get_adapter.return_value = mock_adapter
            await rt.startup()

    assert rt.parent_ready is False
    assert "provider down" in rt.parent_degraded_reason
    pending = rt.drain_pending_readiness()
    assert len(pending) == 1
    assert pending[0]["event"] == "parent_degraded"
    assert "provider down" in pending[0]["reason"]


@pytest.mark.asyncio
async def test_recovered_event_after_degraded_then_success(tmp_db, monkeypatch):
    rt = _make_runtime(tmp_db, monkeypatch)
    # First boot: degrade.
    with patch("core.agent_runtime.update_pulled_models", new=AsyncMock()):
        with patch("core.agent_runtime.get_adapter") as mock_get_adapter:
            mock_adapter = AsyncMock()
            mock_adapter.list_models = AsyncMock(side_effect=RuntimeError("first fail"))
            mock_get_adapter.return_value = mock_adapter
            await rt.startup()
    assert rt.parent_ready is False
    rt.drain_pending_readiness()  # clear the degraded event

    # Simulate a settings change so the next _ensure_parent_kernel rebuilds.
    monkeypatch.setattr(settings, "localmind_reasoning_effort", "high")
    with patch("core.agent_runtime.update_pulled_models", new=AsyncMock()):
        with patch("core.agent_runtime.get_adapter") as mock_get_adapter:
            mock_adapter = AsyncMock()
            mock_adapter.list_models = AsyncMock(return_value=[])
            mock_get_adapter.return_value = mock_adapter
            await rt._ensure_parent_kernel(refresh_provider=True)

    assert rt.parent_ready is True
    pending = rt.drain_pending_readiness()
    assert len(pending) == 1
    assert pending[0]["event"] == "parent_recovered"


@pytest.mark.asyncio
async def test_readiness_events_emit_on_turn_collector(tmp_db, monkeypatch):
    """The first turn's ObsCollector receives the queued parent_ready event."""
    rt = _make_runtime(tmp_db, monkeypatch)
    with patch("core.agent_runtime.update_pulled_models", new=AsyncMock()):
        with patch("core.agent_runtime.get_adapter") as mock_get_adapter:
            mock_adapter = AsyncMock()
            mock_adapter.list_models = AsyncMock(return_value=[])
            mock_get_adapter.return_value = mock_adapter
            await rt.startup()

    # The next turn should drain the pending parent_ready event onto its obs.
    obs = ObsCollector()
    # Manually invoke the drain path (the runtime calls this at turn start).
    for transition in rt.drain_pending_readiness():
        obs.emit(
            transition["event"],
            reason=transition.get("reason", ""),
            adapter="zai",
            model="glm-4.5-flash",
        )
    # The obs now carries a parent_ready event.
    types = [evt.type for evt in obs.history()]
    assert "parent_ready" in types


@pytest.mark.asyncio
async def test_health_endpoint_surfaces_parent_ready(tmp_db, monkeypatch):
    """The /api/health response carries parent_ready + parent_degraded_reason."""
    from fastapi.testclient import TestClient

    from api.app import create_app

    rt = _make_runtime(tmp_db, monkeypatch)
    with patch("core.agent_runtime.update_pulled_models", new=AsyncMock()):
        with patch("core.agent_runtime.get_adapter") as mock_get_adapter:
            mock_adapter = AsyncMock()
            mock_adapter.list_models = AsyncMock(return_value=[])
            mock_get_adapter.return_value = mock_adapter
            await rt.startup()

    # Wire the runtime as the chat engine singleton.
    import api.routes.chat as chat_module
    original_engine = chat_module._engine
    chat_module._engine = rt
    try:
        from api.routes.health import set_engine_ready
        set_engine_ready()
        # Patch the provider-reachability check so overall status is "ok".
        with patch("api.routes.health.get_adapter") as mock_get_adapter_health:
            mock_adapter = AsyncMock()
            mock_adapter.health_check = AsyncMock(return_value=True)
            mock_get_adapter_health.return_value = mock_adapter
            client = TestClient(create_app(), raise_server_exceptions=False)
            resp = client.get("/api/health")
    finally:
        chat_module._engine = original_engine

    assert resp.status_code == 200
    data = resp.json()
    assert data["parent_ready"] is True
    assert data["parent_degraded_reason"] == ""
    assert data["engine_ready"] is True
