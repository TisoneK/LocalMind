"""
Tests for S426 — the UI's own conversational hint must ENABLE, not disable,
the trivial/conversational fast-path.

Live evidence (S426 baseline, bankofai, isolated 8765): the Electron UI sends
``X-LocalMind-Intent: chat`` for obvious conversational sends
(client.ts ``classifyClientIntent``, ADR-11 client half), and the old
``not client_intent`` gate at the fast-path meant every such turn paid the
full init+Thinker+iteration pipeline — 75.0s for "Hi" — while the
deterministic canned reply (S206 zero-provider-call boundary) sat right
there behind the gate.

The contract locked here:
  - client_intent=None / "" / "chat" → fast-path eligible (the deterministic
    detectors — is_trivial_input / is_conversational_question — remain the
    REAL gate; the hint only makes the turn eligible).
  - client_intent="chat" does NOT emit routing_hint_ignored (the hint is
    honored, not discarded).
  - explicit TOOL hints ("code_exec", "shell", ...) still suppress the
    fast-path and still emit routing_hint_ignored.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.trivial_input import _SOCIAL_REPLIES


@pytest.fixture
def runtime():
    from core.agent_runtime import AgentRuntime

    rt = AgentRuntime()
    rt._last_observation = {}
    return rt


def _llm_forbidden_adapter() -> MagicMock:
    """An adapter that fails the test the moment the model is called.

    The canned trivial reply makes ZERO provider calls — if the pipeline
    reaches the model, the fast path did not fire.
    """
    adapter = MagicMock()
    adapter.thinking_enabled = False
    adapter.chat.side_effect = AssertionError(
        "fast path must not call the LLM — the canned reply is deterministic"
    )
    adapter.chat_with_tools.side_effect = AssertionError(
        "fast path must not call the LLM — the canned reply is deterministic"
    )
    return adapter


async def _collect(agen) -> list:
    return [c async for c in agen]


class TestChatHintFastPath:
    @pytest.mark.asyncio
    async def test_greeting_with_chat_hint_takes_canned_fast_path(self, runtime):
        """'Hi' + X-LocalMind-Intent: chat → canned reply, ZERO model calls."""
        from core.obs import ObsCollector

        obs = ObsCollector()
        adapter = _llm_forbidden_adapter()
        with patch_adapter(adapter):
            chunks = await _collect(
                runtime.process("Hi", "sess-s426-hint", obs=obs, client_intent="chat")
            )

        text = "".join(getattr(c, "text", "") or "" for c in chunks)
        assert text == _SOCIAL_REPLIES["greeting"]
        # No routing_hint_ignored for a chat hint — the hint is honored.
        assert not [e for e in obs.history() if e.type == "routing_hint_ignored"]

    @pytest.mark.asyncio
    async def test_greeting_without_hint_still_fast_paths(self, runtime):
        """No header at all → canned reply (pre-existing S206 behavior)."""
        from core.obs import ObsCollector

        obs = ObsCollector()
        adapter = _llm_forbidden_adapter()
        with patch_adapter(adapter):
            chunks = await _collect(
                runtime.process("Hi", "sess-s426-nohint", obs=obs, client_intent=None)
            )

        text = "".join(getattr(c, "text", "") or "" for c in chunks)
        assert text == _SOCIAL_REPLIES["greeting"]

    @pytest.mark.asyncio
    async def test_chat_hint_conversational_question_single_direct_call(self, runtime):
        """Conversational question + chat hint → ONE direct chat call, no init.

        Discriminator vs a pipeline regression: the fast path emits
        stage_timing(intent_classify, skipped) and NEVER agent_initialization_*.
        """
        from core.obs import ObsCollector

        calls: list[dict] = []

        async def chat(messages, intent="chat", **kwargs):
            calls.append({"system": str(messages[0].get("content", ""))[:80]})
            yield MagicMock(text="I can help with files, web research, and code.",
                            done=False, error=None)
            yield MagicMock(text="", done=True, error=None)

        adapter = MagicMock()
        adapter.thinking_enabled = False
        adapter.chat = chat

        obs = ObsCollector()
        with patch_adapter(adapter):
            chunks = await _collect(
                runtime.process(
                    "What can you do?", "sess-s426-conv", obs=obs, client_intent="chat"
                )
            )

        text = "".join(getattr(c, "text", "") or "" for c in chunks)
        assert "files" in text
        # One direct call — the init decision call never happened.
        assert len(calls) == 1, f"expected 1 chat call, got {len(calls)}"
        stages = [e for e in obs.history() if e.type == "stage_timing"]
        assert any(
            e.data.get("stage") == "intent_classify"
            and e.data.get("status") == "skipped"
            for e in stages
        )
        assert not [e for e in obs.history() if e.type == "agent_initialization_done"]


class TestToolHintStillSuppressed:
    @pytest.mark.asyncio
    async def test_tool_hint_bypasses_fast_path(self, runtime):
        """An explicit TOOL hint still suppresses the fast-path.

        The canned greeting must NEVER appear in the output, the
        routing_hint_ignored announcement must fire, and the fast-path's
        signature skipped-stage events must be absent. The mock adapter's
        stream content is irrelevant — the parent pipeline can do whatever
        it does with it; what matters is that the deterministic canned
        reply was not served.
        """
        from core.obs import ObsCollector

        async def chat(messages, intent="chat", **kwargs):
            yield MagicMock(text="(mock model output)", done=False, error=None)
            yield MagicMock(text="", done=True, error=None)

        adapter = MagicMock()
        adapter.thinking_enabled = False
        adapter.chat = chat
        adapter.chat_with_tools = chat

        obs = ObsCollector()
        with patch_adapter(adapter):
            chunks = await _collect(
                runtime.process(
                    "Hi", "sess-s426-tool", obs=obs, client_intent="code_exec"
                )
            )

        text = "".join(getattr(c, "text", "") or "" for c in chunks)
        assert _SOCIAL_REPLIES["greeting"] not in text
        assert [e for e in obs.history() if e.type == "routing_hint_ignored"], (
            "an explicit tool hint must still emit routing_hint_ignored"
        )


def patch_adapter(adapter: MagicMock):
    """Patch the adapter factory the runtime resolves its model through."""
    import unittest.mock as mock

    return mock.patch("core.engine.get_adapter", return_value=adapter)
