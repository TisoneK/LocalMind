"""
Composable adapter for OpenAI-compatible APIs.

Supports multiple providers (OpenAI, Anthropic, OpenRouter, LiteLLM) with
shared logic and provider-specific config. Each provider is configured
via environment variables and registered in PROVIDER_CONFIGS.

v8 changes:
- Bug C fix: _stream_from_http() now gracefully handles empty content deltas
  (keepalives from providers that send delta.content="" between text chunks).
  Previously these empty deltas were silently skipped (correct), but they
  also shouldn't cause the generator to stall. The fix ensures we continue
  reading from the stream without yielding for empty content.
- v8.1 fix: Tool args truncation — Phase 1 detection now reads up to 10
  chunks (was 5) before deciding text vs tool_call, giving slow-streaming
  providers more time to produce the tool_call delta. Phase 2a now drains
  until [DONE] or finish_reason=="tool_calls" to ensure complete args.
  If args JSON is still invalid after draining, logs a clear warning with
  the raw args preview instead of silently passing malformed data.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, AsyncIterator

import httpx

from adapters.base import BaseAdapter
from core.cache import TTLCache
from core.models import StreamChunk

if TYPE_CHECKING:
    # ToolCallResult is defined in adapters.ollama. Imported only under
    # TYPE_CHECKING to avoid a circular import at runtime (ollama.py is
    # the heavier module). Runtime references use local imports.
    from adapters.ollama import ToolCallResult

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Model context window registry
# ─────────────────────────────────────────────────────────────────────────────

MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    # OpenAI
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4-turbo": 128000,
    "gpt-4": 8192,
    "gpt-3.5-turbo": 16385,
    # Anthropic
    "claude-sonnet-4-20250514": 200000,
    "claude-3-5-sonnet-20241022": 200000,
    "claude-3-5-sonnet-20240620": 200000,
    "claude-3-opus-20240229": 200000,
    "claude-3-sonnet-20240229": 200000,
    "claude-3-haiku-20240307": 200000,
    "claude-3-5-haiku-20241022": 200000,
    # OpenRouter (varies by underlying model, use conservative default)
    "openrouter/auto": 128000,
    "openrouter/free": 128000,
    # DeepSeek
    "deepseek-chat": 64000,
    "deepseek-coder": 64000,
    # Zen (curated models)
    "zen/default": 128000,
    "deepseek-v4-flash-free": 128000,
    # Retain the MiniMax entries for explicitly selected legacy models.
    "minimax-m2.5-free": 128000,
    "MiniMax M2.5 Free": 128000,
    # Groq (fast inference)
    "llama-3.1-70b-versatile": 128000,
    "llama-3.1-8b-instant": 128000,
    "mixtral-8x7b-32768": 32768,
    # Together AI
    "meta-llama/Llama-3.1-70B-Instruct-Turbo": 128000,
    # Mistral
    "mistral-large-latest": 131072,
    "mistral-small-latest": 131072,
    # Cohere
    "command-r-plus": 128000,
    "command-r": 128000,
    # Cerebras (production: gpt-oss-120b; preview: gemma-4-31b, zai-glm-4.7)
    "gpt-oss-120b": 128000,
    "gemma-4-31b": 128000,
    "zai-glm-4.7": 128000,
    # SambaNova
    "Meta-Llama-3.3-70B-Instruct": 128000,
    "DeepSeek-R1": 128000,
    # Google Gemini (via OpenAI-compatible endpoint)
    "gemini-2.5-flash": 1048576,
    "gemini-2.5-pro": 1048576,
    "gemini-2.5-flash-lite": 1048576,
    # Chutes (all current models are TEE-suffixed)
    "deepseek-ai/DeepSeek-V3.2-TEE": 131072,
    "Qwen/Qwen3.6-27B-TEE": 262144,
    "zai-org/GLM-5.2-TEE": 1048576,
    "moonshotai/Kimi-K2.6-TEE": 262144,
    # Z.ai (GLM models — free tier)
    "glm-4.5-flash": 128000,
    "glm-5.2": 1048576,
    "glm-5.1": 1048576,
    "glm-5": 128000,
    "glm-5-turbo": 128000,
    "glm-4.7": 128000,
    # ZenMux — aggregated models (provider/model-name format).
    # ADR-9: IMPLEMENTED BUT UNTESTED. Context windows are the underlying
    # model's, sourced from the provider's documentation. Unknown models
    # fall back to "default": 32768.
    "x-ai/grok-4.5": 131072,
    "anthropic/claude-opus-5": 200000,
    "anthropic/claude-sonnet-5": 200000,
    "anthropic/claude-opus-4-8": 200000,
    "anthropic/claude-fable-5": 200000,
    "google/gemini-3.6-flash": 1048576,
    "google/gemini-3.5-flash": 1048576,
    "google/gemini-3.5-flash-lite": 1048576,
    "openai/gpt-5.6-luna": 128000,
    "openai/gpt-5.6-terra": 128000,
    "openai/gpt-5.6-sol": 128000,
    "z-ai/glm-5.2": 1048576,
    "deepseek/deepseek-v4-flash": 131072,
    "moonshotai/kimi-k3": 262144,
    "minimax/minimax-m3": 128000,
    # Default fallback
    "default": 32768,
}

# ─────────────────────────────────────────────────────────────────────────────
# /models TTL cache (shared TTLCache — was class-level dicts before Session 136)
# ─────────────────────────────────────────────────────────────────────────────
# The provider /models endpoint is fetched by BOTH health_check() and
# list_models(). At startup the frontend polls /api/health every 1.5s,
# Electron every 2s, wait-on polls before launching, and useModels hits
# /api/models — each used to fire an uncached GET {base_url}/models,
# producing 20+ identical Zen fetches in ~7s. A MODULE-level TTLCache (keyed
# by provider) means even the throwaway adapter instances created in
# routes/models.py share the cached result. Failures are NOT cached, so a
# recovering provider is detected promptly.
#
# TTL is 30s (not 60s): the health ROUTE already caches reachability for
# 60s, so an adapter TTL of 30s caps worst-case outage-detection lag at
# ~90s (route 60s + adapter 30s) while still cutting the fetch burst
# from 20+ to ~2/min.
_MODELS_CACHE: "TTLCache[list[str]]" = TTLCache(ttl_seconds=30.0, max_entries=32)
# Per-provider lock so CONCURRENT misses (startup pollers fire within
# the same second) collapse into a single fetch instead of re-bursting.
_models_fetch_locks: dict[str, asyncio.Lock] = {}


# ─────────────────────────────────────────────────────────────────────────────
# Provider configuration
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ProviderConfig:
    """Single source of truth for a provider's configuration.

    All other places that need provider info (config.py routes, model_router,
    adapters/__init__.py) derive from PROVIDER_CONFIGS rather than maintaining
    their own hardcoded lists. Adding a new provider = one entry here.
    """
    name: str  # "openai", "anthropic", "openrouter", etc.
    base_url: str  # e.g. "https://api.openai.com/v1"
    api_key: str  # baked default only (LiteLLM's "dummy"); live value resolved in __init__ via key_env
    default_model: str  # fallback if none specified
    key_env: str  # env var name for the API key (e.g. "OPENAI_API_KEY")
    model_env: str  # env var name for the model override (e.g. "OPENAI_MODEL")
    settings_field: str  # Settings attr for the model override (e.g. "openai_model")
    display_name: str = ""  # human-friendly name for the Settings UI (defaults to name)
    headers: dict | None = None  # optional extra headers
    supports_streaming: bool = True

    def __post_init__(self) -> None:
        if not self.display_name:
            self.display_name = self.name


PROVIDER_CONFIGS: dict[str, ProviderConfig] = {
    "openai": ProviderConfig(
        name="openai",
        display_name="OpenAI",
        base_url="https://api.openai.com/v1",
        api_key="",
        default_model="gpt-4o-mini",
        key_env="OPENAI_API_KEY",
        model_env="OPENAI_MODEL",
        settings_field="openai_model",
    ),
    "anthropic": ProviderConfig(
        name="anthropic",
        display_name="Anthropic",
        base_url="https://api.anthropic.com/v1",
        api_key="",
        default_model="claude-3-5-sonnet-20241022",
        key_env="ANTHROPIC_API_KEY",
        model_env="ANTHROPIC_MODEL",
        settings_field="anthropic_model",
        headers={
            "anthropic-version": "2023-06-01",
            "x-api-key": "",
        },
    ),
    "openrouter": ProviderConfig(
        name="openrouter",
        display_name="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        api_key="",
        default_model="openrouter/auto",
        key_env="OPENROUTER_API_KEY",
        model_env="OPENROUTER_MODEL",
        settings_field="openrouter_model",
    ),
    "deepseek": ProviderConfig(
        name="deepseek",
        display_name="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        api_key="",
        default_model="deepseek-chat",
        key_env="DEEPSEEK_API_KEY",
        model_env="DEEPSEEK_MODEL",
        settings_field="deepseek_model",
    ),
    "lite-llm": ProviderConfig(
        name="lite-llm",
        display_name="LiteLLM",
        base_url=os.getenv("LITELLM_BASE_URL", "http://localhost:4000"),
        api_key="dummy",
        default_model=os.getenv("LITELLM_MODEL", "gpt-4"),
        key_env="LITELLM_API_KEY",
        model_env="LITELLM_MODEL",
        settings_field="litellm_model",
    ),
    "zen": ProviderConfig(
        name="zen",
        display_name="Zen AI",
        base_url="https://opencode.ai/zen/v1",
        api_key="",
        default_model="deepseek-v4-flash-free",
        key_env="ZEN_API_KEY",
        model_env="ZEN_MODEL",
        settings_field="zen_model",
    ),
    # ZenMux — unified API gateway aggregating 100+ models (Claude, GPT,
    # Gemini, Grok, DeepSeek, GLM, etc.) with one API key. OpenAI-SDK
    # compatible. Model format: "provider/model-name" (e.g. "x-ai/grok-4.5",
    # "anthropic/claude-opus-5", "google/gemini-3.6-flash").
    #
    # ADR-9 (Session 33): IMPLEMENTED BUT UNTESTED. The smoke test is
    # BLOCKED — the free plan returns 403 on all chat completions ("No
    # API Request access"). A paid plan (Pro $20/mo, Max $100/mo, or
    # Ultra $400/mo) is required for API access. When the user upgrades,
    # re-run the smoke test (ADR-9 Step 5) before marking this as tested.
    # Per the flaw log (Session 31/33): do NOT claim this works without
    # a real-API smoke test.
    "zenmux": ProviderConfig(
        name="zenmux",
        display_name="ZenMux (paid — API access requires subscription)",
        base_url="https://zenmux.ai/api/v1",
        api_key="",
        default_model="x-ai/grok-4.5",  # currently free on paid plans per web research
        key_env="ZENMUX_API_KEY",
        model_env="ZENMUX_MODEL",
        settings_field="zenmux_model",
    ),
    # High-performance / infra
    "groq": ProviderConfig(
        name="groq",
        display_name="Groq",
        base_url="https://api.groq.com/openai/v1",
        api_key="",
        default_model="llama-3.1-70b-versatile",
        key_env="GROQ_API_KEY",
        model_env="GROQ_MODEL",
        settings_field="groq_model",
    ),
    "together": ProviderConfig(
        name="together",
        display_name="Together AI",
        base_url="https://api.together.ai/v1",
        api_key="",
        default_model="meta-llama/Llama-3.1-70B-Instruct-Turbo",
        key_env="TOGETHER_API_KEY",
        model_env="TOGETHER_MODEL",
        settings_field="together_model",
    ),
    "fireworks": ProviderConfig(
        name="fireworks",
        display_name="Fireworks AI",
        base_url="https://api.fireworks.ai/v1",
        api_key="",
        default_model="accounts/fireworks/models/llama-v3-70b-instruct",
        key_env="FIREWORKS_API_KEY",
        model_env="FIREWORKS_MODEL",
        settings_field="fireworks_model",
    ),
    "deepinfra": ProviderConfig(
        name="deepinfra",
        display_name="DeepInfra",
        base_url="https://api.deepinfra.com/v1",
        api_key="",
        default_model="meta-llama/Llama-3.1-70B-Instruct",
        key_env="DEEPINFRA_API_KEY",
        model_env="DEEPINFRA_MODEL",
        settings_field="deepinfra_model",
    ),
    # Model-specific providers
    "mistral": ProviderConfig(
        name="mistral",
        display_name="Mistral AI",
        base_url="https://api.mistral.ai/v1",
        api_key="",
        default_model="mistral-large-latest",
        key_env="MISTRAL_API_KEY",
        model_env="MISTRAL_MODEL",
        settings_field="mistral_model",
    ),
    "cohere": ProviderConfig(
        name="cohere",
        display_name="Cohere",
        base_url="https://api.cohere.ai/v1",
        api_key="",
        default_model="command-r-plus",
        key_env="COHERE_API_KEY",
        model_env="COHERE_MODEL",
        settings_field="cohere_model",
    ),
    # Gateways (use custom base URL)
    "vercel": ProviderConfig(
        name="vercel",
        display_name="Vercel AI Gateway",
        base_url=os.getenv("VERCEL_AI_GATEWAY_URL", "https://gateway.ai.vercel.sh"),
        api_key="",
        default_model="gpt-4o-mini",
        key_env="VERCEL_API_KEY",
        model_env="VERCEL_MODEL",
        settings_field="vercel_model",
    ),
    "cloudflare": ProviderConfig(
        name="cloudflare",
        display_name="Cloudflare AI Gateway",
        base_url=os.getenv("CLOUDFLARE_GATEWAY_URL", "https://gateway.ai.cloudflare.com"),
        api_key="",
        default_model="@cf/meta/llama-3.1-70b-instruct",
        key_env="CLOUDFLARE_API_KEY",
        model_env="CLOUDFLARE_MODEL",
        settings_field="cloudflare_model",
    ),
    # Free-tier-friendly providers with strong OpenAI compatibility
    "cerebras": ProviderConfig(
        name="cerebras",
        display_name="Cerebras",
        base_url="https://api.cerebras.ai/v1",
        api_key="",
        # gpt-oss-120b is the current production model. llama-3.3-70b and
        # qwen-3-32b were deprecated — see inference-docs.cerebras.ai/support/deprecation
        default_model="gpt-oss-120b",
        key_env="CEREBRAS_API_KEY",
        model_env="CEREBRAS_MODEL",
        settings_field="cerebras_model",
    ),
    "sambanova": ProviderConfig(
        name="sambanova",
        display_name="SambaNova",
        base_url="https://api.sambanova.ai/v1",
        api_key="",
        default_model="Meta-Llama-3.3-70B-Instruct",
        key_env="SAMBANOVA_API_KEY",
        model_env="SAMBANOVA_MODEL",
        settings_field="sambanova_model",
    ),
    "gemini": ProviderConfig(
        name="gemini",
        display_name="Google Gemini",
        # Google's official OpenAI-compatible endpoint
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key="",
        default_model="gemini-2.5-flash",
        key_env="GEMINI_API_KEY",
        model_env="GEMINI_MODEL",
        settings_field="gemini_model",
    ),
    "chutes": ProviderConfig(
        name="chutes",
        display_name="Chutes AI",
        # llm.chutes.ai is the inference host; api.chutes.ai is management only.
        # All current Chutes models are TEE-suffixed (e.g. deepseek-ai/DeepSeek-V3.2-TEE).
        # See https://llm.chutes.ai/v1/models for the live list.
        base_url="https://llm.chutes.ai/v1",
        api_key="",
        default_model="deepseek-ai/DeepSeek-V3.2-TEE",
        key_env="CHUTES_API_KEY",
        model_env="CHUTES_MODEL",
        settings_field="chutes_model",
    ),
    "zai": ProviderConfig(
        name="zai",
        display_name="Z.ai (GLM)",
        # Z.ai's OpenAI-compatible endpoint. Free tier includes GLM-5.2,
        # GLM-5.1, GLM-5, GLM-5-Turbo, GLM-4.7 (limited-time free) and
        # GLM-4.5-Flash (always free). Get a key at z.ai/manage-apikey/billing
        base_url="https://api.z.ai/api/paas/v4",
        api_key="",
        default_model="glm-4.5-flash",
        key_env="ZAI_API_KEY",
        model_env="ZAI_MODEL",
        settings_field="zai_model",
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# Derived registries — single source of truth is PROVIDER_CONFIGS above.
# Adding a new provider = one ProviderConfig entry. Everything else updates
# automatically. Do NOT add provider names to these derived structures.
# ─────────────────────────────────────────────────────────────────────────────

# Tuple of all valid cloud provider adapter names (used by adapters/__init__.py)
CLOUD_PROVIDER_NAMES: tuple[str, ...] = tuple(PROVIDER_CONFIGS.keys())

# Map: provider key → settings field name (used by config.py and model_router.py)
PROVIDER_SETTINGS_FIELDS: dict[str, str] = {
    key: cfg.settings_field for key, cfg in PROVIDER_CONFIGS.items()
}

# Map: provider key → env var name for the model override
PROVIDER_MODEL_ENVS: dict[str, str] = {
    key: cfg.model_env for key, cfg in PROVIDER_CONFIGS.items()
}

# Map: provider key → env var name for the API key
PROVIDER_KEY_ENVS: dict[str, str] = {
    key: cfg.key_env for key, cfg in PROVIDER_CONFIGS.items()
}


# ── Session 23: thinking/response separation helper ──────────────────────────
# Models that support "thinking mode" (GLM, DeepSeek, Qwen, etc.) stream
# their internal reasoning in delta.reasoning_content and the final answer
# in delta.content. The previous code merged both into `text`:
#     text = delta.get("content", "") or delta.get("reasoning_content", "")
# That was a security/UX bug: the model's internal reasoning (which often
# quotes the system prompt verbatim, including user PII like name/OS/memory
# state) leaked into the chat response. Users could extract the entire
# system prompt just by looking at a "Hi" response.
#
# The fix: route reasoning_content to StreamChunk.thinking (which the UI
# renders in a collapsible "THINKING" panel) and content to StreamChunk.text
# (the actual answer). Never merge them.


def _normalize_usage(usage: dict | None) -> dict:
    """Normalize provider usage fields to the OpenAI-compatible names.

    Providers use both ``prompt_tokens``/``completion_tokens`` and
    ``input_tokens``/``output_tokens``. Return only positive integer fields so
    a provider's empty usage heartbeat cannot overwrite real telemetry.
    """
    if not isinstance(usage, dict):
        return {}

    def _positive_int(*keys: str) -> int | None:
        for key in keys:
            value = usage.get(key)
            if isinstance(value, (int, float)) and value >= 0:
                return int(value)
        return None

    normalized: dict[str, int] = {}
    prompt = _positive_int("prompt_tokens", "input_tokens", "prompt_token_count", "input_token_count")
    completion = _positive_int("completion_tokens", "output_tokens", "completion_token_count", "output_token_count")
    total = _positive_int("total_tokens", "total_token_count")
    if prompt is not None:
        normalized["prompt_tokens"] = prompt
    if completion is not None:
        normalized["completion_tokens"] = completion
    if total is not None:
        normalized["total_tokens"] = total
    elif prompt is not None or completion is not None:
        normalized["total_tokens"] = (prompt or 0) + (completion or 0)
    return normalized


def _extract_content_and_reasoning(delta: dict) -> tuple[str, str]:
    """
    Extract content (the answer) and reasoning_content (internal thinking)
    from a streaming delta, keeping them SEPARATE.

    Returns:
        (content, reasoning) — both may be empty strings. The caller must
        route content to StreamChunk.text and reasoning to StreamChunk.thinking.
        Never merge them.

    Some models (DeepSeek-v3, Qwen) wrap reasoning in <think>...</think>
    tags inside content instead of using a separate reasoning_content field.
    We detect and split that too — the <think> portion goes to reasoning,
    the rest stays as content.
    """
    content = delta.get("content", "") or ""
    reasoning = delta.get("reasoning_content", "") or ""

    # Some models (DeepSeek-v3, Qwen) put reasoning in <think>...</think>
    # tags inside content instead of a separate field. Split it out.
    if "<think>" in content:
        import re as _re

        # Extract <think>...</think> blocks → reasoning
        think_matches = _re.findall(r"<think>(.*?)</think>", content, _re.DOTALL)
        if think_matches:
            reasoning += "".join(think_matches)
            # Remove the <think> blocks from content
            content = _re.sub(r"<think>.*?</think>", "", content, flags=_re.DOTALL)

        # Handle unclosed <think> (streaming — tag opened but not yet closed)
        # If there's an open <think> with no closing tag, everything after it
        # is reasoning, not content.
        if "<think>" in content and "</think>" not in content:
            idx = content.find("<think>")
            reasoning += content[idx + len("<think>") :]
            content = content[:idx]

    return content, reasoning


class OpenAICompatAdapter(BaseAdapter):
    """Composable adapter for OpenAI-compatible APIs."""

    @staticmethod
    def clear_models_cache(provider: str | None = None) -> None:
        """Drop cached /models lists. If provider given, only that provider."""
        if provider is None:
            _MODELS_CACHE.clear()
            _models_fetch_locks.clear()
        else:
            _MODELS_CACHE.pop(provider)
            _models_fetch_locks.pop(provider, None)

    async def _fetch_models_cached(self) -> list[str] | None:
        """Return the provider's model list, cached for TTL seconds.

        Returns None when the provider is unreachable or the fetch failed
        (failures are not cached, so a recovering provider is detected
        promptly). Concurrent misses for the same provider are serialized by
        a per-provider lock so the startup burst becomes a single fetch.
        """
        key = self._provider_key
        lock = _models_fetch_locks.setdefault(key, asyncio.Lock())
        async with lock:
            cached = _MODELS_CACHE.get(key)
            if cached is not None:
                return cached
            try:
                response = await self._client.get(
                    f"{self._base_url}/models",
                    headers=self._headers,
                    timeout=15,
                )
                if response.status_code == 200:
                    data = response.json()
                    models = [m.get("id") for m in data.get("data", [])]
                    # Only cache successes — a failure must retry next call.
                    _MODELS_CACHE.set(key, models)
                    return models
                return None
            except Exception as e:
                logger.warning(f"Failed to fetch models for {self._provider_name}: {e}")
                return None

    def __init__(
        self,
        provider: str = "openai",
        model_override: str = "",
    ):
        from core.config import settings

        cfg = PROVIDER_CONFIGS.get(provider)
        if not cfg:
            raise ValueError(f"Unknown provider: {provider}. Available: {list(PROVIDER_CONFIGS.keys())}")

        # Resolve the API key LIVE: runtime settings (Settings UI) -> env
        # var at construction time -> provider baked default (LiteLLM's
        # "dummy" placeholder). Never rely on cfg.api_key's import-time
        # value: freezing the env var into the config at import meant a
        # module imported while a key was set (e.g. tests/api collection
        # importing openai_compat) kept using the stale key even after the
        # env var was removed — defeating runtime key changes and making
        # env manipulation in tests ineffective.
        api_key = (
            settings.get_api_key(provider)
            or os.getenv(cfg.key_env, "")
            or cfg.api_key
        )
        if not api_key:
            raise ValueError(f"API key not set for provider '{provider}'. Set it in settings or .env.")

        self._provider_name = cfg.name
        self._provider_key = provider  # raw key like "gemini", "cerebras", etc.
        self._base_url = cfg.base_url.rstrip("/")
        # Read the model from settings (set by select_model or settings.json),
        # falling back to the provider default. Previously this only used
        # cfg.default_model (a static value evaluated at import time), so
        # model selection via the UI had NO EFFECT on which model the
        # adapter actually used for chat requests.
        settings_model_attr = f"{provider.replace('-', '')}_model"
        settings_model = getattr(settings, settings_model_attr, "") or ""
        self._model = model_override or settings_model or cfg.default_model
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            **(cfg.headers or {}),
        }
        # Update headers with runtime key if needed
        if "x-api-key" in self._headers:
            self._headers["x-api-key"] = api_key

        # Per-intent timeouts (seconds)
        self._timeouts = {
            "chat": 120,
            "web_search": 180,
            "file_task": 180,
            "file_write": 180,
            "file_edit": 180,
            "shell": 120,
            "code_exec": 180,
            "sysinfo": 60,
            "memory_op": 120,
        }

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=30.0),
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
            ),
        )

    def _add_provider_params(self, payload: dict) -> dict:
        """
        Add provider-specific parameters to the API request payload.

        Z.ai (GLM): GLM models default to thinking/reasoning mode, which
        streams 1000+ reasoning tokens before the actual answer. This takes
        20-30 seconds and breaks the ThinkingDispatcher's 10s timeout,
        causing "Thinking... forever". Disabling thinking mode makes GLM
        respond instantly (4 tokens for "Say PONG" vs 1200+ with thinking).
        The reasoning_content field is still read by the streaming parsers
        as a fallback in case thinking is ever re-enabled.
        """
        if self._provider_key == "zai":
            payload["thinking"] = {"type": "disabled"}
        return payload

    @staticmethod
    def _is_permanent_429(body_text: str, retry_after: str | None) -> bool:
        """True when a 429 is a permanent quota/billing exhaustion (daily or
        free-tier limit, out of credits) rather than a transient per-minute
        burst.

        ADR-32: a permanent 429 must NOT be retried. Retrying only burns the
        backoff window and — across an agent loop's several calls — tens of
        seconds, before surfacing an error the user could have seen in the
        first round-trip. Quota markers win over a generic "rate limit"
        phrase so a "free daily rate limit exceeded" body is treated as
        permanent.
        """
        text = (body_text or "").lower()
        permanent_markers = (
            "insufficient_quota",
            "insufficient credits",
            "out of credits",
            "quota",
            "daily limit",
            "daily quota",
            "free tier",
            "free-tier",
            "usage limit",
            "usage_limit",
            "billing",
            "add credits",
            "upgrade your plan",
            "exceeded your current",
        )
        if any(marker in text for marker in permanent_markers):
            return True
        # A very long Retry-After (>= 10 minutes) is a quota window, not a burst.
        if retry_after:
            try:
                if float(retry_after) >= 600:
                    return True
            except ValueError:
                pass
        return False

    async def _send_streaming_with_retry(
        self,
        url: str,
        payload: dict,
        headers: dict | None = None,
        timeout: float | int | None = None,
    ):
        """
        Send a streaming POST request with automatic retry on HTTP 429.

        429 (Too Many Requests) is typically a per-minute burst limit, not a
        daily quota — a short wait + retry succeeds. This is transparent to
        callers: they receive the first successful response stream.

        Retry strategy:
          - Max 2 retries (3 total attempts)
          - Respect the Retry-After response header if present
          - Otherwise use exponential backoff: 2s, then 4s
          - Log each retry so it's visible in the server terminal

        Only retries on 429. Other errors (400/401/402/403/404/500) are
        permanent — retrying would just waste time. The caller gets the
        final response object (whatever status code) and is responsible
        for handling non-200s.
        """
        req_headers = headers or self._headers
        req_timeout = timeout if timeout is not None else 120.0

        usage_option_retry = True
        tool_choice_retry = True
        request_payload = payload
        for attempt in range(3):  # 0, 1, 2 = 3 total attempts
            request = self._client.build_request(
                "POST",
                url,
                json=request_payload,
                headers=req_headers,
                timeout=req_timeout,
            )
            response = await self._client.send(request, stream=True)

            if response.status_code != 429:
                # Some OpenAI-compatible providers reject optional fields
                # (stream_options/include_usage, tool_choice) instead of
                # ignoring them. Retry once without the offending field so
                # telemetry and forced tool choice remain additive and can
                # never break chat.
                if response.status_code in (400, 422):
                    body = (await response.aread()).decode(errors="replace").lower()
                    if (
                        usage_option_retry
                        and "stream_options" in request_payload
                        and (
                            "stream_options" in body
                            or "include_usage" in body
                            or "unknown field" in body
                        )
                    ):
                        await response.aclose()
                        request_payload = dict(request_payload)
                        request_payload.pop("stream_options", None)
                        usage_option_retry = False
                        logger.warning(
                            "[adapter] %s rejected stream usage options; retrying without them",
                            self._provider_name,
                        )
                        continue
                    # Session 238: some providers reject the tool_choice field
                    # (or a specific value like "required"). Retry once
                    # without it so the forced-tool first iteration degrades
                    # to the previous (unforced) behavior instead of failing
                    # the turn with a 400.
                    if (
                        tool_choice_retry
                        and "tool_choice" in request_payload
                        and ("tool_choice" in body or "tool choice" in body)
                    ):
                        await response.aclose()
                        request_payload = dict(request_payload)
                        request_payload.pop("tool_choice", None)
                        tool_choice_retry = False
                        logger.warning(
                            "[adapter] %s rejected tool_choice; retrying without it",
                            self._provider_name,
                        )
                        continue
                return response  # success (200) or non-retryable error

            # Got 429 — read the body so we can distinguish a transient
            # per-minute burst (worth a short retry) from a permanent quota /
            # billing exhaustion (daily or free-tier limit). ADR-32: a
            # permanent 429 must NOT be retried — retrying only burns the
            # backoff window (and, across an agent loop, tens of seconds)
            # before surfacing an error the user could have seen instantly.
            body_text = (await response.aread()).decode(errors="replace")
            retry_after = response.headers.get("retry-after")

            if self._is_permanent_429(body_text, retry_after):
                logger.warning(
                    "[adapter] permanent quota/billing 429 from %s — not retrying, surfacing immediately",
                    self._provider_name,
                )
                # Keep this response open for the caller. Its body is already
                # buffered, so the caller can read it once more and close it;
                # most importantly, do not issue the old extra request below.
                return response

            if attempt == 2:
                # The final transient attempt has already been read. Return
                # this response directly instead of sending a fourth request
                # merely to obtain a fresh response object.
                logger.warning("[adapter] transient 429 from %s after 3 attempts — giving up", self._provider_name)
                return response

            await response.aclose()
            if attempt < 2:  # don't sleep after the last attempt
                # Respect Retry-After header if the provider sent one
                if retry_after:
                    try:
                        wait_secs = float(retry_after)
                    except ValueError:
                        # Could be an HTTP-date format — fall back to backoff
                        wait_secs = 2.0 * (2**attempt)
                else:
                    wait_secs = 2.0 * (2**attempt)  # 2s, then 4s

                logger.warning(
                    "[adapter] transient 429 from %s (attempt %d/3), retrying in %.1fs",
                    self._provider_name,
                    attempt + 1,
                    wait_secs,
                )
                await asyncio.sleep(wait_secs)

        # The loop returns from every 429 attempt (permanent or final
        # transient). This guard is defensive if the retry policy changes.
        raise RuntimeError("429 retry loop exited without a response")

    # ─────────────────────────────────────────────────────────────────────
    # Properties
    # ─────────────────────────────────────────────────────────────────────

    @property
    def context_window(self) -> int:
        return MODEL_CONTEXT_WINDOWS.get(self._model, MODEL_CONTEXT_WINDOWS["default"])

    @property
    def effective_context_window(self) -> int:
        # Cloud APIs don't need smart capping like Ollama
        return self.context_window

    # ─────────────────────────────────────────────────────────────────────
    # Core chat (streaming)
    # ─────────────────────────────────────────────────────────────────────

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        intent: str = "chat",
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        # Session 26: validate kwargs — previously unsupported kwargs
        # (like stream=True) were silently swallowed into **kwargs,
        # causing bugs that were impossible to trace. Now: log a warning
        # so callers know their kwarg is being ignored.
        _SUPPORTED_KWARGS = set()  # chat() doesn't use any kwargs yet
        _unsupported = set(kwargs.keys()) - _SUPPORTED_KWARGS
        if _unsupported:
            logger.warning(
                "[adapter] %s.chat() received unsupported kwargs: %s — "
                "these are silently ignored. Supported: %s",
                self.__class__.__name__,
                _unsupported,
                _SUPPORTED_KWARGS or "(none)",
            )

        timeout = self._timeouts.get(intent, 120)

        # Build payload based on provider
        if self._provider_name == "anthropic":
            async for chunk in self._chat_anthropic(messages, temperature, timeout):
                yield chunk
        else:
            async for chunk in self._chat_openai_style(messages, temperature, timeout):
                yield chunk

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        temperature: float = 0.7,
        intent: str = "chat",
        tool_choice: str | dict | None = None,
    ) -> "AsyncIterator[StreamChunk] | ToolCallResult":
        """Send messages with tool definitions.

        For providers that support OpenAI-style function calling (most do via
        the /chat/completions endpoint), we pass the tools parameter and handle
        tool_call responses. For providers that don't (e.g. Anthropic), we fall
        back to regular chat.

        Returns either:
          - ToolCallResult: when the model requests a tool call
          - AsyncIterator[StreamChunk]: when the model streams text

        IMPORTANT: This method must RETURN (not yield) so that the caller
        (AgentLoop) can distinguish ToolCallResult from streaming text via
        isinstance(). Using yield would make this an async generator, which
        cannot be awaited — causing "async_generator can't be used in 'await'
        expression" errors.
        """
        # Anthropic has a different tool calling format — fall back to plain chat
        # TODO: implement Anthropic native tool calling
        if self._provider_name == "anthropic":

            async def _anthropic_fallback() -> AsyncIterator[StreamChunk]:
                async for chunk in self.chat(messages, temperature, intent):
                    yield chunk

            return _anthropic_fallback()

        # OpenAI-style providers: send tools and parse tool_call responses
        timeout = self._timeouts.get(intent, 120)
        url = f"{self._base_url}/chat/completions"

        # Inject tool descriptions into the system prompt as a fallback
        # for providers that don't support the tools parameter natively.
        # This gives the model context about available tools even if the
        # API doesn't support structured tool calling.
        tool_descriptions = []
        tool_names = set()
        for tool in tools:
            func = tool.get("function", {})
            name = func.get("name", "")
            tool_names.add(name)
            desc = func.get("description", "")
            params = func.get("parameters", {})
            required = params.get("required", [])
            param_desc = ", ".join(
                f"{p}: {params.get('properties', {}).get(p, {}).get('description', p)}" for p in required
            )
            tool_descriptions.append(f"- {name}({param_desc}): {desc}")

        tool_context = ""
        if tool_descriptions:
            tool_context = (
                "\n\nYou have access to these tools. To use a tool, call it directly using "
                "the native tool-calling API. Do NOT output tool calls as text.\n\n"
                "Available tools:\n" + "\n".join(tool_descriptions) + "\n\n"
                "IMPORTANT: Call the tool immediately when needed. Do NOT narrate your intent. "
                "Do NOT output minimax:tool_call or any other text format for tool calls. "
                "Use the native function-calling API only."
            )

        # Add tool context to the system message
        enhanced_messages = list(messages)
        if enhanced_messages and enhanced_messages[0].get("role") == "system":
            enhanced_messages[0] = {
                "role": "system",
                "content": enhanced_messages[0]["content"] + tool_context,
            }

        # Session 31 (root cause found via real-model testing):
        # DeepSeek-v4-flash-free (via Zen) and possibly other providers
        # reject requests where the last message is a `tool` role — they
        # return HTTP 400 "Upstream request failed". This breaks the agent
        # loop: after every tool execution, the loop appends an
        # `assistant`+`tool_calls` message and a `tool` role message, then
        # calls chat_with_tools again. The last message is `tool` role →
        # 400 error → adapter yields error chunk → loop sees error →
        # retries or falls through to _force_final_answer → user sees the
        # generic "I started the Running command request..." fallback.
        #
        # Fix: if the last message is a `tool` role, append a synthetic
        # `user` message prompting the model to continue. This is harmless
        # for providers that don't have this requirement (the model just
        # sees an extra instruction) and necessary for providers that do.
        # Verified against Zen/DeepSeek: appending a user message after
        # the tool role makes the request succeed (200 OK).
        if enhanced_messages and enhanced_messages[-1].get("role") == "tool":
            enhanced_messages = list(enhanced_messages) + [
                {
                    "role": "user",
                    "content": (
                        "Based on the tool result above, continue. Either call "
                        "another tool if needed, or provide your final answer to "
                        "the user."
                    ),
                }
            ]
            logger.debug(
                "[adapter] %s: appended synthetic user message after trailing "
                "tool role (provider may require user-terminated messages)",
                self._provider_name,
            )

        payload = {
            "model": self._model,
            "messages": enhanced_messages,
            "temperature": temperature,
            "stream": True,
            # OpenAI-compatible providers that support streaming usage emit a
            # final usage-only SSE frame when this is enabled. Providers that
            # omit it remain supported through the engine's estimation fallback.
            "stream_options": {"include_usage": True},
        }
        self._add_provider_params(payload)

        # Try sending with the tools parameter for providers that support it
        if tools:
            payload["tools"] = tools

        # Session 238 (Thinker/Agent rebuild Step 0): honor an explicit
        # tool_choice. The parent loop passes tool_choice="required" on the
        # FIRST tool iteration so models that would otherwise answer directly
        # or return empty on the first tool call (gemini-2.5-flash via this
        # OpenAI-compat endpoint, Session 237 trace) are forced to emit a
        # tool call. This parameter was previously accepted but silently
        # ignored — every OpenAI-compatible provider supports the standard
        # tool_choice values ("auto" / "required" / "none" / a specific
        # function). Providers that reject the field are handled by the
        # graceful degrade in _send_streaming_with_retry (retry once without
        # it), so this stays additive and can never break chat.
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice

        # ── Streaming implementation ─────────────────────────────────────────
        # Previous version buffered ALL text before returning, which broke
        # real-time SSE streaming — the user saw "Generating response..."
        # until the entire LLM response was complete, then it appeared at once.
        #
        # New approach: detect tool calls from streaming deltas (they appear
        # early). If no tool call is detected, stream text directly from the
        # HTTP response without buffering. This gives true token-by-token
        # streaming through to the frontend.
        #
        # We use a two-phase approach:
        #   Phase 1: Read deltas until we can determine tool_call vs text
        #            (usually just 1-3 deltas, <100ms)
        #   Phase 2a: If tool_call detected → buffer remaining, return ToolCallResult
        #   Phase 2b: If text → return async gen that yields directly from stream

        try:
            tool_call_buffers: dict[int, dict] = {}
            raw_content_parts: list[str] = []
            usage_metadata: dict = {}
            tool_call_detected = False
            # Initial text accumulated during Phase 1 — yielded once Phase 2
            # decides this is a text response (not tool call).
            initial_text_chunks: list[StreamChunk] = []
            phase1_done = False

            # Open the streaming response WITHOUT async-with so we can hand
            # the open stream to the returned generator. The generator is
            # responsible for closing it. Uses _send_streaming_with_retry
            # to transparently retry on 429 (per-minute burst limits).
            response = await self._send_streaming_with_retry(url, payload, headers=self._headers)

            if response.status_code != 200:
                body = await response.aread()
                await response.aclose()
                error_msg = (
                    f"{self._provider_name} returned {response.status_code}: {body.decode(errors='replace')[:1000]}"
                )
                logger.error(error_msg)

                async def _error_iter():
                    # text="" on error so consumers that only read .text don't
                    # leak the error message as chat content. The .error field
                    # is the authoritative signal.
                    yield StreamChunk(text="", done=True, error=error_msg)

                return _error_iter()

            # ── Phase 1: Detect tool_call vs text ──────────────────────────
            # Read deltas until we see either tool_calls in the delta or
            # enough text to be confident this is a plain text response.
            # Tool calls typically appear in the very first delta.
            # v8.1: raised from 5 to 10 — some providers (MiniMax, etc.)
            # take longer to emit the tool_call delta, and 5 was too
            # aggressive, causing false text classification.
            _DETECTION_CHUNK_LIMIT = 10
            chunks_read = 0
            _safety_error = None  # set if Gemini/other provider blocks via safety filter

            async for line in response.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    phase1_done = True
                    break

                try:
                    obj = json.loads(data)
                    usage_metadata.update(_normalize_usage(obj.get("usage")))
                    choice = obj.get("choices", [{}])[0]
                    delta = choice.get("delta", {})
                    chunks_read += 1

                    # Check for tool calls in the delta. Session 116 (real-
                    # model smoke test): providers commonly emit a first
                    # assistant delta with `tool_calls: null` (or an empty
                    # list). The old `"tool_calls" in delta` guard treated
                    # that as a tool call and iterated None -> TypeError
                    # 'NoneType' object is not iterable, which escaped the
                    # inner except (JSONDecodeError/IndexError/KeyError) and
                    # killed the whole turn via the outer handler. Truthy
                    # .get() skips null/empty deltas and keeps reading.
                    if delta.get("tool_calls"):
                        tool_call_detected = True
                        for tc in delta["tool_calls"]:
                            idx = tc.get("index", 0)
                            if idx not in tool_call_buffers:
                                tool_call_buffers[idx] = {"name": "", "arguments": ""}
                            if tc.get("function", {}).get("name"):
                                tool_call_buffers[idx]["name"] = tc["function"]["name"]
                            if tc.get("function", {}).get("arguments"):
                                tool_call_buffers[idx]["arguments"] += tc["function"]["arguments"]

                    # Session 23: route reasoning_content to `thinking`, content
                    # to `text`. Never merge them — merging leaks the model's
                    # internal reasoning (which quotes the system prompt,
                    # including user PII) into the chat response.
                    _content, _reasoning = _extract_content_and_reasoning(delta)
                    if _reasoning:
                        initial_text_chunks.append(
                            StreamChunk(text="", thinking=_reasoning, done=False, usage=dict(usage_metadata))
                        )
                    if _content:
                        raw_content_parts.append(_content)
                        initial_text_chunks.append(
                            StreamChunk(text=_content, done=False, usage=dict(usage_metadata))
                        )

                    # Check finish_reason for tool calls — THIS signals completion
                    finish_reason = choice.get("finish_reason", "")
                    if finish_reason == "tool_calls":
                        tool_call_detected = True
                        phase1_done = True  # Tool call is complete, stop reading
                        break

                    # Check finish_reason for safety/content filter blocks
                    # (same as _chat_openai_style — Gemini can silently block)
                    if finish_reason and finish_reason.lower() in (
                        "safety",
                        "content_filter",
                        "prohibited_content",
                        "recitation",
                    ):
                        error_msg = (
                            f"{self._provider_name} blocked the response "
                            f"(finish_reason={finish_reason}). This is usually "
                            f"a content filter — try rephrasing your message "
                            f"or switching to a different provider."
                        )
                        logger.warning(error_msg)
                        phase1_done = True
                        # Store the error so _stream_from_http can yield it
                        _safety_error = error_msg
                        break

                except (json.JSONDecodeError, IndexError, KeyError):
                    continue

                # Decision point: if we've seen text and no tool_call so far,
                # check if the text contains MiniMax's proprietary tool_call format
                # before deciding this is a plain text response. MiniMax outputs
                # tool calls as text content in the format:
                #   minimax:tool_call <invoke name="TOOL">...</invoke> </minimax:tool_call>
                # If we find this pattern, we should NOT break out of Phase 1
                # — instead, continue reading to get the complete tool call text.
                #
                # v8.2 fix: MiniMax sometimes outputs a text prefix (e.g., "Searching the web")
                # BEFORE the minimax:tool_call XML. The previous check at chunks_read >= 4
                # would break too early if the text prefix consumed the first 4 chunks.
                # Now we:
                # 1. Use a larger detection window (15 chunks instead of 4)
                # 2. Check for both the full pattern AND the "minimax:tool_call" prefix
                #    (partial match) — if we see even the start of a tool call, keep reading
                # 3. After 15 chunks with no sign of tool calling, break confidently
                #
                # Session 31 (root cause found via real-model testing):
                # DeepSeek-v4-flash-free produces 80+ reasoning chunks BEFORE
                # the tool_call delta arrives. The break at chunks_read >= 15
                # was firing during the reasoning phase, falling through to
                # Phase 2b (text streaming), which silently dropped the
                # tool_call deltas (it only handles content/reasoning, not
                # tool_calls). The model's tool call was lost — user saw
                # empty output.
                #
                # Fix: only break out of Phase 1 if we've seen actual CONTENT
                # (not just reasoning). Reasoning-only chunks mean the model
                # is still thinking and hasn't decided between text vs tool
                # call yet. We must keep reading until content or tool_calls
                # arrives. Add a hard cap (500 chunks) to prevent infinite
                # looping if the model streams reasoning forever.
                if not tool_call_detected and initial_text_chunks and chunks_read >= 4:
                    _full_text_so_far = "".join(raw_content_parts)
                    _mm_full_check = re.search(
                        r'minimax:tool_call\s*<invoke\s+name=["\']\w+["\']',
                        _full_text_so_far,
                        re.IGNORECASE,
                    )
                    _mm_prefix_check = "minimax:tool_call" in _full_text_so_far.lower()
                    if _mm_full_check:
                        # Full MiniMax tool call pattern detected — don't break,
                        # continue reading to get the complete call
                        logger.info("[adapter] MiniMax tool_call pattern detected in Phase 1 text — continuing to read")
                    elif _mm_prefix_check:
                        # Partial "minimax:tool_call" prefix detected — the full
                        # <invoke> tag hasn't arrived yet. Keep reading.
                        logger.info(
                            "[adapter] MiniMax tool_call prefix detected in Phase 1 — continuing to read for full pattern"  # noqa: E501
                        )
                    elif _full_text_so_far and chunks_read >= 15:
                        # We've seen actual CONTENT (not just reasoning) and no
                        # tool call sign — this is a text response. Break.
                        phase1_done = True
                        break
                    elif not _full_text_so_far and chunks_read >= 500:
                        # Reasoning-only for 500 chunks with no content or
                        # tool_calls — model is stuck thinking. Break to avoid
                        # infinite loop; Phase 2b will stream whatever comes.
                        logger.warning(
                            "[adapter] Phase 1 read 500 chunks of reasoning with no "
                            "content or tool_calls — breaking to avoid infinite loop"
                        )
                        phase1_done = True
                        break
                    # else: keep reading — either chunks_read < 15, or we've
                    # only seen reasoning (no content yet) and the model may
                    # still produce a tool_call.

            # ── Safety filter check ─────────────────────────────────────────
            # If the provider blocked the response via a safety/content filter
            # during Phase 1, yield the error immediately — don't proceed to
            # Phase 2 (there's nothing to stream or collect).
            if _safety_error:
                await response.aclose()

                async def _safety_error_iter():
                    yield StreamChunk(text="", done=True, error=_safety_error)

                return _safety_error_iter()

            # ── Phase 2a: Tool call detected ──────────────────────────────
            # Continue reading to collect full tool call arguments, then
            # return ToolCallResult.
            if tool_call_detected:
                # Drain remaining lines to get full tool call args.
                # Session 116 (real-model smoke test): the httpx stream is
                # ONE-SHOT — Phase 1 already consumed it (it only exits via
                # finish_reason=tool_calls, [DONE], or exhaustion, which all
                # mean the args are COMPLETE). Re-iterating raises
                # RuntimeError("content has already been streamed"), which
                # previously escaped to the outer handler and killed the
                # whole turn. The drain only exists to consume the tail +
                # usage frame; the args are already fully buffered, so
                # swallowing the one-shot error is correct.
                try:
                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                            usage_metadata.update(_normalize_usage(obj.get("usage")))
                            choice = obj.get("choices", [{}])[0]
                            delta = choice.get("delta", {})
                            if delta.get("tool_calls"):
                                for tc in delta["tool_calls"]:
                                    idx = tc.get("index", 0)
                                    if idx not in tool_call_buffers:
                                        tool_call_buffers[idx] = {"name": "", "arguments": ""}
                                    if tc.get("function", {}).get("name"):
                                        tool_call_buffers[idx]["name"] = tc["function"]["name"]
                                    if tc.get("function", {}).get("arguments"):
                                        tool_call_buffers[idx]["arguments"] += tc["function"]["arguments"]
                            # Session 23: separate reasoning from content
                            _content, _reasoning = _extract_content_and_reasoning(delta)
                            if _reasoning:
                                # Reasoning goes to a separate buffer — not
                                # raw_content_parts (which becomes the response text)
                                pass  # reasoning is streamed via thinking field elsewhere
                            if _content:
                                raw_content_parts.append(_content)
                            finish_reason = choice.get("finish_reason", "")
                            if finish_reason == "tool_calls":
                                # Tool call complete — stop reading
                                break
                        except (json.JSONDecodeError, IndexError, KeyError):
                            continue
                except RuntimeError:
                    logger.debug(
                        "[adapter] %s: stream already consumed after Phase 1 — "
                        "skipping drain (tool args complete)",
                        self._provider_name,
                    )

                await response.aclose()

                if tool_call_buffers:
                    first_idx = sorted(tool_call_buffers.keys())[0]
                    buf = tool_call_buffers[first_idx]
                    raw_args = buf.get("arguments", "{}")
                    try:
                        tool_args = json.loads(raw_args) if raw_args else {}
                    except json.JSONDecodeError:
                        # v8.1: Enhanced logging for truncated tool args.
                        # The stream may have ended before the args were
                        # fully transmitted. Log the raw args for debugging
                        # and pass them through so the agent loop can
                        # detect the malformed args and retry.
                        logger.warning(
                            "[adapter] tool args not valid JSON (possibly truncated). Raw args (%d chars): %s",
                            len(raw_args),
                            raw_args[:300],
                        )
                        # Try to extract partial args using a lenient parser
                        # Some providers emit valid key-value pairs but with
                        # truncated string values — we can still extract the
                        # tool name and partial params.
                        tool_args = {"_raw_arguments": raw_args}
                        # Attempt a simple key-value extraction for common params
                        import re as _re

                        for _key in ("path", "command", "query", "code", "content", "description"):
                            _m = _re.search(rf'"{_key}"\s*:\s*"([^"]*)', raw_args)
                            if _m:
                                tool_args[_key] = _m.group(1)

                    if len(tool_call_buffers) > 1:
                        extra = [tool_call_buffers[i]["name"] for i in sorted(tool_call_buffers.keys())[1:]]
                        logger.warning(
                            "[adapter] %d tool calls; using first (%s), extra: %s",
                            len(tool_call_buffers),
                            buf["name"],
                            extra,
                        )

                    from adapters.ollama import ToolCallResult

                    return ToolCallResult(
                        tool_name=buf["name"],
                        tool_args=tool_args,
                        raw_content="".join(raw_content_parts),
                        usage=usage_metadata,
                    )

                # Tool call detected but no buffers parsed — treat as text
                # (fall through to Phase 2b)

            # ── MiniMax proprietary format detection ─────────────────────
            # MiniMax M2.5 Free sometimes outputs tool calls as text in the
            # format: minimax:tool_call <invoke name="TOOL"> <parameter
            # name="param">value</parameter> </invoke> </minimax:tool_call>
            # This is NOT the standard OpenAI tool_calls delta format. We need
            # to detect this pattern in the accumulated text and convert it to
            # a proper ToolCallResult so the agent loop can execute the tool.
            full_initial_text = "".join(raw_content_parts)
            _MINIMAX_TC_RE = re.compile(
                r'minimax:tool_call\s*<invoke\s+name=["\'](\w+)["\']>(.*?)</invoke>\s*</minimax:tool_call>',
                re.DOTALL | re.IGNORECASE,
            )
            _minimax_match = _MINIMAX_TC_RE.search(full_initial_text)
            if _minimax_match:
                _mm_tool_name = _minimax_match.group(1)
                _mm_params_xml = _minimax_match.group(2)
                # Normalize tool name to lowercase — MiniMax outputs "SHELL"
                # but the tool registry expects "shell"
                _mm_tool_name = _mm_tool_name.lower()
                # Parse <parameter name="key">value</parameter> from the XML
                _mm_args = {}
                _PARAM_RE = re.compile(
                    r'<parameter\s+name=["\']([^"\']+)["\']>([^<]*)</parameter>',
                    re.DOTALL,
                )
                for _pm in _PARAM_RE.finditer(_mm_params_xml):
                    _mm_args[_pm.group(1)] = _pm.group(2).strip()
                logger.info(
                    "[adapter] MiniMax proprietary tool_call detected: %s args=%s",
                    _mm_tool_name,
                    list(_mm_args.keys()),
                )
                await response.aclose()
                from adapters.ollama import ToolCallResult

                return ToolCallResult(
                    tool_name=_mm_tool_name,
                    tool_args=_mm_args,
                    raw_content=full_initial_text,
                    usage=usage_metadata,
                )

            # ── Phase 2b: Text response — stream directly from HTTP ──────
            # Return an async generator that yields the initial buffered text
            # and then continues reading from the still-open HTTP stream.
            # The generator closes the response when exhausted.
            _initial = initial_text_chunks
            _resp = response
            _raw_parts = list(raw_content_parts)  # snapshot for JSON fallback
            _tool_names = tool_names  # captured for mid-stream detection
            _usage = usage_metadata  # updated by the live stream closure

            async def _stream_from_http() -> AsyncIterator[StreamChunk]:
                """Yield text chunks directly from the live HTTP stream.

                Bug C fix: Some providers send empty content deltas as
                keepalives (delta.content = ""). These should not block the
                stream — we simply skip them without yielding, and continue
                reading. Previously this was handled implicitly (the `if text:`
                check skipped empty strings), but the fix makes this explicit
                and also ensures we don't accidentally treat a keepalive as
                an error or end-of-stream signal.

                v8.2 fix: MiniMax tool_call XML leak prevention. MiniMax sometimes
                outputs tool calls as text content (minimax:tool_call <invoke...>)
                which should NEVER be shown to the user. We filter these patterns
                from the text stream before yielding chunks to the caller.
                """
                full_text_parts = list(_raw_parts)
                json_tool_checked = False
                minimax_checked = False

                # v8.2: Pre-compiled patterns for filtering MiniMax tool call XML
                # from the text stream. These patterns match the proprietary format
                # that MiniMax uses when it doesn't use native tool calling.
                _mm_full_pattern = re.compile(
                    r'minimax:tool_call\s*<invoke\s+name=["\'][^"\']+["\']\s*>.*?</invoke>\s*</minimax:tool_call>',
                    re.DOTALL | re.IGNORECASE,
                )
                _mm_prefix_pattern = re.compile(
                    r"minimax:tool_call\s*<invoke[^>]*>.*?</invoke>",
                    re.DOTALL | re.IGNORECASE,
                )
                # Also match just the opening "minimax:tool_call" tag as a prefix
                _mm_tag_prefix = re.compile(
                    r"minimax:tool_call\b",
                    re.IGNORECASE,
                )

                try:
                    # Yield the initial text accumulated during Phase 1
                    # v8.2: Filter MiniMax tool_call XML from initial text
                    for chunk in _initial:
                        filtered_text = _mm_full_pattern.sub("", chunk.text)
                        filtered_text = _mm_prefix_pattern.sub("", filtered_text)
                        filtered_text = _mm_tag_prefix.sub("", filtered_text)
                        if filtered_text or chunk.thinking or chunk.usage:
                            yield StreamChunk(
                                text=filtered_text,
                                thinking=chunk.thinking,
                                done=False,
                                usage=dict(_usage),
                            )

                    # Continue reading from the still-open stream. Session
                    # 116 (real-model smoke test): httpx streams are ONE-SHOT.
                    # When Phase 1 consumed the response (it ended without a
                    # [DONE] line — phase1_done stays False — or broke after
                    # [DONE]), re-iterating raises RuntimeError("content has
                    # already been streamed"). Everything was already buffered
                    # into _initial/_raw_parts, so skip the re-iteration.
                    if not phase1_done and not _resp.is_stream_consumed:
                        async for line in _resp.aiter_lines():
                            if not line or not line.startswith("data: "):
                                # Empty lines or non-data lines are SSE
                                # keepalives — skip them but keep reading.
                                continue
                            data = line[6:]
                            if data == "[DONE]":
                                break

                            try:
                                obj = json.loads(data)
                                _usage.update(_normalize_usage(obj.get("usage")))
                                _choice = obj.get("choices", [{}])[0]
                                delta = _choice.get("delta", {})
                                # Session 23: separate reasoning from content
                                _content, _reasoning = _extract_content_and_reasoning(delta)
                                # Bug C fix: explicitly handle empty content deltas.
                                # Some providers send delta.content="" as keepalives.
                                # These are not errors — just skip and continue.
                                if _reasoning:
                                    yield StreamChunk(
                                        text="", thinking=_reasoning, done=False, usage=dict(_usage)
                                    )
                                if _content:
                                    text = _content
                                    # v8.2: Filter MiniMax tool_call XML from streaming text.
                                    filtered_text = _mm_full_pattern.sub("", text)
                                    filtered_text = _mm_prefix_pattern.sub("", filtered_text)
                                    filtered_text = _mm_tag_prefix.sub("", filtered_text)
                                    if not filtered_text:
                                        # The entire chunk was a tool call tag — skip it
                                        full_text_parts.append(text)
                                        continue
                                    full_text_parts.append(text)
                                    yield StreamChunk(
                                        text=filtered_text, done=False, usage=dict(_usage)
                                    )

                                    # One-time MiniMax proprietary format check.
                                    # MiniMax may send its tool_call as text
                                    # content mid-stream after initial text.
                                    if not minimax_checked and len("".join(full_text_parts)) > 60:
                                        minimax_checked = True
                                        _full_so_far = "".join(full_text_parts)
                                        _mm_re = re.compile(
                                            r'minimax:tool_call\s*<invoke\s+name=["\'](\w+)["\']>(.*?)</invoke>\s*</minimax:tool_call>',
                                            re.DOTALL | re.IGNORECASE,
                                        )
                                        _mm_m = _mm_re.search(_full_so_far)
                                        if _mm_m:
                                            # MiniMax tool call found mid-stream.
                                            # We can't un-send the text already
                                            # yielded, but we log it for debugging.
                                            logger.info(
                                                "[adapter] MiniMax tool_call detected mid-stream (after text already sent): %s",  # noqa: E501
                                                _mm_m.group(1),
                                            )

                                    # One-time JSON tool fallback check after
                                    # accumulating enough text. This handles
                                    # providers that don't support structured
                                    # tool calling.
                                    if not json_tool_checked and len("".join(full_text_parts)) > 80:
                                        json_tool_checked = True
                                        full_so_far = "".join(full_text_parts)
                                        _JSON_TOOL_RE = re.compile(
                                            r'```json\s*\n?\s*(\{[^`]*?"tool"\s*:\s*"[^"]+?"[^}]*\})\s*\n?\s*```',
                                            re.DOTALL,
                                        )
                                        json_match = _JSON_TOOL_RE.search(full_so_far)
                                        if json_match:
                                            try:
                                                tool_json = json.loads(json_match.group(1))
                                                tn = tool_json.get("tool", "")
                                                if tn and tn in {t["function"]["name"] for t in tools}:
                                                    # Found a JSON tool call —
                                                    # can't un-send text, but log it
                                                    logger.info(
                                                        "[adapter] JSON tool call found mid-stream: %s",
                                                        tn,
                                                    )
                                            except (json.JSONDecodeError, KeyError):
                                                pass
                                # else: empty content delta (keepalive) — skip, continue reading

                                # Check finish_reason for safety/content filter
                                # blocks. Gemini returns finish_reason="SAFETY"
                                # when its content filter triggers, leaving content
                                # empty. This check is OUTSIDE the `if text:` block
                                # so it fires even when no content was yielded.
                                _fr = _choice.get("finish_reason", "")
                                if _fr and _fr.lower() in (
                                    "safety",
                                    "content_filter",
                                    "prohibited_content",
                                    "recitation",
                                ):
                                    _safety_msg = (
                                        f"{self._provider_name} blocked the response "
                                        f"(finish_reason={_fr}). This is usually "
                                        f"a content filter — try rephrasing your "
                                        f"message or switching providers."
                                    )
                                    logger.warning(_safety_msg)
                                    yield StreamChunk(text="", done=True, error=_safety_msg)
                                    return

                            except (json.JSONDecodeError, IndexError, KeyError):
                                continue

                    yield StreamChunk(text="", done=True, usage=dict(_usage))
                finally:
                    await _resp.aclose()

            return _stream_from_http()

        except httpx.ConnectError:
            msg = f"Cannot connect to {self._provider_name} at {self._base_url}. Check your network and API endpoint."
            logger.error(msg)

            async def _error_iter():
                yield StreamChunk(text="", done=True, error=msg)

            return _error_iter()

        except httpx.TimeoutException:
            msg = f"{self._provider_name} timed out after {timeout}s. The request may be too large for the context window."  # noqa: E501
            logger.error(msg)

            async def _error_iter():
                yield StreamChunk(text="", done=True, error=msg)

            return _error_iter()

        except Exception as e:
            msg = f"Unexpected error calling {self._provider_name}: {e}"
            logger.error(msg)

            async def _error_iter():
                yield StreamChunk(text="", done=True, error=msg)

            return _error_iter()

    async def _chat_openai_style(
        self,
        messages: list[dict],
        temperature: float,
        timeout: int,
    ) -> AsyncIterator[StreamChunk]:
        """Handle OpenAI-style APIs (OpenAI, OpenRouter, DeepSeek, LiteLLM)."""
        url = f"{self._base_url}/chat/completions"
        usage_metadata: dict = {}
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        self._add_provider_params(payload)

        try:
            response = await self._send_streaming_with_retry(url, payload, headers=self._headers, timeout=timeout)
            try:
                if response.status_code != 200:
                    body = await response.aread()
                    error_msg = (
                        f"{self._provider_name} returned {response.status_code}: {body.decode(errors='replace')[:1000]}"
                    )
                    logger.error(error_msg)
                    yield StreamChunk(text="", done=True, error=error_msg)
                    return

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        yield StreamChunk(text="", done=True, usage=dict(usage_metadata))
                        return

                    try:
                        obj = json.loads(data)
                        usage_metadata.update(_normalize_usage(obj.get("usage")))
                        choice = obj.get("choices", [{}])[0]
                        delta = choice.get("delta", {})
                        # Session 23: separate reasoning from content
                        _content, _reasoning = _extract_content_and_reasoning(delta)
                        if _reasoning:
                            yield StreamChunk(text="", thinking=_reasoning, done=False, usage=dict(usage_metadata))
                        if _content:
                            yield StreamChunk(text=_content, done=False, usage=dict(usage_metadata))

                        # Check finish_reason for safety/content filter blocks.
                        # Gemini returns finish_reason="SAFETY" when its content
                        # filter triggers, leaving content empty. Without this
                        # check, the user sees a blank response with no error.
                        finish_reason = choice.get("finish_reason", "")
                        if finish_reason and finish_reason.lower() in (
                            "safety",
                            "content_filter",
                            "prohibited_content",
                            "recitation",
                        ):
                            error_msg = (
                                f"{self._provider_name} blocked the response "
                                f"(finish_reason={finish_reason}). This is usually "
                                f"a content filter — try rephrasing your message "
                                f"or switching to a different provider."
                            )
                            logger.warning(error_msg)
                            yield StreamChunk(text="", done=True, error=error_msg)
                            return
                    except (json.JSONDecodeError, IndexError, KeyError):
                        continue
            finally:
                await response.aclose()

        except httpx.ConnectError:
            msg = f"Cannot connect to {self._provider_name} at {self._base_url}. Check your network and API endpoint."
            logger.error(msg)
            yield StreamChunk(text="", done=True, error=msg)
        except httpx.TimeoutException:
            msg = f"{self._provider_name} timed out after {timeout}s. The request may be too large for the context window."  # noqa: E501
            logger.error(msg)
            yield StreamChunk(text="", done=True, error=msg)
        except Exception as e:
            msg = f"Unexpected error calling {self._provider_name}: {e}"
            logger.error(msg)
            yield StreamChunk(text="", done=True, error=msg)

    async def _chat_anthropic(
        self,
        messages: list[dict],
        temperature: float,
        timeout: int,
    ) -> AsyncIterator[StreamChunk]:
        """Handle Anthropic's API (different format from OpenAI)."""
        url = f"{self._base_url}/messages"

        # Convert messages to Anthropic format
        # Anthropic uses "system" as a separate field, not in messages
        system_messages = [m for m in messages if m.get("role") == "system"]
        non_system_messages = [m for m in messages if m.get("role") != "system"]

        system_content = ""
        if system_messages:
            system_content = system_messages[0].get("content", "")

        # Build Anthropic message format
        anthropic_messages = []
        for m in non_system_messages:
            role = "assistant" if m.get("role") == "assistant" else "user"
            anthropic_messages.append(
                {
                    "role": role,
                    "content": m.get("content", ""),
                }
            )

        payload = {
            "model": self._model,
            "messages": anthropic_messages,
            "max_tokens": 4096,
            "temperature": temperature,
            "stream": True,
        }
        if system_content:
            payload["system"] = system_content

        try:
            response = await self._send_streaming_with_retry(url, payload, headers=self._headers, timeout=timeout)
            try:
                if response.status_code != 200:
                    body = await response.aread()
                    error_msg = f"Anthropic returned {response.status_code}: {body.decode(errors='replace')[:1000]}"
                    logger.error(error_msg)
                    yield StreamChunk(text="", done=True, error=error_msg)
                    return

                # Anthropic streaming SSE event format (different from OpenAI):
                #   event: message_start          — session metadata
                #   event: content_block_start    — new content block (index, type)
                #   event: content_block_delta    — incremental text: delta.text
                #   event: content_block_stop     — block complete
                #   event: message_delta          — stop_reason, usage
                #   event: message_stop           — message complete → [DONE]
                #
                # Each SSE frame has both an `event:` line and a `data:` line.
                # We only parse the `data:` line and dispatch on `obj["type"]`.
                # The previous code read `obj.get("content", [])` which is the
                # NON-STREAMING response shape — streaming deltas never have a
                # top-level `content` array, so every chunk was silently dropped
                # and the user saw a blank response.
                # B-2026-08-09-14 (Session 90): usage_metadata is populated
                # from message_delta usage frames; it must be initialized here —
                # a missing init was a latent NameError that would crash every
                # Anthropic streaming request (found by the new CI check).
                usage_metadata: dict = {}
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        yield StreamChunk(text="", done=True, usage=dict(usage_metadata))
                        return

                    try:
                        obj = json.loads(data)
                        usage_metadata.update(_normalize_usage(obj.get("usage")))
                        evt_type = obj.get("type", "")

                        # content_block_delta carries the actual text tokens.
                        # delta.type is "text_delta" for text, "input_json_delta"
                        # for tool inputs (we don't support Anthropic tool calls
                        # here — falls back to plain chat via chat_with_tools).
                        if evt_type == "content_block_delta":
                            delta = obj.get("delta", {})
                            if delta.get("type") == "text_delta":
                                text = delta.get("text", "")
                                if text:
                                    yield StreamChunk(text=text, done=False, usage=dict(usage_metadata))

                        # message_stop signals the end of the streamed message.
                        # Anthropic doesn't send a [DONE] line — we synthesize
                        # the done chunk here so the caller's stream terminates.
                        elif evt_type == "message_stop":
                            yield StreamChunk(text="", done=True, usage=dict(usage_metadata))
                            return

                        # message_delta carries stop_reason — surface content
                        # filter blocks as an error so the user sees a clear
                        # message instead of a blank response.
                        elif evt_type == "message_delta":
                            delta = obj.get("delta", {})
                            stop_reason = delta.get("stop_reason", "")
                            if stop_reason in (
                                "content_filter",
                                "safety_filter",
                                "prohibited_content",
                            ):
                                error_msg = (
                                    f"{self._provider_name} blocked the response "
                                    f"(stop_reason={stop_reason}). This is usually "
                                    f"a content filter — try rephrasing your message "
                                    f"or switching to a different provider."
                                )
                                logger.warning(error_msg)
                                yield StreamChunk(text="", done=True, error=error_msg)
                                return
                    except (json.JSONDecodeError, KeyError):
                        continue
            finally:
                await response.aclose()

        except httpx.ConnectError:
            msg = f"Cannot connect to Anthropic at {self._base_url}. Check your network."
            logger.error(msg)
            yield StreamChunk(text="", done=True, error=msg)
        except httpx.TimeoutException:
            msg = f"Anthropic timed out after {timeout}s."
            logger.error(msg)
            yield StreamChunk(text="", done=True, error=msg)
        except Exception as e:
            msg = f"Unexpected error calling Anthropic: {e}"
            logger.error(msg)
            yield StreamChunk(text="", done=True, error=msg)

    # ─────────────────────────────────────────────────────────────────────
    # Model management
    # ─────────────────────────────────────────────────────────────────────

    async def health_check(self) -> bool:
        """Return True if the provider endpoint is reachable."""
        try:
            if self._provider_name == "anthropic":
                # Anthropic doesn't have a simple /models endpoint,
                # use a minimal message to check connectivity
                response = await self._client.post(
                    f"{self._base_url}/messages",
                    json={
                        "model": self._model,
                        "messages": [{"role": "user", "content": "hi"}],
                        "max_tokens": 1,
                    },
                    headers=self._headers,
                    timeout=10,
                )
                return response.status_code in (
                    200,
                    400,
                )  # 400 means auth worked but invalid request
            else:
                return (await self._fetch_models_cached()) is not None
        except Exception:
            return False

    async def list_models(self) -> list[str]:
        """Return list of available models for this provider."""
        # _fetch_models_cached() never raises (it catches and returns None),
        # so no try/except is needed here.
        if self._provider_name == "anthropic":
            # Anthropic returns models in a different format
            # Use a simple approach: return the configured model + known variants
            return [
                "claude-sonnet-4-20250514",
                "claude-3-5-sonnet-20241022",
                "claude-3-5-sonnet-20240620",
                "claude-3-opus-20240229",
                "claude-3-sonnet-20240229",
                "claude-3-haiku-20240307",
                "claude-3-5-haiku-20241022",
            ]
        else:
            models = await self._fetch_models_cached()
            if models is not None:
                return models
            logger.warning(f"Failed to list models for {self._provider_name}; falling back to configured model")
            return [self._model]  # Fallback to current model

    # ─────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────────────

    async def close(self) -> None:
        """Gracefully close the HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> "OpenAICompatAdapter":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
