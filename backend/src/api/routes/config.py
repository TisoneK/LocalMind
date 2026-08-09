"""
Settings endpoints for adapter and provider configuration.
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from adapters import clear_adapter_cache
from core.config import settings

router = APIRouter()


class SettingsResponse(BaseModel):
    adapter: str
    model: str
    embed_model: Optional[str] = None  # Ollama embedding model (always local)
    providers: dict


class AdapterConfig(BaseModel):
    adapter: str
    model: Optional[str] = None


class ProviderKeyRequest(BaseModel):
    provider: str
    api_key: str
    model: Optional[str] = None


# Provider info is derived from the single source of truth in
# PROVIDER_CONFIGS (adapters/openai_compat.py). Adding a new provider
# there automatically makes it available everywhere — no need to update
# this file.
from adapters.openai_compat import PROVIDER_CONFIGS

PROVIDER_INFO: dict[str, dict] = {
    key: {
        "name": cfg.display_name,
        "model_env": cfg.model_env,
        "key_env": cfg.key_env,
        "default_model": cfg.default_model,
    }
    for key, cfg in PROVIDER_CONFIGS.items()
}

# Valid adapter names for validation (ollama + all cloud providers)
VALID_ADAPTERS: list[str] = ["ollama"] + list(PROVIDER_CONFIGS.keys())

# Map: adapter key → settings field name (derived, not hardcoded)
ADAPTER_MODEL_FIELDS: dict[str, str] = {
    "ollama": "ollama_model",
    **{key: cfg.settings_field for key, cfg in PROVIDER_CONFIGS.items()},
}


@router.get("/settings", response_model=SettingsResponse)
async def get_settings():
    """
    Get current adapter and model configuration.
    """
    adapter = settings.localmind_adapter

    # Derive the model-setting map from ADAPTER_MODEL_FIELDS (single source
    # of truth in PROVIDER_CONFIGS). No hardcoded provider list.
    model_setting_map = {
        key: getattr(settings, field, "")
        for key, field in ADAPTER_MODEL_FIELDS.items()
    }
    current_model = model_setting_map.get(adapter) or settings.ollama_model
    embed_model = settings.ollama_embed_model

    # Build provider info (whether API key is set)
    # Check both runtime-stored keys (settings.json) and env vars.
    # The settings field name comes from ADAPTER_MODEL_FIELDS (derived from
    # PROVIDER_CONFIGS) — don't reconstruct it from model_env, which couples
    # this code to the env-var-naming convention and breaks if they ever diverge.
    providers = {}
    for prov, info in PROVIDER_INFO.items():
        runtime_key = settings.get_api_key(prov)
        env_key = os.getenv(info["key_env"], "")
        key_set = bool(runtime_key or env_key)
        settings_field = ADAPTER_MODEL_FIELDS.get(prov, "")
        model_value = (getattr(settings, settings_field, "") if settings_field else "") or info["default_model"]
        providers[prov] = {
            "name": info["name"],
            "api_key_set": key_set,
            "model": model_value,
            "default_model": info["default_model"],
        }

    return SettingsResponse(
        adapter=adapter,
        model=current_model,
        embed_model=embed_model,
        providers=providers,
    )


@router.post("/settings/adapter")
async def set_adapter(req: AdapterConfig):
    """
    Switch to a different adapter (ollama, openai, anthropic, etc.).
    """
    valid_adapters = VALID_ADAPTERS
    if req.adapter not in valid_adapters:
        raise HTTPException(status_code=400, detail=f"Invalid adapter. Valid: {valid_adapters}")

    # For cloud providers, check if an API key is available.
    # Check both runtime-stored keys (settings.json) and env vars.
    if req.adapter != "ollama":
        info = PROVIDER_INFO.get(req.adapter)
        if info:
            runtime_key = settings.get_api_key(req.adapter)
            env_key = os.getenv(info["key_env"], "")
            if not (runtime_key or env_key):
                raise HTTPException(
                    status_code=400,
                    detail=f"API key not set for {info['name']}. Set it via the Settings UI or {info['key_env']} in .env.",  # noqa: E501
                )

    settings.localmind_adapter = req.adapter
    # Clear adapter cache so new adapter is used for next request
    clear_adapter_cache()

    # Resolve the model for this adapter: use the provided model, or fall
    # back to the adapter's current model setting, or the provider default.
    # Previously, calling set_adapter without a model saved model="" to
    # settings.json, wiping any previously-saved model on restart.
    # model_field is derived from ADAPTER_MODEL_FIELDS (single source of truth).
    model_field = ADAPTER_MODEL_FIELDS.get(req.adapter)
    if model_field:
        # Use provided model, or keep the existing model if no model given
        resolved_model = req.model or getattr(settings, model_field, "")
        if resolved_model:
            setattr(settings, model_field, resolved_model)
    else:
        resolved_model = req.model or ""

    # Persist runtime settings to JSON file for restart survival.
    # save_runtime_settings preserves existing values when a kwarg is empty,
    # so passing model="" won't wipe a previously-saved model.
    settings.save_runtime_settings(
        adapter=req.adapter,
        model=resolved_model,
    )

    return {
        "adapter": settings.localmind_adapter,
        "model": resolved_model or "default",
        "message": f"Switched to {req.adapter}",
    }


@router.post("/settings/provider-key")
async def set_provider_key(req: ProviderKeyRequest):
    """
    Validate and store a provider API key at runtime.
    The key is saved to settings.json so it persists across restarts.

    After saving, a lightweight health check is run against the provider
    so the user gets immediate feedback if the key is invalid (typo,
    wrong account, expired). The key is saved regardless of the health
    check result — the user may be offline, or the provider may be
    temporarily unreachable. The `validated` field reflects the health
    check outcome.
    """
    if req.provider not in PROVIDER_INFO:
        raise HTTPException(status_code=400, detail=f"Unknown provider. Valid: {list(PROVIDER_INFO.keys())}")

    info = PROVIDER_INFO[req.provider]

    # Save the API key to runtime storage first — we want it persisted
    # even if the health check fails (user may be offline).
    settings.save_api_key(req.provider, req.api_key)

    # If a model was provided, persist it too so the adapter uses it
    # on the next request. The settings field name comes from the derived
    # ADAPTER_MODEL_FIELDS map (single source of truth in PROVIDER_CONFIGS),
    # not from reconstructing it via string manipulation.
    if req.model:
        model_field = ADAPTER_MODEL_FIELDS.get(req.provider, "")
        if model_field and hasattr(settings, model_field):
            setattr(settings, model_field, req.model)
            settings.save_runtime_settings(adapter=req.provider, model=req.model)

    # Run a health check against the provider to validate the key.
    # This is best-effort: a False result doesn't unsave the key.
    validated = False
    validation_error: str | None = None
    try:
        from adapters import clear_adapter_cache, get_adapter

        # Clear the cache so the new key is picked up (the cached adapter
        # may have been constructed with the old key or none at all).
        clear_adapter_cache(req.provider)
        adapter = get_adapter(req.provider)
        validated = await adapter.health_check()
        if not validated:
            validation_error = "Key saved, but the provider did not respond to a health check. The key may be invalid, the provider may be down, or your network may be blocking the request."  # noqa: E501
        # Close the adapter's HTTP client to avoid leaking connections.
        if hasattr(adapter, "close"):
            await adapter.close()
    except Exception as exc:
        # Adapter construction can raise ValueError if the key is empty
        # or the provider is misconfigured. Surface that as a validation
        # failure rather than a 500.
        validation_error = f"Key saved, but validation failed: {exc}"

    # Clear the cache again so the next chat request builds a fresh
    # adapter with the validated key.
    clear_adapter_cache(req.provider)

    return {
        "provider": req.provider,
        "name": info["name"],
        "validated": validated,
        "validation_error": validation_error,
        "message": (
            f"API key saved for {info['name']}."
            if validated
            else f"API key saved for {info['name']}, but validation failed."
        ),
    }


class DeleteProviderKeyRequest(BaseModel):
    provider: str


@router.delete("/settings/provider-key")
async def delete_provider_key(req: DeleteProviderKeyRequest):
    """
    Delete a stored provider API key.

    Previously, once a key was saved via POST /settings/provider-key, there
    was no way to revoke it without manually editing settings.json. This
    endpoint allows the frontend to remove a key cleanly.
    """
    if req.provider not in PROVIDER_INFO:
        raise HTTPException(status_code=400, detail=f"Unknown provider. Valid: {list(PROVIDER_INFO.keys())}")

    info = PROVIDER_INFO[req.provider]
    removed = settings.delete_api_key(req.provider)

    return {
        "provider": req.provider,
        "name": info["name"],
        "deleted": removed,
        "message": f"API key removed for {info['name']}" if removed else f"No API key was stored for {info['name']}",
    }
