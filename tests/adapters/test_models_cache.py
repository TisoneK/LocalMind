"""
Regression tests for the OpenAI-compat /models TTL cache.

Health-check burst bug (2026-08-09): every `GET /api/health` fired a fresh
`GET {base_url}/models` — with wait-on x2, the 1.5s frontend poll, the 2s
Electron poll, and useModels all hitting /api/health + /api/models at
startup, that was 20+ identical Zen fetches in ~7s (see
`opencode.ai/zen/v1/models` in the dev log).

The cache is CLASS-level (mirrors OllamaAdapter) so even the throwaway
adapter instances created in routes/models.py share the cached result.
Successes are cached for ``_MODELS_CACHE_TTL`` seconds; failures are NOT
cached so a recovering provider is detected promptly.
"""

from __future__ import annotations

import asyncio

import pytest
from adapters.openai_compat import OpenAICompatAdapter


class FakeResponse:
    """Minimal httpx.Response stand-in with .status_code and .json()."""

    def __init__(self, status_code: int = 200, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {"data": [{"id": "model-a"}, {"id": "model-b"}]}

    def json(self) -> dict:
        return self._payload


class CountingClient:
    """Fake client that counts GET calls and returns canned responses."""

    def __init__(self, status_code: int = 200, payload: dict | None = None):
        self.calls = 0
        self.status_code = status_code
        self.payload = payload

    async def get(self, url: str, headers=None, timeout=None) -> FakeResponse:
        self.calls += 1
        return FakeResponse(self.status_code, self.payload)


@pytest.fixture(autouse=True)
def _reset_models_cache():
    """The cache is class-level — reset between tests to avoid bleed."""
    OpenAICompatAdapter.clear_models_cache()
    yield
    OpenAICompatAdapter.clear_models_cache()


def _make_adapter(monkeypatch, client: CountingClient, provider: str = "zen") -> OpenAICompatAdapter:
    monkeypatch.setenv("ZEN_API_KEY", "sk-fake-test-key")
    monkeypatch.setenv("CEREBRAS_API_KEY", "sk-fake-test-key")
    adapter = OpenAICompatAdapter(provider=provider, model_override="deepseek-v4-flash-free")
    adapter._client = client  # replace httpx client with the counting fake
    return adapter


def test_health_check_caches_models_fetch(monkeypatch):
    """Two health checks within TTL must only hit the /models endpoint once."""

    async def run():
        client = CountingClient()
        adapter = _make_adapter(monkeypatch, client)
        assert await adapter.health_check() is True
        assert await adapter.health_check() is True
        assert client.calls == 1

    asyncio.run(run())


def test_list_models_shares_cache_with_health_check(monkeypatch):
    """list_models() and health_check() share the same cached fetch."""

    async def run():
        client = CountingClient()
        adapter = _make_adapter(monkeypatch, client)
        models = await adapter.list_models()
        assert models == ["model-a", "model-b"]
        assert await adapter.health_check() is True
        # One fetch serves both callers.
        assert client.calls == 1

    asyncio.run(run())


def test_throwaway_instances_share_class_cache(monkeypatch):
    """Separate adapter instances (like routes/models.py creates) share the cache."""

    async def run():
        client = CountingClient()
        adapter_a = _make_adapter(monkeypatch, client, provider="zen")
        models = await adapter_a.list_models()
        assert models == ["model-a", "model-b"]

        # A brand-new instance with a fresh client must NOT re-fetch.
        client_b = CountingClient()
        adapter_b = _make_adapter(monkeypatch, client_b, provider="zen")
        assert await adapter_b.health_check() is True
        assert client_b.calls == 0

    asyncio.run(run())


def test_provider_key_isolation(monkeypatch):
    """Caches are keyed per-provider — zen and cerebras don't collide."""

    async def run():
        zen_client = CountingClient(payload={"data": [{"id": "zen-only"}]})
        zen_adapter = _make_adapter(monkeypatch, zen_client, provider="zen")
        await zen_adapter.list_models()

        cerebras_client = CountingClient(payload={"data": [{"id": "cerebras-only"}]})
        cerebras_adapter = _make_adapter(monkeypatch, cerebras_client, provider="cerebras")
        models = await cerebras_adapter.list_models()
        assert models == ["cerebras-only"]
        assert cerebras_client.calls == 1

    asyncio.run(run())


def test_cache_expires_after_ttl(monkeypatch):
    """After TTL elapses, the next call re-fetches."""

    async def run():
        client = CountingClient()
        adapter = _make_adapter(monkeypatch, client)
        assert await adapter.health_check() is True
        assert client.calls == 1

        # Simulate TTL expiry by backdating the cache timestamp.
        OpenAICompatAdapter._models_cache_ts["zen"] -= OpenAICompatAdapter._MODELS_CACHE_TTL + 1
        assert await adapter.health_check() is True
        assert client.calls == 2

    asyncio.run(run())


def test_concurrent_misses_collapse_to_single_fetch(monkeypatch):
    """Concurrent health checks (startup pollers firing in the same second)
    must serialize on the per-provider lock — one fetch, not a re-burst."""

    async def run():
        client = CountingClient()
        adapter = _make_adapter(monkeypatch, client)
        results = await asyncio.gather(
            adapter.health_check(),
            adapter.health_check(),
            adapter.health_check(),
        )
        assert results == [True, True, True]
        assert client.calls == 1

    asyncio.run(run())


def test_failure_not_cached(monkeypatch):
    """A failed fetch is NOT cached — the next call retries the provider."""

    async def run():
        client = CountingClient(status_code=500)
        adapter = _make_adapter(monkeypatch, client)
        assert await adapter.health_check() is False
        assert await adapter.health_check() is False
        # Every call re-attempts (no caching of failure).
        assert client.calls == 2

    asyncio.run(run())


def test_clear_models_cache_forces_refetch(monkeypatch):
    """clear_models_cache() invalidates even a fresh cache entry."""

    async def run():
        client = CountingClient()
        adapter = _make_adapter(monkeypatch, client)
        assert await adapter.health_check() is True
        assert client.calls == 1

        OpenAICompatAdapter.clear_models_cache("zen")
        assert await adapter.health_check() is True
        assert client.calls == 2

    asyncio.run(run())


def test_clear_adapter_cache_invalidates_models_cache(monkeypatch):
    """clear_adapter_cache() (settings save) must drop the models cache too."""

    async def run():
        from adapters import clear_adapter_cache

        client = CountingClient()
        adapter = _make_adapter(monkeypatch, client)
        assert await adapter.health_check() is True
        assert client.calls == 1

        clear_adapter_cache("zen")
        assert await adapter.health_check() is True
        assert client.calls == 2

    asyncio.run(run())
