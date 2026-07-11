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


PROVIDER_INFO = {
    # Core providers
    "openai": {
        "name": "OpenAI",
        "model_env": "OPENAI_MODEL",
        "key_env": "OPENAI_API_KEY",
        "default_model": "gpt-4o-mini",
    },
    "anthropic": {
        "name": "Anthropic",
        "model_env": "ANTHROPIC_MODEL",
        "key_env": "ANTHROPIC_API_KEY",
        "default_model": "claude-3-5-sonnet-20241022",
    },
    # Aggregators
    "openrouter": {
        "name": "OpenRouter",
        "model_env": "OPENROUTER_MODEL",
        "key_env": "OPENROUTER_API_KEY",
        "default_model": "openrouter/auto",
    },
    "zen": {
        "name": "Zen AI",
        "model_env": "ZEN_MODEL",
        "key_env": "ZEN_API_KEY",
        "default_model": "gpt-4o-mini",
    },
    # High-performance / infra
    "groq": {
        "name": "Groq",
        "model_env": "GROQ_MODEL",
        "key_env": "GROQ_API_KEY",
        "default_model": "llama-3.1-70b-versatile",
    },
    "together": {
        "name": "Together AI",
        "model_env": "TOGETHER_MODEL",
        "key_env": "TOGETHER_API_KEY",
        "default_model": "meta-llama/Llama-3.1-70B-Instruct-Turbo",
    },
    "fireworks": {
        "name": "Fireworks AI",
        "model_env": "FIREWORKS_MODEL",
        "key_env": "FIREWORKS_API_KEY",
        "default_model": "accounts/fireworks/models/llama-v3-70b-instruct",
    },
    "deepinfra": {
        "name": "DeepInfra",
        "model_env": "DEEPINFRA_MODEL",
        "key_env": "DEEPINFRA_API_KEY",
        "default_model": "meta-llama/Llama-3.1-70B-Instruct",
    },
    # Model-specific
    "deepseek": {
        "name": "DeepSeek",
        "model_env": "DEEPSEEK_MODEL",
        "key_env": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-chat",
    },
    "mistral": {
        "name": "Mistral AI",
        "model_env": "MISTRAL_MODEL",
        "key_env": "MISTRAL_API_KEY",
        "default_model": "mistral-large-latest",
    },
    "cohere": {
        "name": "Cohere",
        "model_env": "COHERE_MODEL",
        "key_env": "COHERE_API_KEY",
        "default_model": "command-r-plus",
    },
    # Gateways
    "vercel": {
        "name": "Vercel AI Gateway",
        "model_env": "VERCEL_MODEL",
        "key_env": "VERCEL_API_KEY",
        "default_model": "gpt-4o-mini",
    },
    "cloudflare": {
        "name": "Cloudflare AI Gateway",
        "model_env": "CLOUDFLARE_MODEL",
        "key_env": "CLOUDFLARE_API_KEY",
        "default_model": "@cf/meta/llama-3.1-70b-instruct",
    },
    # Free-tier-friendly providers (OpenAI-compatible, generous free quotas)
    "cerebras": {
        "name": "Cerebras",
        "model_env": "CEREBRAS_MODEL",
        "key_env": "CEREBRAS_API_KEY",
        # 1M tokens/day free, no credit card — most generous free tier.
        # llama-3.3-70b and qwen-3-32b were deprecated; gpt-oss-120b is the
        # current production model.
        "default_model": "gpt-oss-120b",
    },
    "sambanova": {
        "name": "SambaNova",
        "model_env": "SAMBANOVA_MODEL",
        "key_env": "SAMBANOVA_API_KEY",
        "default_model": "Meta-Llama-3.3-70B-Instruct",
    },
    "gemini": {
        "name": "Google Gemini",
        "model_env": "GEMINI_MODEL",
        "key_env": "GEMINI_API_KEY",
        # Google AI Studio free tier — gemini-2.5-flash ~10 req/min
        "default_model": "gemini-2.5-flash",
    },
    "chutes": {
        "name": "Chutes AI",
        "model_env": "CHUTES_MODEL",
        "key_env": "CHUTES_API_KEY",
        # All Chutes models are TEE-suffixed; deepseek-v3.2 is a solid default.
        # See https://llm.chutes.ai/v1/models for the live list.
        "default_model": "deepseek-ai/DeepSeek-V3.2-TEE",
    },
    "zai": {
        "name": "Z.ai (GLM)",
        "model_env": "ZAI_MODEL",
        "key_env": "ZAI_API_KEY",
        # Free tier: GLM-5.2, GLM-5.1, GLM-5, GLM-5-Turbo, GLM-4.7 (limited-time
        # free) + GLM-4.5-Flash (always free). Get a key at z.ai/manage-apikey/billing
        "default_model": "glm-4.5-flash",
    },
    # Local
    "lite-llm": {
        "name": "LiteLLM",
        "model_env": "LITELLM_MODEL",
        "key_env": "LITELLM_API_KEY",
        "default_model": "gpt-4",
    },
}


