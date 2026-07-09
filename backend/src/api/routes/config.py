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
    valid_adapters = ["ollama", "openai", "anthropic", "openrouter", "deepseek", "lite-llm", "zen", "groq", "together", "fireworks", "deepinfra", "mistral", "cohere", "vercel", "cloudflare"]
    if req.adapter not in valid_adapters:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid adapter. Valid: {valid_adapters}"
        )

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
                    detail=f"API key not set for {info['name']}. Set it via the Settings UI or {info['key_env']} in .env."
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
        "message": f"Switched to {req.adapter}"
    }


@router.post("/settings/provider-key")
async def set_provider_key(req: ProviderKeyRequest):
    """
    Validate and store a provider API key at runtime.
    The key is saved to settings.json so it persists across restarts.
    """
    if req.provider not in PROVIDER_INFO:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider. Valid: {list(PROVIDER_INFO.keys())}"
        )

    info = PROVIDER_INFO[req.provider]

    # Save the API key to runtime storage
    settings.save_api_key(req.provider, req.api_key)

    return {
        "provider": req.provider,
        "name": info["name"],
        "validated": True,
        "message": f"API key saved for {info['name']}"
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
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider. Valid: {list(PROVIDER_INFO.keys())}"
        )

    info = PROVIDER_INFO[req.provider]
    removed = settings.delete_api_key(req.provider)

    return {
        "provider": req.provider,
        "name": info["name"],
        "deleted": removed,
        "message": f"API key removed for {info['name']}" if removed
                   else f"No API key was stored for {info['name']}",
    }
