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
    # ADR-41 (Session 254): reasoning-model thinking policy (z.ai/GLM).
    # Mirrored to the Settings UI so users can tune thinking without env vars.
    thinking: str = "enabled"
    reasoning_timeout: float = 180.0
    reasoning_plan_timeout: float = 30.0
    reasoning_effort: str = ""


class AdapterConfig(BaseModel):
    adapter: str
    model: Optional[str] = None


class ThinkingSettingsRequest(BaseModel):
    """Body for POST /api/settings/thinking (ADR-41 reasoning policy).

    All fields optional so a partial update is safe: only provided fields
    are applied and persisted. reasoning_effort="" clears the effort.
    """

    thinking: Optional[str] = None  # "enabled" | "disabled"
    reasoning_timeout: Optional[float] = None  # per-call seconds when thinking
    reasoning_plan_timeout: Optional[float] = None  # plan/init/orchestrator s
    reasoning_effort: Optional[str] = None  # GLM-5.2+ effort level


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
        thinking=settings.localmind_thinking,
        reasoning_timeout=settings.localmind_reasoning_timeout_secs,
        reasoning_plan_timeout=settings.localmind_reasoning_plan_timeout_secs,
        reasoning_effort=settings.localmind_reasoning_effort,
    )


@router.post("/settings/thinking")
async def set_thinking_settings(req: ThinkingSettingsRequest):
    """
    Update the reasoning-model thinking policy (ADR-41) and persist it to
    settings.json so it survives restarts.

    Applies only the fields the client actually sends. The adapter reads
    these from the Settings singleton on every call, and load_runtime_settings
    applies settings.json after pydantic folds the env in — so a UI setting
    wins over LOCALMIND_THINKING / LOCALMIND_REASONING_* env vars.
    """
    if req.thinking is not None:
        if req.thinking not in ("enabled", "disabled"):
            raise HTTPException(status_code=400, detail="thinking must be 'enabled' or 'disabled'")
        settings.localmind_thinking = req.thinking
    if req.reasoning_timeout is not None:
        if req.reasoning_timeout < 45:
            raise HTTPException(status_code=400, detail="reasoning_timeout must be >= 45 seconds")
        settings.localmind_reasoning_timeout_secs = float(req.reasoning_timeout)
    if req.reasoning_plan_timeout is not None:
        if req.reasoning_plan_timeout < 8:
            raise HTTPException(status_code=400, detail="reasoning_plan_timeout must be >= 8 seconds")
        settings.localmind_reasoning_plan_timeout_secs = float(req.reasoning_plan_timeout)
    if req.reasoning_effort is not None:
        settings.localmind_reasoning_effort = req.reasoning_effort.strip().lower()

    settings.save_runtime_settings(
        thinking=settings.localmind_thinking,
        reasoning_timeout=settings.localmind_reasoning_timeout_secs,
        reasoning_plan_timeout=settings.localmind_reasoning_plan_timeout_secs,
        reasoning_effort=settings.localmind_reasoning_effort,
    )
    # save_runtime_settings PRESERVES empty values (so a partial update can't
    # clobber a saved model), which means an explicitly-cleared effort would
    # linger in settings.json and reappear on restart. Remove the key directly
    # when the user clears it. Guarded on an explicit empty request so partial
    # updates (effort untouched) never touch the file.
    if req.reasoning_effort is not None and not settings.localmind_reasoning_effort:
        try:
            _path = settings._runtime_settings_path()
            _data = settings._load_json_file(_path)
            if "reasoning_effort" in _data:
                _data.pop("reasoning_effort")
                settings._secure_write_json(_path, _data)
        except Exception:
            pass  # best-effort cleanup; the live value is already correct
    # The adapter caches provider params; rebuild so the new policy applies
    # to the next call without a restart.
    clear_adapter_cache()

    return {
        "thinking": settings.localmind_thinking,
        "reasoning_timeout": settings.localmind_reasoning_timeout_secs,
        "reasoning_plan_timeout": settings.localmind_reasoning_plan_timeout_secs,
        "reasoning_effort": settings.localmind_reasoning_effort,
        "message": f"Reasoning thinking {'enabled' if settings.localmind_thinking != 'disabled' else 'disabled'}",
    }


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
        # Resolve the model in priority order: the explicitly requested model,
        # then THIS provider's own saved model, then THIS provider's DEFAULT.
        # The default fallback is load-bearing: switching provider without a
        # model used to leave resolved_model="" when the new provider had no
        # saved model, and save_runtime_settings PRESERVES an empty kwarg — so
        # the top-level model kept the PREVIOUS provider's value (e.g. a
        # Cerebras "gpt-oss-120b" stranded under the Gemini adapter, which then
        # hit Gemini's free-tier limit). Falling through to the provider
        # default makes an adapter switch always land on a valid model.
        resolved_model = (
            req.model
            or getattr(settings, model_field, "")
            or PROVIDER_INFO.get(req.adapter, {}).get("default_model", "")
        )
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
