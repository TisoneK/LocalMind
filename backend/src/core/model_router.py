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
import os

from core.config import settings
from core.models import Intent

logger = logging.getLogger(__name__)

# Per-agent model routing
# ------------------------------------------------
# Every agent used to share the single configured model. Per-agent routing
# lets a CodingAgent run a stronger local model, DirectAgent a tiny one,
# and ResearchAgent a cloud model — while DEFAULT behavior stays exactly
# as before (all agents use the configured adapter/model unless the user
# opts in). Mixing local + cloud in one run is explicit opt-in via env
# vars (never the default) — see get_adapter_for_agent.
#
# Format: LOCALMIND_AGENT_MODEL_<NAME> = 'adapter:model' or 'model'.
#   LOCALMIND_AGENT_MODEL_CODING=llama3.1:70b          # same adapter, bigger local model
#   LOCALMIND_AGENT_MODEL_DIRECT=qwen2.5:1.5b          # same adapter, tiny model
#   LOCALMIND_AGENT_MODEL_RESEARCH=zen:deepseek-v4-pro  # different adapter entirely
AGENT_MODEL_ENV_PREFIX: str = "LOCALMIND_AGENT_MODEL_"


def parse_agent_spec(spec: str) -> tuple[str, str] | None:
    """Parse a `LOCALMIND_AGENT_MODEL_*` value into (adapter_name, model).

    Accepts either ``adapter:model`` (e.g. ``zen:deepseek-v4-pro``) or a
    bare model name (e.g. ``llama3.1:70b``) which uses the currently
    configured adapter. Ollama model names contain ``:`` too
    (``llama3.1:70b``), so a spec only splits on the first ``:`` when the
    prefix before it is a KNOWN adapter name (ollama or a cloud provider).
    Returns None for blank input.

    KNOWN COLLISION: local Ollama models whose base name is also a cloud
    provider name (``mistral:7b``, ``deepseek-coder:6.7b``, ``gemini:*``,
    ``cohere:*``) parse as the PROVIDER, not the local model. There is no
    purely syntactic way to distinguish ``mistral:7b`` (local) from
    ``zen:deepseek-v4-pro`` (cloud). Escape hatch: prefix with ``ollama:``
    to force the local model — ``ollama:mistral:7b`` parses to
    ("ollama", "mistral:7b").
    """
    spec = (spec or "").strip()
    if not spec:
        return None
    if ":" in spec:
        prefix, _, rest = spec.partition(":")
        # Lazy import — adapters.openai_compat is heavy and pulls API keys.
        # Known adapter names are the AI-connection ids (presets + custom).
        from core.connections import get_connection_registry

        if prefix == "ollama" or prefix in get_connection_registry().ids():
            return prefix, rest
    return settings.localmind_adapter, spec


def get_adapter_for_agent(
    agent_name: str,
    config_model: str | None = None,
    config_adapter: str | None = None,
):
    """Return the per-agent adapter for ``agent_name``, or None for default.

    Priority:
      1. ``LOCALMIND_AGENT_MODEL_<NAME>`` env var (adapter:model or bare
         model). E.g. ``LOCALMIND_AGENT_MODEL_CODING=zen:deepseek-v4-pro``.
      2. AgentConfig-declared fields (``config_adapter`` / ``config_model``,
         resolved by BaseAgent.run()).

    Returns None when neither is configured — the caller keeps its default
    adapter. Never raises: a misconfigured override (unknown provider,
    missing API key) logs a warning and falls back to None, honoring the
    router's "never fails, always falls back" rule.

    Adapter instances are cached by ``adapters.get_adapter`` keyed on
    (name, model_override), so repeated lookups (top-level agent + every
    delegated child of the same type) share one instance.
    """
    env_value = os.getenv(f"{AGENT_MODEL_ENV_PREFIX}{agent_name.upper()}") or ""
    adapter_name: str | None = None
    model: str = ""
    if env_value.strip():
        parsed = parse_agent_spec(env_value)
        if parsed is None:
            return None
        adapter_name, model = parsed
    elif config_adapter or config_model:
        adapter_name = config_adapter or settings.localmind_adapter
        model = config_model or ""
    else:
        return None

    try:
        from adapters import get_adapter

        return get_adapter(adapter_name, model_override=model or "")
    except Exception as exc:
        logger.warning(
            "[model_router] per-agent adapter for %r failed to build "
            "(%s): %s — falling back to the default adapter",
            agent_name, adapter_name, exc,
        )
        return None


def resolve_agent_adapter(
    agent_name: str,
    config_model: str | None = None,
    config_adapter: str | None = None,
    fallback=None,
):
    """Per-agent adapter with fallback — the single call site for agents.

    Used by ``BaseAgent.run()`` (and, indirectly, by the delegate tools via
    ``get_adapter_for_agent``) so the top-level agent and every delegated
    child resolve their model identically. Returns ``fallback`` when no
    per-agent override is configured.
    """
    routed = get_adapter_for_agent(
        agent_name,
        config_model=config_model,
        config_adapter=config_adapter,
    )
    return routed if routed is not None else fallback

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

    # Cloud connections — resolve the model from the connection record,
    # then the preset's Settings field, then the preset default. Preset ids
    # are unchanged, so the historical resolution order holds for them.
    from adapters.openai_compat import PROVIDER_CONFIGS
    from core.connections import get_connection_registry

    connection = get_connection_registry().get(adapter_name)
    if connection is not None and connection.kind == "openai-compat":
        cfg = PROVIDER_CONFIGS.get(adapter_name)
        model = connection.model or (getattr(settings, cfg.settings_field, "") if cfg else "")
        if model:
            return model
        if cfg is not None:
            return cfg.default_model
        # A custom connection with no model — the adapter raises a clearer
        # error at construction; fall through to the Ollama fallback here
        # rather than returning an empty model to the loop.
        logger.warning(
            "[model_router] connection '%s' has no model configured — using the Ollama fallback",
            adapter_name,
        )
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
