"""Embedding backend fallback — a missing local Ollama must not silently
disable memory when a cloud embedder is configured, and it must never mix
two embedding spaces in one vec0 index.

Before this fix, `VectorStore` could embed through exactly one backend (the
local Ollama /api/embeddings endpoint).  When Ollama was not running, every
embed call warned "[embed] Failed: All connection attempts failed" and
returned None — facts were never stored and recall always returned [], with
nothing surfacing the cause to the user.

The fix is bind-time backend selection, NOT per-call fallback: one index
holds one embedding space, and vectors from different models are not
comparable even at equal dimensions.  So:

  * default (no cloud configured) == historical behavior, zero change;
  * Ollama unreachable + a usable cloud config -> the store binds the cloud
    backend for its lifetime (fresh or empty index only);
  * an index already holding another backend's vectors is refused, never
    blended;
  * both cache tiers are namespaced by backend identity so a cloud vector
    can never poison an Ollama-keyed entry.

All tests are hermetic: HTTP is faked at the httpx boundary, nothing touches
a real Ollama or cloud provider.
"""

from __future__ import annotations

import asyncio
import hashlib
import os

import pytest

os.environ.setdefault("LOCALMIND_HOME", ".")

import httpx

import storage.vector as v
from core.config import settings


def _vec_for(text: str, dim: int = 8) -> list[float]:
    """Deterministic pseudo-embedding: one signed hash byte per dimension.
    Signed components keep distinct texts near-orthogonal (an all-positive
    generator would leave every pair cosine ~0.9 and the store's dedup guard
    would merge unrelated facts); identical texts reproduce themselves."""
    return [
        (hashlib.sha256(f"{text}|{i}".encode()).digest()[0] - 127) / 128.0
        for i in range(dim)
    ]


class _FakeResp:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = ""

    def json(self) -> dict:
        return self._payload


class _FakeNet:
    """Routes POSTs by endpoint shape and records every call.

    /api/embeddings -> Ollama contract (prompt/embedding)
    /embeddings     -> OpenAI-compatible cloud contract (input/data[0].embedding)
    """

    def __init__(self, ollama_up: bool = True, cloud_up: bool = True, cloud_dim: int = 8):
        self.ollama_up = ollama_up
        self.cloud_up = cloud_up
        self.cloud_dim = cloud_dim
        self.calls: list[tuple[str, dict, dict]] = []  # (url, body, headers)

    def handle(self, url: str, body: dict, headers: dict | None = None):
        self.calls.append((url, body, headers or {}))
        if url.endswith("/api/embeddings"):
            if not self.ollama_up:
                raise httpx.ConnectError("All connection attempts failed")
            return _FakeResp({"embedding": _vec_for(body.get("prompt", ""))})
        if not self.cloud_up:
            raise httpx.ConnectError("All connection attempts failed")
        return _FakeResp({"data": [{"embedding": _vec_for(body.get("input", ""), self.cloud_dim)}]})

    async def post(self, url, json=None, headers=None, **kw):
        return self.handle(url, json or {}, headers)

    def sync_post(self, url, json=None, headers=None, timeout=None):
        return self.handle(url, json or {}, headers)

    def embed_calls(self):
        """POST calls that are real embed requests (probes use 'dim_probe')."""
        return [c for c in self.calls if c[1].get("prompt") != "dim_probe" and c[1].get("input") != "dim_probe"]

    @property
    def cloud_embed_calls(self):
        return [c for c in self.embed_calls() if c[0].endswith("/embeddings") and "/api/" not in c[0]]

    @property
    def ollama_embed_calls(self):
        return [c for c in self.embed_calls() if c[0].endswith("/api/embeddings")]


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    """Reset module-level backend state between tests (the LRU and the
    process-wide cloud-bind flag are shared by design within a session)."""
    monkeypatch.setattr(v, "_USE_CLOUD", False)
    v._embed_cached.cache_clear()
    # Neutral defaults: Ollama-only unless a test opts in.
    monkeypatch.setattr(settings, "localmind_embed_adapter", "")
    monkeypatch.setattr(settings, "localmind_embed_base_url", "")
    monkeypatch.setattr(settings, "localmind_embed_model", "")
    monkeypatch.setattr(settings, "localmind_embed_key_provider", "openai")
    monkeypatch.setattr(settings, "_runtime_api_keys", {}, raising=False)
    monkeypatch.setattr(settings, "ollama_embed_model", "test-embed")
    # Pin the Ollama URL — the settings singleton may have loaded a real
    # settings.json before the test process started.
    monkeypatch.setattr(settings, "ollama_base_url", "http://localhost:11434")
    yield
    v._embed_cached.cache_clear()


def _wire(monkeypatch, net: _FakeNet):
    """Route every embed HTTP path (sync and async) through the fake."""
    monkeypatch.setattr(v.httpx, "post", net.sync_post)

    async def _client():
        return net

    monkeypatch.setattr(v, "_get_async_client", _client)


