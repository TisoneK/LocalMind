"""
B-2026-08-02-10 (C1) — per-agent model routing.

Covers the ModelRouter additions: parse_agent_spec, get_adapter_for_agent,
resolve_agent_adapter — env-var overrides, AgentConfig-declared fallback,
default (None) fallback, and the never-raises rule for bad overrides.
"""

from typing import ClassVar

import pytest
from agents.base_agent import AgentConfig, BaseAgent
from core.config import settings
from core.model_router import (
    AGENT_MODEL_ENV_PREFIX,
    get_adapter_for_agent,
    parse_agent_spec,
    resolve_agent_adapter,
)


@pytest.fixture(autouse=True)
def _clear_adapter_cache():
    """Adapter construction is cached module-globally; keep tests isolated.

    Some tests build real adapters (with fake API keys) — clearing after
    each test prevents a later test from reusing a stale instance.
    """
    yield
    from adapters import clear_adapter_cache

    clear_adapter_cache()


# ── parse_agent_spec ────────────────────────────────────────────────────────


def test_parse_spec_adapter_prefix():
    """'zen:deepseek-v4-pro' → (zen, deepseek-v4-pro)."""
    assert parse_agent_spec("zen:deepseek-v4-pro") == ("zen", "deepseek-v4-pro")


def test_parse_spec_ollama_prefix():
    """'ollama:qwen2.5:7b' → (ollama, qwen2.5:7b) — adapter split wins even
    though the model itself contains a colon."""
    assert parse_agent_spec("ollama:qwen2.5:7b") == ("ollama", "qwen2.5:7b")


def test_parse_spec_bare_model_uses_current_adapter():
    """'llama3.1:70b' → (current adapter, llama3.1:70b) — 'llama3.1' is not
    a known adapter, so the whole string is the model."""
    assert parse_agent_spec("llama3.1:70b") == (settings.localmind_adapter, "llama3.1:70b")


def test_parse_spec_blank_is_none():
    assert parse_agent_spec("") is None
    assert parse_agent_spec("   ") is None


def test_parse_spec_provider_collision_escape_hatch():
    """'mistral:7b' collides with the mistral PROVIDER (parses as cloud);
    the 'ollama:' prefix forces the LOCAL model. Pinned per the review
    finding — users must write ollama:mistral:7b for the local model."""
    assert parse_agent_spec("ollama:mistral:7b") == ("ollama", "mistral:7b")
    # Documented collision: base name == provider name → provider wins.
    assert parse_agent_spec("mistral:7b") == ("mistral", "7b")


# ── get_adapter_for_agent ───────────────────────────────────────────────────


def test_no_override_returns_none(monkeypatch):
    monkeypatch.delenv(f"{AGENT_MODEL_ENV_PREFIX}CODING", raising=False)
    assert get_adapter_for_agent("coding") is None
    assert get_adapter_for_agent("coding", config_model=None, config_adapter=None) is None


def test_env_override_bare_model(monkeypatch):
    """LOCALMIND_AGENT_MODEL_CODING=llama3.1:70b → an ollama adapter on that model."""
    monkeypatch.setenv(f"{AGENT_MODEL_ENV_PREFIX}CODING", "llama3.1:70b")
    adapter = get_adapter_for_agent("coding")
    assert adapter is not None
    assert getattr(adapter, "_model", "") == "llama3.1:70b"


def test_env_override_cloud_provider(monkeypatch):
    """LOCALMIND_AGENT_MODEL_RESEARCH=zen:deepseek-v4-pro → a zen adapter."""
    monkeypatch.setenv("ZEN_API_KEY", "test-key")
    monkeypatch.setenv(f"{AGENT_MODEL_ENV_PREFIX}RESEARCH", "zen:deepseek-v4-pro")
    adapter = get_adapter_for_agent("research")
    assert adapter is not None
    assert getattr(adapter, "_provider_key", "") == "zen"
    assert getattr(adapter, "_model", "") == "deepseek-v4-pro"


