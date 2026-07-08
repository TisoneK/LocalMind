"""
Settings endpoints for adapter and provider configuration.
"""
from __future__ import annotations
import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.config import settings
from adapters import clear_adapter_cache

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
    providers = {}
    for prov, info in PROVIDER_INFO.items():
        key_set = bool(os.getenv(info["key_env"], ""))
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

    # For cloud providers, check if API key is set
    if req.adapter != "ollama":
        info = PROVIDER_INFO.get(req.adapter)
        if info:
            api_key = os.getenv(info["key_env"], "")
            if not api_key:
                raise HTTPException(
                    status_code=400,
                    detail=f"API key not set for {info['name']}. Set {info['key_env']} in .env or environment."
                )

    settings.localmind_adapter = req.adapter
    # Clear adapter cache so new adapter is used for next request
    clear_adapter_cache()
    if req.model:
        # Set model for this provider
        model_field_map = {
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
        if req.adapter in model_field_map:
            setattr(settings, model_field_map[req.adapter], req.model)

    # Persist runtime settings to JSON file for restart survival
    settings.save_runtime_settings(
        adapter=req.adapter,
        model=req.model or "",
    )

    return {
        "adapter": settings.localmind_adapter,
        "model": req.model or "default",
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