def _make_store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "localmind_db_path", str(tmp_path / "localmind.db"))
    return v.VectorStore(db_path=str(tmp_path / "localmind.db"))


def _configure_cloud(monkeypatch, net_url="http://embed.test/v1"):
    monkeypatch.setattr(settings, "localmind_embed_adapter", "openai")
    monkeypatch.setattr(settings, "localmind_embed_base_url", net_url)
    monkeypatch.setattr(settings, "localmind_embed_model", "stub-embed-1")
    monkeypatch.setattr(settings, "localmind_embed_key_provider", "stubprov")
    settings._runtime_api_keys["stubprov"] = "test-key-123"


# ── (a) Default config == historical behavior, exactly ────────────────────────


class TestDefaultUnchanged:
    def test_ollama_up_no_cloud_pure_ollama(self, tmp_path, monkeypatch):
        """adapter "" + Ollama reachable: every embed hits Ollama, memory works,
        no cloud call is ever attempted."""
        net = _FakeNet(ollama_up=True)
        _wire(monkeypatch, net)
        store = _make_store(tmp_path, monkeypatch)

        assert store._ready is True
        assert asyncio.run(store.store("User likes dark mode", "s1")) is True
        results = asyncio.run(store.recall("dark mode"))
        assert "User likes dark mode" in results
        assert net.ollama_embed_calls, "expected Ollama embed calls"
        assert not net.cloud_embed_calls, "cloud must never be called when unconfigured"
        assert v._USE_CLOUD is False

    def test_ollama_down_no_cloud_offline_as_before(self, tmp_path, monkeypatch):
        """The pre-fix bug scenario with no cloud configured: memory stays
        offline (store False, recall []) — no crash, no cloud attempt either."""
        net = _FakeNet(ollama_up=False)
        _wire(monkeypatch, net)
        store = _make_store(tmp_path, monkeypatch)

        assert asyncio.run(store.store("User likes dark mode", "s1")) is False
        assert asyncio.run(store.recall("dark mode")) == []
        assert not net.cloud_embed_calls
        assert v._USE_CLOUD is False


# ── (b) Ollama down + cloud configured == facts still store ──────────────────


class TestCloudFailover:
    def test_fresh_index_binds_cloud_and_stores(self, tmp_path, monkeypatch):
        """THE fix: Ollama unreachable at startup, cloud embedder configured ->
        the store binds cloud, the first fact stores, and recall works."""
        net = _FakeNet(ollama_up=False)
        _wire(monkeypatch, net)
        _configure_cloud(monkeypatch)
        store = _make_store(tmp_path, monkeypatch)

        assert store._ready is True
        assert v._USE_CLOUD is True
        assert asyncio.run(store.store("User likes dark mode", "s1")) is True
        assert asyncio.run(store.store("User prefers vim keybindings", "s1")) is True
        results = asyncio.run(store.recall("dark mode"))
        assert "User likes dark mode" in results

        # Cloud contract: POST {base}/embeddings, body {model, input}, Bearer key.
        calls = net.cloud_embed_calls
        assert calls, "expected cloud embed calls"
        url, body, headers = calls[0]
        assert url == "http://embed.test/v1/embeddings"
        assert body["model"] == "stub-embed-1"
        assert "input" in body and "prompt" not in body
        assert headers.get("Authorization") == "Bearer test-key-123"
        # Every post-bind embed went to cloud — none leaked back to Ollama.
        assert not net.ollama_embed_calls

    def test_backend_stays_fixed_when_ollama_recovers(self, tmp_path, monkeypatch):
        """One index, one space: Ollama coming back mid-session must NOT flip
        the backend — later facts keep the cloud space the index started in."""
        net = _FakeNet(ollama_up=False)
        _wire(monkeypatch, net)
        _configure_cloud(monkeypatch)
        store = _make_store(tmp_path, monkeypatch)
        asyncio.run(store.store("fact one", "s1"))

        net.ollama_up = True  # Ollama "restarts" mid-session
        asyncio.run(store.store("fact two", "s1"))

        assert v._USE_CLOUD is True
        assert not net.ollama_embed_calls, "backend flipped mid-session — index would be corrupt"
        assert len(net.cloud_embed_calls) >= 2

    def test_cloud_unusable_without_key_falls_back_to_offline(self, tmp_path, monkeypatch):
        """Adapter set but no resolvable key: every cloud call would 401, so the
        store must not bind — memory stays offline exactly as before."""
        net = _FakeNet(ollama_up=False)
        _wire(monkeypatch, net)
        _configure_cloud(monkeypatch)
        settings._runtime_api_keys.pop("stubprov")  # no key anywhere

        store = _make_store(tmp_path, monkeypatch)
        assert v._USE_CLOUD is False
        assert asyncio.run(store.store("User likes dark mode", "s1")) is False

    def test_tool_result_index_shares_bound_backend(self, tmp_path, monkeypatch):
        """The other _embed_async caller (tool-result index) must embed through
        the same bound backend — its vectors live in the same space."""
        net = _FakeNet(ollama_up=False)
        _wire(monkeypatch, net)
        _configure_cloud(monkeypatch)
        _make_store(tmp_path, monkeypatch)  # binds cloud process-wide

        vec = asyncio.run(v._embed_async("some tool output", settings.ollama_base_url))
        assert vec is not None
        assert not net.ollama_embed_calls
        assert net.cloud_embed_calls