def test_config_fallback_without_env(monkeypatch):
    """AgentConfig-declared model is used when no env override exists."""
    monkeypatch.delenv(f"{AGENT_MODEL_ENV_PREFIX}DIRECT", raising=False)
    adapter = get_adapter_for_agent("direct", config_model="qwen2.5:1.5b")
    assert adapter is not None
    assert getattr(adapter, "_model", "") == "qwen2.5:1.5b"


def test_config_adapter_without_model(monkeypatch):
    """config_adapter with no model → the provider's configured/default model."""
    monkeypatch.setenv("ZEN_API_KEY", "test-key")
    monkeypatch.delenv(f"{AGENT_MODEL_ENV_PREFIX}BROWSER", raising=False)
    adapter = get_adapter_for_agent("browser", config_adapter="zen")
    assert adapter is not None
    assert getattr(adapter, "_provider_key", "") == "zen"


def test_bad_override_falls_back_to_none(monkeypatch):
    """Unknown adapter (config path) → logs a warning, returns None, never raises."""
    monkeypatch.delenv(f"{AGENT_MODEL_ENV_PREFIX}CODING", raising=False)
    assert get_adapter_for_agent("coding", config_adapter="nosuchprovider") is None


def test_missing_api_key_falls_back_to_none(monkeypatch):
    """Cloud override without an API key → None (fall back), never raises."""
    monkeypatch.delenv("ZEN_API_KEY", raising=False)
    monkeypatch.setenv(f"{AGENT_MODEL_ENV_PREFIX}CODING", "zen:deepseek-v4-pro")
    assert get_adapter_for_agent("coding") is None


# ── resolve_agent_adapter (the BaseAgent call site) ─────────────────────────


def test_resolve_fallback_when_no_override(monkeypatch):
    monkeypatch.delenv(f"{AGENT_MODEL_ENV_PREFIX}CODING", raising=False)
    sentinel = object()
    assert resolve_agent_adapter("coding", fallback=sentinel) is sentinel


def test_resolve_routed_when_override(monkeypatch):
    monkeypatch.setenv(f"{AGENT_MODEL_ENV_PREFIX}CODING", "llama3.1:70b")
    sentinel = object()
    resolved = resolve_agent_adapter("coding", fallback=sentinel)
    assert resolved is not sentinel
    assert getattr(resolved, "_model", "") == "llama3.1:70b"


# ── BaseAgent.run() wiring (review item: loop must receive the routed adapter) ──


class _StubAgent(BaseAgent):
    """Minimal concrete BaseAgent for the wiring test — never calls a model."""

    def config(self):
        return AgentConfig(name="stub")

    def build_context(self, **kwargs):
        return ""

    def is_done(self, **kwargs):
        return True, "done"

    def description(self):
        return "stub"


class _FakeLoop:
    """Records the adapter it was built with and the run() kwargs, yields nothing."""

    instances: ClassVar[list] = []

    def __init__(self, adapter):
        self.adapter = adapter
        _FakeLoop.instances.append(self)

    async def run(self, **kwargs):
        self.run_kwargs = kwargs
        return
        yield  # pragma: no cover — makes run() an async generator


@pytest.mark.asyncio
async def test_base_agent_run_passes_routed_adapter_to_loop(monkeypatch):
    """BaseAgent.run() must pass the routed adapter to BOTH AgentLoop
    construction and loop.run() — the review-identified wiring gap."""
    import core.agent.loop as loop_mod
    import core.model_router as router_mod

    sentinel = object()
    monkeypatch.setattr(loop_mod, "AgentLoop", _FakeLoop)
    monkeypatch.setattr(router_mod, "resolve_agent_adapter", lambda *a, **k: sentinel)
    _FakeLoop.instances.clear()

    from core.models import Intent

    agent = _StubAgent(adapter=object())
    async for _chunk in agent.run(
        messages=[],
        intent=Intent.CHAT,
        initial_tool_result=None,
        available_tools=[],
    ):
        pass  # _FakeLoop yields nothing — the wiring is what we assert

    assert _FakeLoop.instances, "AgentLoop was never constructed"
    loop = _FakeLoop.instances[-1]
    assert loop.adapter is sentinel
    assert loop.run_kwargs["adapter"] is sentinel
