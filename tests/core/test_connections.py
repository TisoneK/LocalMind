"""Tests for the AI-connections registry (core/connections.py).

A connection is the user-configurable shape in front of every model
endpoint: preset providers keep their historical ids and defaults, and
stored records in settings.json override preset fields or add custom
endpoints. These tests pin the merge semantics so a preset never breaks
and a custom connection always resolves.
"""

import pytest

from core.connections import (
    Connection,
    ConnectionCapabilities,
    ConnectionRegistry,
    is_valid_connection_id,
)


def test_seed_presets_cover_registry_and_ollama():
    from adapters.openai_compat import PROVIDER_CONFIGS

    registry = ConnectionRegistry(stored=[])
    ids = registry.ids()
    assert "ollama" in ids
    for key in PROVIDER_CONFIGS:
        assert key in ids
    assert len(ids) == len(PROVIDER_CONFIGS) + 1


def test_preset_connection_matches_registry_values():
    from adapters.openai_compat import PROVIDER_CONFIGS

    registry = ConnectionRegistry(stored=[])
    zai = registry.get("zai")
    cfg = PROVIDER_CONFIGS["zai"]
    assert zai is not None
    assert zai.preset is True
    assert zai.kind == "openai-compat"
    assert zai.base_url == cfg.base_url.rstrip("/")
    assert zai.model == ""  # empty = the preset's default/Settings field


def test_ollama_preset_is_local_kind():
    registry = ConnectionRegistry(stored=[])
    ollama = registry.get("ollama")
    assert ollama is not None
    assert ollama.kind == "ollama"
    assert ollama.preset is True


def test_stored_record_overrides_preset_fields():
    registry = ConnectionRegistry(
        stored=[{"id": "lite-llm", "name": "Atria via LiteLLM", "base_url": "http://localhost:4000/v1"}]
    )
    conn = registry.get("lite-llm")
    assert conn is not None
    assert conn.preset is True  # still a preset — only the fields changed
    assert conn.name == "Atria via LiteLLM"
    assert conn.base_url == "http://localhost:4000/v1"
    # Untouched fields keep the seed values.
    assert conn.kind == "openai-compat"
    assert conn.model == ""


def test_custom_connection_round_trip():
    stored = [
        {
            "id": "atria-proxy",
            "name": "Atria Local Proxy",
            "kind": "openai-compat",
            "base_url": "http://localhost:4000/v1",
            "model": "atria-dawn-preview",
            "protocol": "openai",
            "capabilities": {
                "streaming": True,
                "context_window": 131072,
                "vision": False,
                "tool_calling": True,
                "structured_output": False,
            },
            "enabled": True,
            "fallback_to": "zai",
        }
    ]
    registry = ConnectionRegistry(stored=stored)
    conn = registry.get("atria-proxy")
    assert conn is not None
    assert conn.preset is False
    assert conn.name == "Atria Local Proxy"
    assert conn.base_url == "http://localhost:4000/v1"
    assert conn.model == "atria-dawn-preview"
    assert conn.capabilities.context_window == 131072
    assert conn.fallback_to == "zai"
    assert conn.enabled is True
    # Custom ids sort after presets in the registry order.
    assert registry.ids()[-1] == "atria-proxy"


def test_capabilities_from_dict_validates_types():
    caps = ConnectionCapabilities.from_dict(
        {
            "streaming": False,
            "context_window": "65536",  # numeric strings coerce
            "vision": "yes",  # wrong type ignored
            "tool_calling": False,
            "structured_output": True,
            "unknown_key": "ignored",
        }
    )
    assert caps.streaming is False
    assert caps.context_window == 65536
    assert caps.vision is False  # default preserved
    assert caps.tool_calling is False
    assert caps.structured_output is True


def test_capabilities_from_dict_none_and_garbage():
    assert ConnectionCapabilities.from_dict(None).to_dict() == ConnectionCapabilities().to_dict()
    assert ConnectionCapabilities.from_dict("nonsense").streaming is True
    assert ConnectionCapabilities.from_dict({"context_window": "not-a-number"}).context_window == 0


def test_unknown_connection_returns_none():
    registry = ConnectionRegistry(stored=[])
    assert registry.get("nope") is None
    assert registry.get("") is None
    assert registry.get(None) is None


def test_connection_id_validation():
    assert is_valid_connection_id("atria-proxy")
    assert is_valid_connection_id("a")
    assert is_valid_connection_id("local-2")
    assert not is_valid_connection_id("Atria")  # uppercase
    assert not is_valid_connection_id("a--b")  # double dash
    assert not is_valid_connection_id("-lead")
    assert not is_valid_connection_id("trail-")
    assert not is_valid_connection_id("")
    assert not is_valid_connection_id("has space")
    assert not is_valid_connection_id("under_score")


def test_connection_to_dict_never_carries_preset_flag():
    conn = Connection(id="x", name="X", preset=False)
    assert "preset" not in conn.to_dict()


def test_registry_rebuilds_after_settings_change(monkeypatch):
    import core.config
    import core.connections

    class FakeSettings:
        _runtime_connections = []

    monkeypatch.setattr(core.connections, "_registry", None)
    monkeypatch.setattr(core.config, "settings", FakeSettings())
    first = core.connections.get_connection_registry()
    assert first.get("atria-proxy") is None

    FakeSettings._runtime_connections = [
        {"id": "atria-proxy", "name": "Atria", "base_url": "http://localhost:4000/v1", "model": "atria-dawn"}
    ]
    core.connections.invalidate_connection_registry()
    second = core.connections.get_connection_registry()
    assert second.get("atria-proxy") is not None
    assert second.get("atria-proxy").model == "atria-dawn"


def test_capability_defaults_are_the_historical_assumptions():
    caps = ConnectionCapabilities()
    assert caps.streaming is True
    assert caps.tool_calling is True
    assert caps.context_window == 0
    assert caps.vision is False
    assert caps.structured_output is False


@pytest.mark.asyncio
async def test_custom_connection_adapter_construction(monkeypatch):
    """get_adapter resolves a custom connection into an OpenAI-compat adapter."""
    import core.config
    from core.connections import ConnectionRegistry, invalidate_connection_registry

    class FakeSettings:
        _runtime_connections = [
            {
                "id": "atria-proxy",
                "name": "Atria Local Proxy",
                "kind": "openai-compat",
                "base_url": "http://localhost:4000/v1",
                "model": "atria-dawn-preview",
            }
        ]

        def get_api_key(self, provider):
            return None

    monkeypatch.setattr(core.config, "settings", FakeSettings())
    invalidate_connection_registry()

    from adapters import get_adapter

    adapter = get_adapter("atria-proxy")
    assert adapter._provider_key == "atria-proxy"
    assert adapter._provider_name == "Atria Local Proxy"
    assert adapter._base_url == "http://localhost:4000/v1"
    assert adapter._model == "atria-dawn-preview"
    # No key configured — a custom connection sends no Authorization header.
    assert "Authorization" not in adapter._headers
    await adapter.close()


def test_unknown_adapter_still_raises():
    from adapters import get_adapter

    with pytest.raises(ValueError, match="Unknown adapter"):
        get_adapter("definitely-not-a-provider")
