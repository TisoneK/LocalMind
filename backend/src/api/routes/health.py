"""Health check endpoint."""
from __future__ import annotations
from fastapi import APIRouter
from pydantic import BaseModel
from adapters import get_adapter
from core.config import settings
from tools import available_tools

import time as _time

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
_REACHABILITY_CACHE_TTL = 60  # seconds (was 30)
_cached_reachable: bool = False
_cached_reachable_at: float = 0.0


class HealthResponse(BaseModel):
    status: str
    provider_reachable: bool
    engine_ready: bool
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
    global _cached_reachable, _cached_reachable_at

    now = _time.time()
    # Use cached value if still within TTL
    if now - _cached_reachable_at < _REACHABILITY_CACHE_TTL:
        reachable = _cached_reachable
    else:
        try:
            adapter = get_adapter(settings.localmind_adapter)
            reachable = await adapter.health_check()
            _cached_reachable = reachable
            _cached_reachable_at = now
        except Exception:
            reachable = False
            _cached_reachable = False
            _cached_reachable_at = now

    uptime = round(now - _SERVER_START, 2)

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
    }
    current_model = model_setting_map.get(adapter_name) or settings.ollama_model

    return HealthResponse(
        status="ok" if reachable and _engine_ready else "degraded",
        provider_reachable=reachable,
        engine_ready=_engine_ready,
        model=current_model,
        adapter=adapter_name,
        tools=available_tools(),
        uptime=uptime
    )
