"""Model listing and selection endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from adapters import clear_adapter_cache, get_adapter
from core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Shared provider → settings-attribute maps ────────────────────────────────
# Single source of truth for mapping provider IDs to Settings model fields.
# Previously this map was duplicated in list_models() and select_model(),
# which meant every new provider needed to be added in two places.
# Now both call sites read from these helpers.


def _model_setting_attr(provider: str) -> str | None:
    """Return the Settings attribute name for a provider's model field.

    Derived from PROVIDER_CONFIGS (single source of truth) so a new provider
    is picked up automatically and can never drift out of this map. (The
    pre-Session-319 hardcoded dict silently omitted ZenMux — added in ADR-9 —
    so its model field resolved to None here while health.py still had it.)
    """
    from adapters.openai_compat import PROVIDER_CONFIGS

    cfg = PROVIDER_CONFIGS.get(provider)
    return cfg.settings_field if cfg else None


def _build_model_setting_map() -> dict[str, str]:
    """Return {provider_id: current_model_value} for all cloud providers.

    Derived from PROVIDER_CONFIGS (single source of truth) — same fix as
    _model_setting_attr (ZenMux was omitted from the old hardcoded dict).
    """
    from adapters.openai_compat import PROVIDER_CONFIGS

    return {
        key: getattr(settings, cfg.settings_field, "") or ""
        for key, cfg in PROVIDER_CONFIGS.items()
    }


async def _list_models_for_provider(provider: str) -> dict:
    """
    List models for a specific provider without switching the active adapter.

    Used by the Settings modal so users picking a provider can see a live
    dropdown of that provider's available models — no free-text typing
    required. Falls back gracefully to just the default model if the
    provider's /models endpoint is unreachable or no API key is saved.
    """
    from adapters.openai_compat import PROVIDER_CONFIGS

    # Validate the provider ID
    if provider == "ollama":
        # Ollama doesn't make sense here — it's the local adapter, not a
        # key-based provider. Return empty so the frontend hides the dropdown.
        return {"models": [], "current": "", "provider": "ollama"}

    cfg = PROVIDER_CONFIGS.get(provider)
    if not cfg:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    current_model = getattr(settings, _model_setting_attr(provider) or "", "") or ""
    model_options: list[dict] = []

    # Always include BOTH the provider's default model AND the currently
    # saved model. Previously this was `current_model or default_model` —
    # if the user had saved a non-default model (e.g. glm-4.5), the default
    # (e.g. glm-4.5-flash, the free one) was never shown. This meant users
    # couldn't switch back to the free default from the dropdown.
    seen_ids: set[str] = set()
    for model_id in (cfg.default_model, current_model):
        if model_id and model_id not in seen_ids:
            model_options.append(
                {"id": model_id, "name": model_id, "provider": provider, "size": "Cloud"}
            )
            seen_ids.add(model_id)

    # Try to fetch the live model list. This requires a saved API key for the
    # provider — without one, the provider's /models endpoint will 401 and we
    # just return the default. The frontend shows the dropdown only when
    # models are available.
    try:
        # Create a throwaway adapter instance for this provider. We don't use
        # get_adapter() because that would cache an instance for a provider
        # that isn't the active adapter — confusing for the adapter cache.
        from adapters.openai_compat import OpenAICompatAdapter

        adapter = OpenAICompatAdapter(provider=provider)
        available = await adapter.list_models()
        await adapter.close()

        # Merge: add any live models not already in the list
        for m in available:
            if m and m not in seen_ids:
                model_options.append({"id": m, "name": m, "provider": provider, "size": "Cloud"})
                seen_ids.add(m)
    except Exception as exc:
        # No API key saved, or provider /models endpoint unreachable.
        # Non-fatal — the dropdown will just show the default model.
        logger.debug("[models] could not list live models for %s: %s", provider, exc)

    return {
        "models": model_options,
        "current": current_model or cfg.default_model,
        "provider": provider,
    }


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
async def list_models(provider: str | None = None):
    """
    List available models.

    Without a `provider` query param: returns models for the currently
    active adapter (used by the chat sidebar's model selector).

    With `?provider=cerebras` (etc.): returns models for that specific
    provider, regardless of which adapter is currently active. Used by
    the Settings modal's "Add Key" form so users can pick a model from
    a live dropdown instead of typing a free-text model ID. Requires
    that the provider has a saved API key (otherwise the provider's
    /models endpoint will 401 and we return just the default model).
    """
    # When a specific provider is requested, build a focused response
    # without disturbing the active adapter's cached instance.
    if provider is not None:
        return await _list_models_for_provider(provider)

    adapter_name = settings.localmind_adapter

    # Get adapter - but don't create new instance, just get the class
    # Also read the active adapter's effective context window (the max
    # input-token budget) once so every model option carries it — the
    # frontend uses it for the live context-window occupancy meter.
    context_window: int | None = None
    try:
        adapter = get_adapter(adapter_name)
        available = await adapter.list_models()
        if adapter_name == "ollama":
            available = set(available)
            # Detect the model's real declared window (/api/show) so the
            # sidebar occupancy meter divides by actual capacity, not 8192.
            _prime = getattr(adapter, "prime_context_window", None)
            if callable(_prime):
                await _prime()
        context_window = adapter.effective_context_window
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
        model_setting_map = _build_model_setting_map()
        current_model = model_setting_map.get(adapter_name, "")

        # Always include the provider's default model in the dropdown — even
        # when a different model is currently selected. Some providers' /models
        # endpoints don't include the default (e.g. Z.ai doesn't list
        # glm-4.5-flash, which is the free model). Without this, users can't
        # switch back to the default from the dropdown.
        from adapters.openai_compat import PROVIDER_CONFIGS

        cfg = PROVIDER_CONFIGS.get(adapter_name)
        seen_ids: set[str] = set()
        if cfg and cfg.default_model:
            model_options.append(
                {"id": cfg.default_model, "name": cfg.default_model, "provider": adapter_name, "size": "Cloud"}
            )
            seen_ids.add(cfg.default_model)

        # Providers that expose a working OpenAI-compatible /models endpoint
        # can be queried live so the model selector shows the full current list.
        # Zen: opencode.ai/zen/v1/models
        # Cerebras: api.cerebras.ai/v1/models (gpt-oss-120b, gemma-4-31b, zai-glm-4.7)
        # Gemini: generativelanguage.googleapis.com/v1beta/openai/models
        # Chutes: llm.chutes.ai/v1/models (all TEE-suffixed)
        # Z.ai: api.z.ai/api/paas/v4/models (GLM-5.2, GLM-4.5-Flash, etc.)
        if adapter_name in ("zen", "cerebras", "gemini", "chutes", "zai", "bankofai"):
            try:
                available = await adapter.list_models()
                for m in available:
                    if m and m not in seen_ids:
                        model_options.append(
                            {"id": m, "name": m, "provider": adapter_name, "size": "Cloud"}
                        )
                        seen_ids.add(m)
            except Exception as exc:
                logger.warning("[models] failed to list models for %s: %s", adapter_name, exc)

        # Zen-specific free default when no model is configured
        if adapter_name == "zen" and not current_model:
            current_model = "deepseek-v4-flash-free"

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

    # Attach the active model's token budget to every option (additive field;
    # the frontend falls back gracefully when it's absent).
    if context_window:
        for opt in model_options:
            opt["context_window"] = context_window

    return {"models": model_options, "current": current_model, "provider": adapter_name}


# Embedding-model substrings — Ollama embedding models carry one of these in
# their name (nomic-embed-text, mxbai-embed-large, all-minilm, bge-m3,
# snowflake-arctic-embed, granite-embedding, …). Chat models never do, so this
# cleanly separates the two lists for the Settings embedding-model dropdown.
_EMBED_NAME_HINTS = ("embed", "minilm", "bge", "gte")


@router.get("/models/embeddings")
async def list_embedding_models():
    """List locally-pulled Ollama models usable as embedding models.

    The main /models list deliberately hides embedding models (they use a
    different endpoint); this endpoint surfaces them for the Settings
    embedding-model selector. The currently-configured embed model is always
    included so the UI can show it even if name-matching missed it.
    """
    current = settings.ollama_embed_model
    names: list[str] = []
    try:
        import httpx

        base = settings.ollama_base_url.rstrip("/")
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{base}/api/tags", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                names = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
    except Exception as exc:
        logger.warning("[models] embedding-model list failed: %s", exc)

    embed_models = [n for n in names if any(h in n.lower() for h in _EMBED_NAME_HINTS)]
    # Always include the configured model so the dropdown can display it.
    if current and current not in embed_models:
        embed_models.insert(0, current)

    # B-2026-08-23-14 guide: tell the UI whether the CONFIGURED embed model is
    # actually pulled, and which pulled alternative to suggest. Without this,
    # the force-insert above hides the mismatch and memory stores silently fail
    # (embedding requests 404 from Ollama). configured_available is True only
    # when the configured model is genuinely among Ollama's pulled models.
    # Ollama names pulled models "name:tag" (e.g. mxbai-embed-large:latest)
    # while settings usually hold the bare name — compare tag-insensitively.
    def _matches_pulled(candidate: str) -> bool:
        base = candidate.split(":", 1)[0].lower()
        return candidate in names or any(n.split(":", 1)[0].lower() == base for n in names)

    configured_available = bool(current) and _matches_pulled(current)
    # Suggest the first pulled embed-capable model that differs from the
    # configured one (and is actually available), so the user has a real option.
    suggested = next(
        (m for m in embed_models if m.split(":", 1)[0] != current.split(":", 1)[0] and m in names),
        None,
    )

    return {
        "models": [{"id": n, "name": n, "provider": "ollama"} for n in embed_models],
        "current": current,
        "configured_available": configured_available,
        "suggested": suggested,
    }


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
        # Session 292: persist under the DEDICATED ollama_model key so the choice
        # survives a restart (previously the ollama branch never saved — only
        # cloud did — so the selected local model was lost on next launch) and
        # never collides with the cloud `model` key.
        settings.save_runtime_settings(ollama_model=model)
    else:
        # Cloud providers: update the appropriate setting
        setting_key = _model_setting_attr(adapter_name)
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
