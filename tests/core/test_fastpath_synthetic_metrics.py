"""Regression: the fast path must not fabricate provider metrics.

Live evidence: a "How are you?" turn (pre-fix) was answered with the verbatim
canned greeting AND reported promptTokens 5/8, 4ms latency, 4250 tok/s — the
"tokens" were local string-length estimates for a reply that never touched a
model. The sidebar aggregates inherit those numbers, so one canned turn
pollutes the session's average speed/latency stats (the S431 export
reconciled the pollution arithmetically across all four aggregates).

Contract locked here (updated when the canned path became the FALLBACK):
  - a healthy-provider social turn goes through the MODEL (one call) and its
    real usage flows through untouched — no synthetic flag on the happy path;
  - the canned strings are the degraded path only (provider unreachable/
    empty stream): those chunks stream usage={synthetic: True} — no token
    numbers that could be mistaken for provider data;
  - the runtime epilog persists {prompt_tokens: 0, completion_tokens: 0,
    latency_ms: real, synthetic: True} for synthetic turns and sends
    provider_usage={} on turn_complete;
  - the Session 111 display contract survives: tokens_approx /
    prompt_tokens_approx stay nonzero on synthetic turns.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.obs import ObsCollector
from core.trivial_input import _SOCIAL_REPLIES, trivial_response


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    """AgentRuntime with every write pointed at an isolated tmp home."""
    from core import config
    from core.engine import AgentRuntime
    from storage.db import SessionStore

    monkeypatch.setattr(config.settings, "localmind_home", str(tmp_path), raising=False)
    monkeypatch.setattr(
        config.settings, "localmind_db_path", str(tmp_path / "test.db"), raising=False
    )
    rt = AgentRuntime()
    rt._store = SessionStore(str(tmp_path / "test.db"))
    rt._memory = _NoMemory()
    rt._last_observation = {}
    return rt


class _NoMemory:
    async def list_all_with_metadata(self):
        return []


async def _collect(agen) -> list:
    return [c async for c in agen]


def patch_adapter(adapter):
    import unittest.mock as mock

    return mock.patch("core.engine.get_adapter", return_value=adapter)


class TestCannedUsageIsSynthetic:
    @pytest.mark.asyncio
    async def test_model_greeting_keeps_real_usage_no_synthetic_flag(self):
        """Healthy path: the greeting goes through the model — real provider
        usage flows through, no synthetic flag anywhere."""

        async def chat(messages, intent="chat", **kwargs):
            yield MagicMock(text="Hey! How's it going?", done=False, usage={"prompt_tokens": 25})
            yield MagicMock(text="", done=True, usage={"prompt_tokens": 25, "completion_tokens": 8})

        adapter = MagicMock()
        adapter.chat = chat
        chunks = await _collect(trivial_response("Hi", adapter))
        text = "".join(c.text for c in chunks if getattr(c, "text", ""))
        assert "going" in text
        done = next(c for c in chunks if c.done)
        assert "synthetic" not in (done.usage or {})
        assert done.usage.get("prompt_tokens") == 25

    @pytest.mark.asyncio
    async def test_canned_fallback_streams_synthetic_usage_no_tokens(self):
        """Degraded path (provider unreachable): the canned reply's chunks
        carry the synthetic flag, no token counts."""
        adapter = MagicMock()

        async def exploding_chat(messages, intent="chat", **kwargs):
            raise ConnectionError("provider unreachable")
            yield  # pragma: no cover

        adapter.chat = exploding_chat
        chunks = await _collect(trivial_response("Hi", adapter))
        canned = _SOCIAL_REPLIES["greeting"]
        assert chunks[0].text == canned
        assert chunks[0].usage == {"synthetic": True}
        done = next(c for c in chunks if c.done)
        assert done.usage == {"synthetic": True}
        assert "prompt_tokens" not in done.usage
        assert "completion_tokens" not in done.usage

    @pytest.mark.asyncio
    async def test_conversational_branch_still_forwards_provider_usage(self):
        """Real model calls keep their provider usage untouched."""

        async def chat(messages, intent="chat", **kwargs):
            yield MagicMock(text="hi there", done=False, usage={"prompt_tokens": 300})
            yield MagicMock(text="", done=True, usage={"prompt_tokens": 300, "completion_tokens": 5})

        adapter = MagicMock()
        adapter.chat = chat
        chunks = await _collect(
            trivial_response("yes", adapter)  # yes_no → LLM leg of trivial_response
        )
        done = next(c for c in chunks if c.done)
        assert done.usage.get("prompt_tokens") == 300


class TestEpilogPersistsHonestMetrics:
    @pytest.mark.asyncio
    async def test_provider_down_greeting_persists_synthetic_metrics_and_empty_provider_usage(self, runtime):
        """Degraded turn (provider unreachable): the greeting falls back to
        the canned line; persisted metrics are zeros + synthetic,
        provider_usage={}, while the approx display fields stay nonzero
        (Session 111 contract)."""
        sid = "sess-synth-canned"
        adapter = MagicMock()
        adapter.thinking_enabled = False

        async def exploding_chat(messages, intent="chat", **kwargs):
            raise ConnectionError("provider unreachable")
            yield  # pragma: no cover

        adapter.chat = exploding_chat
        adapter.chat_with_tools.side_effect = AssertionError("fast path must not use tools")

        with patch_adapter(adapter):
            chunks = await _collect(runtime.process("Hi", sid, obs=ObsCollector()))

        text = "".join(getattr(c, "text", "") or "" for c in chunks)
        assert text == _SOCIAL_REPLIES["greeting"]

        assistant = [
            m for m in runtime._store.get_history(sid) if m.role.value == "assistant"
        ]
        assert len(assistant) == 1
        metrics = assistant[0].metrics
        assert metrics["prompt_tokens"] == 0
        assert metrics["completion_tokens"] == 0
        assert metrics["synthetic"] is True
        assert metrics["latency_ms"] >= 0

    @pytest.mark.asyncio
    async def test_degraded_greeting_display_approx_fields_stay_nonzero(self, runtime):
        """The Observe-panel contract: tokens_approx > 0 on a fallback
        greeting turn."""
        obs = ObsCollector()
        sid = "sess-synth-approx"
        adapter = MagicMock()
        adapter.thinking_enabled = False

        async def exploding_chat(messages, intent="chat", **kwargs):
            raise ConnectionError("provider unreachable")
            yield  # pragma: no cover

        adapter.chat = exploding_chat
        adapter.chat_with_tools.side_effect = AssertionError("fast path must not use tools")

        with patch_adapter(adapter):
            await _collect(runtime.process("Hi", sid, obs=obs))

        completes = [e for e in obs.history() if e.type == "turn_complete"]
        assert len(completes) == 1
        data = completes[0].data
        assert data["tokens_approx"] > 0
        assert data["prompt_tokens_approx"] > 0
        # And no fabricated provider usage reached the SSE surface.
        assert data.get("provider_usage", {}) == {}

    @pytest.mark.asyncio
    async def test_conversational_turn_keeps_real_usage_and_no_synthetic_flag(self, runtime):
        """A real model call persists token metrics WITHOUT the synthetic flag."""
        sid = "sess-synth-conv"

        async def chat(messages, intent="chat", **kwargs):
            yield MagicMock(text="I can help with files, web research, and code.", done=False,
                            usage={"prompt_tokens": 432, "completion_tokens": 87})
            yield MagicMock(text="", done=True,
                            usage={"prompt_tokens": 432, "completion_tokens": 87})

        adapter = MagicMock()
        adapter.thinking_enabled = False
        adapter.chat = chat

        with patch_adapter(adapter):
            await _collect(
                runtime.process("What can you do?", sid, obs=ObsCollector(), client_intent="chat")
            )

        assistant = [
            m for m in runtime._store.get_history(sid) if m.role.value == "assistant"
        ]
        assert len(assistant) == 1
        metrics = assistant[0].metrics
        assert metrics["prompt_tokens"] == 432
        assert metrics["completion_tokens"] == 87
        assert "synthetic" not in metrics


class TestDetectorSplitLiveContract:
    @pytest.mark.asyncio
    async def test_how_are_you_takes_model_path_not_canned(self, runtime):
        """'How are you?' must reach the model — never the canned greeting."""
        sid = "sess-synth-howareyou"
        canned = _SOCIAL_REPLIES["greeting"]
        calls: list = []
        gen_seen: list = []

        async def chat(messages, intent="chat", **kwargs):
            calls.append(messages)
            yield MagicMock(text="I'm doing great, thanks for asking!", done=False, usage={})
            yield MagicMock(text="", done=True, usage={})

        adapter = MagicMock()
        adapter.thinking_enabled = False
        adapter.chat = chat

        with patch_adapter(adapter):
            chunks = await _collect(runtime.process("How are you?", sid, obs=ObsCollector()))

        text = "".join(getattr(c, "text", "") or "" for c in chunks)
        assert text == "I'm doing great, thanks for asking!"
        assert canned not in text
        assert len(calls) == 1, "exactly one direct model call"

    @pytest.mark.asyncio
    async def test_hi_goes_through_the_model_one_call(self, runtime):
        """'Hi' is answered by the model on the trivial fast path — exactly
        ONE direct call, no loop pipeline. (The S206 zero-provider boundary
        now lives only in the provider-DOWN fallback: a dead provider still
        can't turn 'hi' into an error card, but a healthy one answers for
        real.)"""
        sid = "sess-synth-hi"
        calls: list = []

        async def chat(messages, intent="chat", **kwargs):
            calls.append(messages)
            yield MagicMock(text="Hey! What are we working on?", done=False, usage={})
            yield MagicMock(text="", done=True, usage={})

        adapter = MagicMock()
        adapter.thinking_enabled = False
        adapter.chat = chat

        with patch_adapter(adapter):
            chunks = await _collect(runtime.process("Hi", sid, obs=ObsCollector()))

        text = "".join(getattr(c, "text", "") or "" for c in chunks)
        assert text == "Hey! What are we working on?"
        assert len(calls) == 1, "exactly one direct model call"
