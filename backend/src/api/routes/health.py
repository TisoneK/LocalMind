"""Health check endpoint."""

from __future__ import annotations

import time as _time

from fastapi import APIRouter
from pydantic import BaseModel

from adapters import get_adapter
from core.cache import TTLCache
from core.config import settings
from tools import available_tools

router = APIRouter()

# Track actual server start time for accurate uptime reporting
_SERVER_START = _time.time()

# Cache Ollama reachability to avoid hitting /api/tags on every health poll.
# The frontend polls /api/health every 1.5s during startup (useHealth hook)
# and the Electron main process polls every 2s. Without caching that's
# ~40 HTTP requests to Ollama per minute even when idle.
#
# Previous 30s TTL was too short — the frontend keeps polling even after
# engine_ready=true (StatusBar displays health status). With 60s TTL we
# reduce Ollama /api/tags calls to ~1 per minute while still detecting
# Ollama going down within 60s.
_reachability_cache = TTLCache(ttl_seconds=60.0, max_entries=1)  # was 30s


class HealthResponse(BaseModel):
    status: str
    provider_reachable: bool
    engine_ready: bool
    # ADR-52 phase 2: distinct parent-kernel readiness (separate from
    # engine_ready, which only tracks startup completion). parent_ready
    # is True when the boot kernel is built and not in a degraded state;
    # parent_degraded_reason carries the warmup failure string when set.
    parent_ready: bool = False
    parent_degraded_reason: str = ""
    model: str
    adapter: str
    tools: list[dict]
    version: str = "0.4.0-dev"
    uptime: float = 0


# Set to True by app.py once engine.startup() completes.
_engine_ready: bool = False


def set_engine_ready() -> None:
    global _engine_ready
    _engine_ready = True


@router.get("/health", response_model=HealthResponse)
async def health():
    # Use cached value if still within TTL
    reachable = _reachability_cache.get("provider")
    if reachable is None:
        try:
            adapter = get_adapter(settings.localmind_adapter)
            reachable = await adapter.health_check()
        except Exception:
            reachable = False
        _reachability_cache.set("provider", reachable)

    uptime = round(_time.time() - _SERVER_START, 2)

    # Get model based on adapter
    adapter_name = settings.localmind_adapter
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
        # ADR-9: ZenMux — IMPLEMENTED BUT UNTESTED (smoke test blocked).
        "zenmux": settings.zenmux_model,
    }
    current_model = model_setting_map.get(adapter_name) or settings.ollama_model

    # ADR-52 phase 2: surface the parent kernel's distinct readiness state.
    # ``engine_ready`` only confirms startup completed; ``parent_ready``
    # confirms the boot kernel built without a degraded_reason (provider
    # warmup succeeded). The two can differ when a cloud provider is down
    # at boot — the engine is up but the parent is degraded until the first
    # turn's lazy retry recovers it.
    from api.routes.chat import _engine

    parent_ready = bool(getattr(_engine, "parent_ready", False))
    parent_degraded_reason = str(getattr(_engine, "parent_degraded_reason", "") or "")

    # Overall status: ok requires provider reachable, engine ready, AND
    # parent ready. A degraded parent still serves requests (lazy retry),
    # but the status reflects that something is wrong.
    overall_ok = reachable and _engine_ready and parent_ready
    return HealthResponse(
        status="ok" if overall_ok else "degraded",
        provider_reachable=reachable,
        engine_ready=_engine_ready,
        parent_ready=parent_ready,
        parent_degraded_reason=parent_degraded_reason,
        model=current_model,
        adapter=adapter_name,
        tools=available_tools(),
        uptime=uptime,
    )