# ── (d) Space guard: a populated index is never blended ──────────────────────


class TestSpaceGuard:
    def test_ollama_era_index_refuses_cloud(self, tmp_path, monkeypatch):
        """Facts stored via Ollama, then a restart with Ollama down + cloud
        configured: the cloud backend must NOT write the Ollama-space index —
        same dim or not, the vectors are not comparable."""
        net = _FakeNet(ollama_up=True)
        _wire(monkeypatch, net)
        store = _make_store(tmp_path, monkeypatch)
        assert asyncio.run(store.store("User likes dark mode", "s1")) is True

        # "Restart": Ollama down, cloud configured, SAME dim (8) — the
        # dangerous case a dim check alone would wave through.
        net2 = _FakeNet(ollama_up=False, cloud_dim=8)
        _wire(monkeypatch, net2)
        _configure_cloud(monkeypatch)
        v._embed_cached.cache_clear()
        monkeypatch.setattr(v, "_USE_CLOUD", False)
        store2 = v.VectorStore(db_path=str(tmp_path / "localmind.db"))

        assert v._USE_CLOUD is False, "cloud bound itself onto an Ollama-space index"
        assert asyncio.run(store2.store("new fact", "s2")) is False
        assert not net2.cloud_embed_calls

    def test_cloud_era_index_refuses_ollama(self, tmp_path, monkeypatch):
        """Mirror case: an index started on cloud must not accept Ollama
        vectors later, even when Ollama is back and dims match."""
        net = _FakeNet(ollama_up=False)
        _wire(monkeypatch, net)
        _configure_cloud(monkeypatch)
        store = _make_store(tmp_path, monkeypatch)
        assert asyncio.run(store.store("cloud fact", "s1")) is True

        # "Restart": Ollama back up; cloud config REMOVED (Ollama-only again).
        net2 = _FakeNet(ollama_up=True)
        _wire(monkeypatch, net2)
        monkeypatch.setattr(settings, "localmind_embed_adapter", "")
        v._embed_cached.cache_clear()
        monkeypatch.setattr(v, "_USE_CLOUD", False)
        store2 = v.VectorStore(db_path=str(tmp_path / "localmind.db"))

        assert store2._ready is False, "Ollama extended a cloud-space index"
        assert store2._dim_mismatch is not None
        assert asyncio.run(store2.store("ollama fact", "s2")) is False
        # The stored cloud facts survive untouched for the next cloud session.
        conn = store2._connect()
        assert conn.execute("SELECT COUNT(*) FROM vector_facts").fetchone()[0] == 1

    def test_cloud_restart_continuity_keeps_memory_alive(self, tmp_path, monkeypatch):
        """Ollama down across two restarts with the SAME cloud config: the
        second start must re-bind and keep storing (same space, tracked id)."""
        net = _FakeNet(ollama_up=False)
        _wire(monkeypatch, net)
        _configure_cloud(monkeypatch)
        store = _make_store(tmp_path, monkeypatch)
        assert asyncio.run(store.store("first session fact", "s1")) is True

        v._embed_cached.cache_clear()
        monkeypatch.setattr(v, "_USE_CLOUD", False)
        store2 = v.VectorStore(db_path=str(tmp_path / "localmind.db"))
        assert v._USE_CLOUD is True
        assert asyncio.run(store2.store("second session fact", "s2")) is True
        results = asyncio.run(store2.recall("first session"))
        assert "first session fact" in results

    def test_dim_mismatch_cloud_probe_refuses_bind(self, tmp_path, monkeypatch):
        """Empty-but-dimensioned index + cloud at a different dim: the bind
        re-keys the empty index rather than refusing (nothing to corrupt);
        a NON-empty one is refused. Cover the refusal via a stored fact."""
        net = _FakeNet(ollama_up=True)
        _wire(monkeypatch, net)
        store = _make_store(tmp_path, monkeypatch)
        asyncio.run(store.store("fact", "s1"))

        net2 = _FakeNet(ollama_up=False, cloud_dim=4)
        _wire(monkeypatch, net2)
        _configure_cloud(monkeypatch)
        v._embed_cached.cache_clear()
        monkeypatch.setattr(v, "_USE_CLOUD", False)
        store2 = v.VectorStore(db_path=str(tmp_path / "localmind.db"))
        assert v._USE_CLOUD is False
        assert asyncio.run(store2.store("another", "s2")) is False


