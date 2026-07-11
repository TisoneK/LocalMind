"""
Adapter registry. Maps adapter names to classes.
Set LOCALMIND_ADAPTER in .env to switch runtimes.
"""

from adapters.base import BaseAdapter

# FIX: cache adapter instances to avoid creating a new httpx.AsyncClient
# per request (which leaks TCP connections). Key is (name, model_override).
_adapter_cache: dict[tuple, "BaseAdapter"] = {}


def get_adapter(name: str, model_override: str = "") -> BaseAdapter:
    cache_key = (name, model_override)
    if cache_key not in _adapter_cache:
        if name == "ollama":
            from adapters.ollama import OllamaAdapter

            _adapter_cache[cache_key] = OllamaAdapter(model_override=model_override)
        else:
            # All non-ollama adapters are OpenAI-compatible. The valid names
            # are derived from PROVIDER_CONFIGS — no hardcoded list to drift.
            from adapters.openai_compat import CLOUD_PROVIDER_NAMES

            if name in CLOUD_PROVIDER_NAMES:
                from adapters.openai_compat import OpenAICompatAdapter

                _adapter_cache[cache_key] = OpenAICompatAdapter(provider=name, model_override=model_override)
            else:
                raise ValueError(
                    f"Unknown adapter: '{name}'. Available: ollama, "
                    + ", ".join(CLOUD_PROVIDER_NAMES)
                )
    return _adapter_cache[cache_key]


def clear_adapter_cache(name: str = None) -> None:
    """Clear adapter cache. If name provided, only clear that adapter's entries."""
    global _adapter_cache
    if name is None:
        _adapter_cache.clear()
    else:
        _adapter_cache = {k: v for k, v in _adapter_cache.items() if k[0] != name}


async def close_all_adapters() -> None:
    """Gracefully close all cached adapter HTTP clients. Call from app lifespan teardown."""
    for adapter in _adapter_cache.values():
        if hasattr(adapter, "_client") and hasattr(adapter._client, "aclose"):
            try:
                await adapter._client.aclose()
            except Exception:
                pass
    _adapter_cache.clear()
