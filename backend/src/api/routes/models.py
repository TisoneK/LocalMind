"""Model listing and selection endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from adapters import clear_adapter_cache, get_adapter
from core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

# Human-readable profiles shown in the UI (Ollama only)
OLLAMA_MODEL_PROFILES = {
    "llama3.2:3b": {"label": "Fast & Light", "best_for": "Chat, Q&A, quick tasks", "min_ram_gb": 4},
    "llama3.1:8b": {
        "label": "Balanced",
        "best_for": "General use, long documents",
        "min_ram_gb": 6,
    },
    "qwen2.5-coder:7b": {
        "label": "Best for Code",
        "best_for": "Code generation and review",
        "min_ram_gb": 6,
    },
    "deepseek-coder-v2:16b": {
        "label": "High Quality Code",
        "best_for": "Complex code, large codebases",
        "min_ram_gb": 12,
    },
    "mistral:7b": {
        "label": "Writing Focused",
        "best_for": "Reports, summaries, drafting",
        "min_ram_gb": 6,
    },
    "gemma2:9b": {
        "label": "Reasoning",
        "best_for": "Analysis, step-by-step reasoning",
        "min_ram_gb": 8,
    },
}


class ModelInfo(BaseModel):
    name: str
    label: str
    best_for: str
    min_ram_gb: int
    available: bool
    active: bool


class SelectModelRequest(BaseModel):
    model: str


class SelectModelResponse(BaseModel):
    selected: str
    message: str


@router.get("/models")
async def list_models():
    """
    List available models based on the configured adapter.
    Returns {models: ModelOption[], current: string, provider: string}
    """
    adapter_name = settings.localmind_adapter

    # Get adapter - but don't create new instance, just get the class
    try:
        adapter = get_adapter(adapter_name)
        available = await adapter.list_models()
        if adapter_name == "ollama":
            available = set(available)
    except Exception:
        available = []

    model_options = []
    current_model = ""

    if adapter_name == "ollama":
        # Ollama: show pulled models with profiles
        for model_name, profile in OLLAMA_MODEL_PROFILES.items():
            is_available = model_name in available or any(a.startswith(model_name.split(":")[0]) for a in available)
            if is_available:
                model_options.append(
                    {
                        "id": model_name,
                        "name": profile["label"],
                        "provider": "ollama",
                        "size": f"{profile['min_ram_gb']}GB RAM",
                    }
                )
        # Include pulled models not in profiles
        for name in available:
            if not any(m["id"] == name for m in model_options):
                model_options.append({"id": name, "name": name, "provider": "ollama", "size": "Unknown"})
        current_model = settings.ollama_model
    else:
        # Cloud providers: show configured model (can't list, can only configure)

        # Get model from settings or use adapter default
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
        }
        current_model = model_setting_map.get(adapter_name, "")

        # Providers that expose a working OpenAI-compatible /models endpoint
        # can be queried live so the model selector shows the full current list.
        # Zen: opencode.ai/zen/v1/models
        # Cerebras: api.cerebras.ai/v1/models (gpt-oss-120b, gemma-4-31b, zai-glm-4.7)
        # Gemini: generativelanguage.googleapis.com/v1beta/openai/models
        # Chutes: llm.chutes.ai/v1/models (all TEE-suffixed)
        if adapter_name in ("zen", "cerebras", "gemini", "chutes"):
            try:
                available = await adapter.list_models()
                model_options.extend(
                    [{"id": m, "name": m, "provider": adapter_name, "size": "Cloud"} for m in available]
                )
            except Exception as exc:
                logger.warning("[models] failed to list models for %s: %s", adapter_name, exc)

        # Zen-specific default when no model is configured
        if adapter_name == "zen" and not current_model:
            current_model = "minimax-m2.5-free"

        # For cloud providers without a listable /models endpoint (DeepSeek,
        # OpenAI, etc.), include the current model so the UI can display it.
        # Otherwise the model selector shows an empty list and the sidebar
        # falls back to a hardcoded name.
        if not model_options and current_model:
            model_options.append(
                {
                    "id": current_model,
                    "name": current_model,
                    "provider": adapter_name,
                    "size": "Cloud",
                }
            )

    return {"models": model_options, "current": current_model, "provider": adapter_name}


# Debug endpoint to check settings state
@router.get("/models/debug")
async def debug_models():
    """Debug endpoint showing raw settings values for adapter/model diagnosis."""
    return {
        "localmind_adapter": settings.localmind_adapter,
        "ollama_model": settings.ollama_model,
        "zen_model": settings.zen_model,
        "ollama_ready": settings.ollama_ready,
        "is_ollama_configured": settings.is_ollama_configured(),
        "runtime_settings_path": str(settings._runtime_settings_path()),
        "runtime_settings_exists": settings._runtime_settings_path().exists(),
    }


@router.post("/models/select", response_model=SelectModelResponse)
async def select_model(req: SelectModelRequest):
    """
    Hot-swap the active model at runtime without restarting.
    Validates that the model is actually pulled before switching (Ollama only).
    """
    if not req.model or not req.model.strip():
        raise HTTPException(status_code=400, detail="model name cannot be empty")

    adapter_name = settings.localmind_adapter
    model = req.model.strip()

    if adapter_name == "ollama":
        # Verify the model exists in Ollama before switching.
        # Use get_adapter() (consistent with list_models above) instead of
        # constructing OllamaAdapter() directly — OllamaAdapter was never
        # imported in this module, which would raise NameError at runtime.
        try:
            adapter = get_adapter("ollama")
            available = set(await adapter.list_models())
        except Exception:
            available = set()

        # Accept exact match or prefix match (e.g. "llama3.1" for "llama3.1:8b")
        model_available = model in available or any(a.startswith(model.split(":")[0]) for a in available)

        if not model_available and available:
            raise HTTPException(status_code=404, detail=f"Model '{model}' is not pulled. Run: ollama pull {model}")

        # Mutate settings in-place — all subsequent Engine instances read from settings
        settings.ollama_model = model
        clear_adapter_cache("ollama")
    else:
        # Cloud providers: update the appropriate setting
        model_setting_map = {
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
        }
        setting_key = model_setting_map.get(adapter_name)
        if setting_key:
            setattr(settings, setting_key, model)
        clear_adapter_cache(adapter_name)

        # Persist the model selection to settings.json so it survives
        # restarts. Previously the model was only set in-memory and lost
        # on restart.
        settings.save_runtime_settings(
            adapter=adapter_name,
            model=model,
        )

    return SelectModelResponse(
        selected=model,
        message=f"Active model switched to {model}",
    )