# ── (e) Cache tiers are namespaced by backend identity ───────────────────────


class TestCacheNamespacing:
    def test_backend_id_distinguishes_providers(self):
        a = v._backend_id("ollama", "http://localhost:11434", "nomic-embed-text")
        b = v._backend_id("cloud", "http://localhost:11434", "nomic-embed-text")
        c = v._backend_id("cloud", "http://other.test/v1", "nomic-embed-text")
        assert a != b != c and a != c

    def test_persistent_cache_no_cross_poisoning(self, tmp_path, monkeypatch):
        """A vector persisted under one backend must be invisible to the other.

        Both cache tiers are namespaced by backend identity: the instance tier
        (_write_persistent/_read_persistent via _pkey) and the module tier
        (_get_persistent_cache/_safe_persist_async) — historically distinct key
        derivations over the same table, each verified here on its own path.
        """
        net = _FakeNet(ollama_up=True)
        _wire(monkeypatch, net)
        store = _make_store(tmp_path, monkeypatch)
        text = "User likes dark mode"
        norm = v._normalise_text(text)

        vec = v._normalise(_vec_for(text))
        store._write_persistent(norm, vec)
        store.flush_write_buf()
        assert store._read_persistent(norm) is not None  # same backend: hit

        # Flip the bound backend — the same text must now miss, not return the
        # Ollama vector under a cloud key.
        monkeypatch.setattr(v, "_USE_CLOUD", True)
        monkeypatch.setattr(settings, "localmind_embed_base_url", "http://embed.test/v1")
        monkeypatch.setattr(settings, "localmind_embed_model", "stub-embed-1")
        assert store._read_persistent(norm) is None
        monkeypatch.setattr(v, "_USE_CLOUD", False)

        # Module tier: persist through the ollama backend id, read by id.
        backend_ollama = v._backend_id("ollama", settings.ollama_base_url, "test-embed")
        backend_cloud = v._backend_id("cloud", "http://embed.test/v1", "stub-embed-1")
        asyncio.run(v._safe_persist_async(norm, backend_ollama, tuple(vec)))
        assert v._get_persistent_cache(norm, backend_ollama) is not None
        assert v._get_persistent_cache(norm, backend_cloud) is None

    def test_lru_keyed_by_backend(self, tmp_path, monkeypatch):
        """The LRU tier keys on (text, mode, url, model) — same text through a
        different backend is a cache miss, not a poisoned hit."""
        net = _FakeNet(ollama_up=True, cloud_up=True)
        _wire(monkeypatch, net)
        norm = v._normalise_text("hello world")
        o = v._embed_cached(norm, "ollama", "http://localhost:11434", "test-embed")
        c = v._embed_cached(norm, "cloud", "http://embed.test/v1", "stub-embed-1")
        # Both fetched independently (two backend-keyed entries, one text).
        assert o and c
        assert tuple(_vec_for("hello world")) == o  # Ollama contract vector
        info = v._embed_cached.cache_info()
        assert info.currsize == 2


# ── Config plumbing: settings.json persistence + env names ───────────────────


class TestConfigPersistence:
    def test_runtime_settings_load_embed_keys(self, tmp_path, monkeypatch):
        import json

        path = tmp_path / "settings.json"
        path.write_text(
            json.dumps(
                {
                    "embed_adapter": "openai",
                    "embed_base_url": "http://gw.local/v1",
                    "embed_cloud_model": "some-embed",
                    "embed_key_provider": "ZAI",
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(settings, "_runtime_settings_path", lambda: path)
        settings.load_runtime_settings()
        assert settings.localmind_embed_adapter == "openai"
        assert settings.localmind_embed_base_url == "http://gw.local/v1"
        assert settings.localmind_embed_model == "some-embed"
        assert settings.localmind_embed_key_provider == "zai"

    def test_runtime_settings_ignores_invalid_adapter(self, tmp_path, monkeypatch):
        import json

        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"embed_adapter": "telepathy"}), encoding="utf-8")
        monkeypatch.setattr(settings, "_runtime_settings_path", lambda: path)
        settings.load_runtime_settings()
        assert settings.localmind_embed_adapter == ""  # default preserved

    def test_cloud_base_url_defaults_to_provider_registry(self, monkeypatch):
        """No explicit base URL: resolve from the key provider's registry entry."""
        monkeypatch.setattr(settings, "localmind_embed_key_provider", "openai")
        monkeypatch.setattr(settings, "localmind_embed_base_url", "")
        base, _, _ = v._cloud_embed_config()
        assert base == "https://api.openai.com/v1"
