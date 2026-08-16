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
from api.routes.config import AdapterConfig, PROVIDER_INFO, set_adapter


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