@router.get("/settings", response_model=SettingsResponse)
async def get_settings():
    """
    Get current adapter and model configuration.
    """
    adapter = settings.localmind_adapter

    # Get current model based on adapter
    model_setting_map = {
        "openai": settings.openai_model,
        "anthropic": settings.anthropic_model,
        "openrouter": settings.openrouter_model,
        "deepseek": settings.deepseek_model,
        "lite-llm": settings.litellm_model,
        "zen": settings.zen_model,
        "groq": settings.groq_model,
        "together": settings.together_model,
        "fireworks": settings.fireworks_model,
        "deepinfra": settings.deepinfra_model,
        "mistral": settings.mistral_model,
        "cohere": settings.cohere_model,
        "vercel": settings.vercel_model,
        "cloudflare": settings.cloudflare_model,
        "cerebras": settings.cerebras_model,
        "sambanova": settings.sambanova_model,
        "gemini": settings.gemini_model,
        "chutes": settings.chutes_model,
        "zai": settings.zai_model,
    }
    current_model = model_setting_map.get(adapter) or settings.ollama_model
    embed_model = settings.ollama_embed_model

    # Build provider info (whether API key is set)
    # Check both runtime-stored keys (settings.json) and env vars.
    providers = {}
    for prov, info in PROVIDER_INFO.items():
        runtime_key = settings.get_api_key(prov)
        env_key = os.getenv(info["key_env"], "")
        key_set = bool(runtime_key or env_key)
        model_env = info["model_env"]
        model_value = getattr(settings, model_env.lower(), "") or info["default_model"]
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
    valid_adapters = [
        "ollama",
        "openai",
        "anthropic",
        "openrouter",
        "deepseek",
        "lite-llm",
        "zen",
        "groq",
        "together",
        "fireworks",
        "deepinfra",
        "mistral",
        "cohere",
        "vercel",
        "cloudflare",
        "cerebras",
        "sambanova",
        "gemini",
        "chutes",
        "zai",
    ]
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
                    detail=f"API key not set for {info['name']}. Set it via the Settings UI or {info['key_env']} in .env.",
                )

    settings.localmind_adapter = req.adapter
    # Clear adapter cache so new adapter is used for next request
    clear_adapter_cache()

    # Resolve the model for this adapter: use the provided model, or fall
    # back to the adapter's current model setting, or the provider default.
    # Previously, calling set_adapter without a model saved model="" to
    # settings.json, wiping any previously-saved model on restart.
    model_field_map = {
        "ollama": "ollama_model",
        "openai": "openai_model",
        "anthropic": "anthropic_model",
        "openrouter": "openrouter_model",
        "deepseek": "deepseek_model",
        "lite-llm": "litellm_model",
        "zen": "zen_model",
        "groq": "groq_model",
        "together": "together_model",
        "fireworks": "fireworks_model",
        "deepinfra": "deepinfra_model",
        "mistral": "mistral_model",
        "cohere": "cohere_model",
        "vercel": "vercel_model",
        "cloudflare": "cloudflare_model",
        "cerebras": "cerebras_model",
        "sambanova": "sambanova_model",
        "gemini": "gemini_model",
        "chutes": "chutes_model",
        "zai": "zai_model",
    }
    model_field = model_field_map.get(req.adapter)
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
    # on the next request.
    if req.model:
        model_field = f"{req.provider.replace('-', '')}_model"
        if hasattr(settings, model_field):
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
            validation_error = "Key saved, but the provider did not respond to a health check. The key may be invalid, the provider may be down, or your network may be blocking the request."
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
