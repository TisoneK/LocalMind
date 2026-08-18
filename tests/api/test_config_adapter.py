"""Regression tests for POST /settings/adapter model resolution.

The bug (user-reported, Mac/Windows discrepancy): switching the provider in
the Settings UI did NOT switch the model. Adding a Cerebras key while on
Gemini — then selecting a provider without also picking a model — left the
previous provider's model stranded under the new adapter (adapter=gemini +
model=gpt-oss-120b, a Cerebras model), which then hit Gemini's free-tier
limit. Root cause: an empty resolved_model is PRESERVED by
save_runtime_settings, so the top-level model kept its old value. Fix: fall
through to the new provider's default_model so a switch always lands on a
valid model for that provider.
"""

import types

import pytest

from api.routes import config as config_mod
from api.routes.config import PROVIDER_INFO, AdapterConfig, set_adapter


def _fake_settings(**model_fields):
    saved = {}

    def save_runtime_settings(**kwargs):
        # Mirror the real contract: a non-empty kwarg overwrites; an empty one
        # is preserved (i.e. the OLD value survives). We record what was asked.
        saved.update(kwargs)

    ns = types.SimpleNamespace(
        localmind_adapter="cerebras",
        get_api_key=lambda provider: "fake-key",  # always keyed → no 400
        save_runtime_settings=save_runtime_settings,
        _saved=saved,
        **model_fields,
    )
    return ns


# ── Reasoning thinking policy (ADR-41, POST /api/settings/thinking) ──────


def _fake_settings_for_thinking():
    """SimpleNamespace fake with the fields GET /settings/thinking touch."""
    saved = {}

    def save_runtime_settings(**kwargs):
        saved.update(kwargs)

    return types.SimpleNamespace(
        localmind_adapter="zai",
        localmind_thinking="enabled",
        localmind_reasoning_timeout_secs=180.0,
        localmind_reasoning_plan_timeout_secs=30.0,
        localmind_reasoning_max_wall_clock_secs=360.0,
        localmind_reasoning_effort="",
        ollama_model="",
        ollama_embed_model="",
        get_api_key=lambda provider: "fake-key",
        save_runtime_settings=save_runtime_settings,
        _saved=saved,
    )


@pytest.mark.asyncio
async def test_set_thinking_settings_applies_and_persists(monkeypatch):
    from api.routes.config import ThinkingSettingsRequest, set_thinking_settings

    fake = _fake_settings_for_thinking()
    monkeypatch.setattr(config_mod, "settings", fake)
    monkeypatch.setattr(config_mod, "clear_adapter_cache", lambda: None)

    result = await set_thinking_settings(
        ThinkingSettingsRequest(
            thinking="disabled",
            reasoning_timeout=300,
            reasoning_plan_timeout=60,
            reasoning_max_wall_clock=600,
            reasoning_effort="high",
        )
    )

    assert fake.localmind_thinking == "disabled"
    assert fake.localmind_reasoning_timeout_secs == 300.0
    assert fake.localmind_reasoning_plan_timeout_secs == 60.0
    assert fake.localmind_reasoning_max_wall_clock_secs == 600.0
    assert fake.localmind_reasoning_effort == "high"
    assert fake._saved["thinking"] == "disabled"
    assert fake._saved["reasoning_timeout"] == 300.0
    assert result["thinking"] == "disabled"


@pytest.mark.asyncio
async def test_set_thinking_settings_partial_update_only_applies_given_fields(monkeypatch):
    from api.routes.config import ThinkingSettingsRequest, set_thinking_settings

    fake = _fake_settings_for_thinking()
    monkeypatch.setattr(config_mod, "settings", fake)
    monkeypatch.setattr(config_mod, "clear_adapter_cache", lambda: None)

    await set_thinking_settings(ThinkingSettingsRequest(thinking="enabled"))
    # Untouched fields keep their values.
    assert fake.localmind_reasoning_timeout_secs == 180.0
    assert fake.localmind_reasoning_plan_timeout_secs == 30.0
    assert fake.localmind_reasoning_effort == ""


