"""
Model Router — routes each intent to the best available model.

The philosophy: instead of one big model doing everything badly,
use small specialist models doing one thing well.

For Ollama (local):
    Priority order per intent (first one that is actually pulled wins):
    CHAT      → smallest/fastest model (just conversation)
    CODE_EXEC → code-trained model (qwen-coder, deepseek-coder)
    SHELL     → code-trained model
    FILE_TASK → balanced model (needs reading comprehension)
    WEB_SEARCH→ balanced model (needs summarization)
    FILE_WRITE→ code-trained model (structured output)
    MEMORY_OP → smallest model (just retrieval formatting)

For cloud providers (OpenAI, Anthropic, etc.):
    Uses provider-specific model from settings (e.g., OPENAI_MODEL)
    or adapter default. Intent routing not needed since cloud models
    are generally capable across all intents.

Free models that work on 4-8GB RAM, ordered by quality:
    Conversation: gemma3:1b → llama3.2:3b → llama3.1:8b
    Code:         qwen2.5-coder:7b → deepseek-coder:6.7b → llama3.1:8b
    Balanced:     qwen2.5:7b → mistral:7b → llama3.1:8b

The router checks which models are actually pulled and picks the best
available one — never fails, always falls back to the main model.
"""

from __future__ import annotations

import logging

from core.config import settings
from core.models import Intent

logger = logging.getLogger(__name__)

# Intent → ordered list of preferred models (best first)
# Models are checked against what's actually pulled — first match wins.
_INTENT_MODEL_PREFERENCE: dict[str, list[str]] = {
    Intent.SYSINFO.value: [
        "gemma3:1b",
        "llama3.2:1b",
        "llama3.2:3b",
        # any model works — sysinfo result is pre-formatted, model just echoes it
    ],
    Intent.CHAT.value: [
        "gemma3:1b",
        "gemma2:2b",
        "llama3.2:1b",
        "llama3.2:3b",
        "phi3:mini",
        "qwen2.5:3b",
        # fallback to whatever main model is set
    ],
    Intent.CODE_EXEC.value: [
        "qwen2.5-coder:7b",
        "qwen2.5-coder:3b",
        "deepseek-coder:6.7b",
        "deepseek-coder-v2:16b",
        "codellama:7b",
        "llama3.1:8b",
    ],
    Intent.SHELL.value: [
        "qwen2.5-coder:7b",
        "qwen2.5-coder:3b",
        "deepseek-coder:6.7b",
        "llama3.1:8b",
    ],
    Intent.FILE_TASK.value: [
        "qwen2.5:7b",
        "qwen2.5:3b",
        "mistral:7b",
        "llama3.1:8b",
        "llama3.2:3b",
    ],
    Intent.WEB_SEARCH.value: [
        "qwen2.5:7b",
        "qwen2.5:3b",
        "mistral:7b",
        "llama3.1:8b",
    ],
    Intent.FILE_WRITE.value: [
        "qwen2.5-coder:7b",
        "qwen2.5:7b",
        "mistral:7b",
        "llama3.1:8b",
    ],
    Intent.MEMORY_OP.value: [
        "gemma3:1b",
        "llama3.2:3b",
        "llama3.2:1b",
        "llama3.1:8b",
    ],
}

# Cache of pulled models — refreshed at startup and on model switch
_pulled_models: set[str] = set()


def update_pulled_models(models: list[str]) -> None:
    """Call at startup and after model pull/delete to refresh the cache."""
    global _pulled_models
    # Normalize: store both full names and prefix (e.g. "qwen2.5-coder" for "qwen2.5-coder:7b")
    _pulled_models = set(models)
    logger.info(f"[model_router] known pulled models: {sorted(_pulled_models)}")


def _is_available(model: str) -> bool:
    """Check if a model is pulled. Accepts prefix match (e.g. 'qwen2.5-coder')."""
    if model in _pulled_models:
        return True
    # Prefix match: "qwen2.5-coder:7b" matches if "qwen2.5-coder:7b" is pulled
    base = model.split(":")[0]
    return any(m.startswith(base) for m in _pulled_models)


def _resolve(model: str) -> str:
    """Resolve a model name to the exact pulled name (for prefix matches)."""
    if model in _pulled_models:
        return model
    base = model.split(":")[0]
    for m in sorted(_pulled_models):  # sorted for determinism
        if m.startswith(base):
            return m
    return model


def best_model_for(intent: Intent, fallback: str) -> str:
    """
    Return the best available model for this intent.

    For Ollama: uses intent-based routing from _INTENT_MODEL_PREFERENCE.
    For cloud providers: returns the provider-specific model from settings
    or falls back to adapter default.

    Args:
        intent: The classified request intent.
        fallback: The OLLAMA_MODEL setting — always available.

    Returns:
        Model name string suitable for the adapter.
    """
    adapter_name = settings.localmind_adapter

    # Cloud providers — use provider-specific model from settings
    # If model is not configured, use the adapter's default model, not Ollama fallback
    provider_model_map = {
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

    if adapter_name in provider_model_map:
        # Cloud provider selected — use configured model, or adapter default if not set
        model = provider_model_map[adapter_name]
        if model:
            return model
        # No model configured — get the adapter's default from PROVIDER_CONFIGS
        from adapters.openai_compat import PROVIDER_CONFIGS

        if adapter_name in PROVIDER_CONFIGS:
            return PROVIDER_CONFIGS[adapter_name].default_model
        # Fallback shouldn't happen, but guard against misconfiguration
        logger.warning(f"[model_router] no default model for adapter '{adapter_name}', using Ollama fallback")
        # Don't fall through to Ollama logic — return a safe default
        return fallback

    # Ollama — use intent-based routing
    preferences = _INTENT_MODEL_PREFERENCE.get(intent.value, [])

    for candidate in preferences:
        if _is_available(candidate):
            resolved = _resolve(candidate)
            if resolved != fallback:
                logger.debug(f"[model_router] {intent.value} → {resolved} (preferred over {fallback})")
            return resolved

    # Nothing preferred is pulled — use the main model
    logger.debug(f"[model_router] {intent.value} → {fallback} (no specialist available)")
    return fallback


def routing_report(fallback: str) -> dict[str, str]:
    """Return a dict of intent → resolved model for display/debugging."""
    return {intent.value: best_model_for(intent, fallback) for intent in Intent}