@pytest.mark.asyncio
async def test_set_thinking_settings_rejects_bad_values(monkeypatch):
    from fastapi import HTTPException

    from api.routes.config import ThinkingSettingsRequest, set_thinking_settings

    fake = _fake_settings_for_thinking()
    monkeypatch.setattr(config_mod, "settings", fake)
    monkeypatch.setattr(config_mod, "clear_adapter_cache", lambda: None)

    with pytest.raises(HTTPException) as bad_thinking:
        await set_thinking_settings(ThinkingSettingsRequest(thinking="maybe"))
    assert bad_thinking.value.status_code == 400

    with pytest.raises(HTTPException) as bad_timeout:
        await set_thinking_settings(ThinkingSettingsRequest(reasoning_timeout=10))
    assert bad_timeout.value.status_code == 400

    with pytest.raises(HTTPException) as bad_plan:
        await set_thinking_settings(ThinkingSettingsRequest(reasoning_plan_timeout=2))
    assert bad_plan.value.status_code == 400

    with pytest.raises(HTTPException) as bad_wall:
        await set_thinking_settings(ThinkingSettingsRequest(reasoning_max_wall_clock=60))
    assert bad_wall.value.status_code == 400


@pytest.mark.asyncio
async def test_switch_provider_without_saved_model_uses_new_provider_default(monkeypatch):
    # On cerebras with its model; gemini has NO saved model (the bug trigger).
    fake = _fake_settings(cerebras_model="gpt-oss-120b", gemini_model="")
    monkeypatch.setattr(config_mod, "settings", fake)
    monkeypatch.setattr(config_mod, "clear_adapter_cache", lambda: None)

    result = await set_adapter(AdapterConfig(adapter="gemini"))

    gemini_default = PROVIDER_INFO["gemini"]["default_model"]
    assert result["model"] == gemini_default
    # It must NOT strand the Cerebras model under the Gemini adapter.
    assert result["model"] != "gpt-oss-120b"
    # And the persisted top-level model is the gemini default, not empty.
    assert fake._saved["adapter"] == "gemini"
    assert fake._saved["model"] == gemini_default


@pytest.mark.asyncio
async def test_explicit_model_wins_over_default(monkeypatch):
    fake = _fake_settings(gemini_model="")
    monkeypatch.setattr(config_mod, "settings", fake)
    monkeypatch.setattr(config_mod, "clear_adapter_cache", lambda: None)

    result = await set_adapter(AdapterConfig(adapter="gemini", model="gemini-2.5-flash"))
    assert result["model"] == "gemini-2.5-flash"


@pytest.mark.asyncio
async def test_saved_provider_model_is_kept(monkeypatch):
    # A provider that already has its own saved model keeps it (no reset).
    fake = _fake_settings(cerebras_model="gpt-oss-120b")
    monkeypatch.setattr(config_mod, "settings", fake)
    monkeypatch.setattr(config_mod, "clear_adapter_cache", lambda: None)

    result = await set_adapter(AdapterConfig(adapter="cerebras"))
    assert result["model"] == "gpt-oss-120b"


# ── Session 292: dedicated ollama_model key + shell_enabled persistence ──────
# Bug D/E: the Ollama model was routed through the ambiguous generic `model`
# key. A stale cloud model left in `model` after switching provider→ollama
# loaded as ollama_model (D), and select_model never persisted the Ollama
# model (E). Fix: a dedicated ollama_model key, cloud-only generic `model`.

import json as _json
from core.config import Settings


def _settings_at(tmp_path, data: dict) -> Settings:
    p = tmp_path / "settings.json"
    p.write_text(_json.dumps(data), encoding="utf-8")
    s = Settings()
    s._runtime_settings_path = lambda: p  # type: ignore[method-assign]
    s.ollama_model = ""  # known baseline
    s.load_runtime_settings()
    return s


def test_stale_cloud_model_does_not_load_as_ollama_model(tmp_path):
    # The exact D scenario: adapter=ollama but a leftover cloud model in `model`.
    s = _settings_at(tmp_path, {"adapter": "ollama", "model": "deepseek-v4-flash-free"})
    assert s.ollama_model == ""  # NOT deepseek — the cloud model is ignored for ollama
    assert s.localmind_adapter == "ollama"


def test_dedicated_ollama_model_key_persists(tmp_path):
    # The E scenario: a saved ollama_model survives a restart (load).
    s = _settings_at(tmp_path, {"adapter": "ollama", "ollama_model": "phi4-mini:latest"})
    assert s.ollama_model == "phi4-mini:latest"


def test_cloud_model_still_loads_for_cloud_adapter(tmp_path):
    # Regression guard: the generic `model` key still works for cloud adapters.
    s = _settings_at(tmp_path, {"adapter": "zen", "model": "deepseek-v4-flash-free"})
    assert s.zen_model == "deepseek-v4-flash-free"


def test_shell_enabled_persists_both_ways(tmp_path):
    assert _settings_at(tmp_path, {"shell_enabled": True}).localmind_shell_enabled is True
    assert _settings_at(tmp_path, {"shell_enabled": False}).localmind_shell_enabled is False
