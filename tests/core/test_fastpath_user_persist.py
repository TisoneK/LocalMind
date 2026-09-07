"""Regression: deterministic turn paths must persist the user's message.

Live evidence: a chat export of a short greeting conversation contained only
assistant rows — every turn in that chat took a deterministic epilog (canned
greeting, one direct conversational model call), and those epilogs returned
before the main agent-loop path scheduled its fire-and-forget user-message
persist. The sidebar's per-chat message count (a COUNT over the messages
table, no role filter) inherited the same assistant-only picture, and the
reopened chat's transcript lost the user's side of the conversation.

Contract locked here, per deterministic path:
  - trivial canned fast path (zero provider calls),
  - conversational fast path (one direct chat call),
  - direct memory-write path (both the can't-resolve ask and the
    write confirmation),
the turn leaves BOTH rows — the user's message first, since history reads
order by timestamp — and the session count and first-message preview see it.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.models import Role
from storage.db import SessionStore


async def _no_memories() -> list[dict]:
    return []


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    """An AgentRuntime whose every write lands in an isolated tmp home.

    Default settings point the chat store and the session workspace folders
    at the real LocalMind home — a test that runs a turn must not touch
    either (test suites have historically polluted the real chat store that
    way). Both settings are patched BEFORE the runtime is constructed so
    init-time path derivation sees the tmp home too.
    """
    from core import config
    # Import via core.engine (which re-exports AgentRuntime): entering the
    # engine package first is the safe import direction — a direct
    # core.agent_runtime import re-enters engine/__init__ while
    # agent_runtime is still mid-initialization (circular ImportError).
    from core.engine import AgentRuntime

    monkeypatch.setattr(
        config.settings, "localmind_home", str(tmp_path), raising=False
    )
    monkeypatch.setattr(
        config.settings, "localmind_db_path", str(tmp_path / "test.db"), raising=False
    )

    rt = AgentRuntime()
    rt._store = SessionStore(str(tmp_path / "test.db"))
    rt._memory = SimpleNamespace(list_all_with_metadata=_no_memories)
    rt._last_observation = {}
    return rt


def _llm_forbidden_adapter() -> MagicMock:
    """Fails the test the moment the model is called — the canned trivial
    reply is deterministic and must make zero provider calls."""
    adapter = MagicMock()
    adapter.thinking_enabled = False
    adapter.chat.side_effect = AssertionError(
        "trivial fast path must not call the LLM"
    )
    adapter.chat_with_tools.side_effect = AssertionError(
        "trivial fast path must not call the LLM"
    )
    return adapter


def _chat_adapter(text: str) -> MagicMock:
    """A one-shot direct-chat adapter for the conversational fast path."""

    async def chat(messages, intent="chat", **kwargs):
        yield MagicMock(text=text, done=False, error=None)
        yield MagicMock(text="", done=True, error=None)

    adapter = MagicMock()
    adapter.thinking_enabled = False
    adapter.chat = chat
    return adapter


async def _collect(agen) -> list:
    return [c async for c in agen]


def _history(rt, sid):
    return rt._store.get_history(sid)


class TestFastPathPersistsUserMessage:
    @pytest.mark.asyncio
    async def test_trivial_fast_path_persists_user_then_reply(self, runtime):
        """'Hi' (canned reply, zero provider calls) leaves user + reply rows."""
        from core.obs import ObsCollector
        from core.trivial_input import _SOCIAL_REPLIES

        sid = "sess-userpersist-trivial"
        with patch_adapter(_llm_forbidden_adapter()):
            await _collect(runtime.process("Hi", sid, obs=ObsCollector()))

        history = _history(runtime, sid)
        assert [(m.role, m.content) for m in history] == [
            (Role.USER, "Hi"),
            (Role.ASSISTANT, _SOCIAL_REPLIES["greeting"]),
        ]

    @pytest.mark.asyncio
    async def test_conversational_fast_path_persists_user_then_reply(
        self, runtime
    ):
        """A one-direct-call conversational turn leaves user + reply rows."""
        from core.obs import ObsCollector

        sid = "sess-userpersist-conv"
        adapter = _chat_adapter("I can help with files, web research, and code.")
        calls: list = []
        gen = adapter.chat  # the real generator, captured before wrapping

        async def counting_chat(messages, intent="chat", **kwargs):
            calls.append(messages)
            async for chunk in gen(messages, intent=intent, **kwargs):
                yield chunk

        adapter.chat = counting_chat
        with patch_adapter(adapter):
            await _collect(
                runtime.process(
                    "What can you do?", sid, obs=ObsCollector(), client_intent="chat"
                )
            )

        history = _history(runtime, sid)
        assert [(m.role, m.content) for m in history] == [
            (Role.USER, "What can you do?"),
            (Role.ASSISTANT, "I can help with files, web research, and code."),
        ]
        # The fast-path contract itself is intact: still exactly one call.
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_session_count_and_preview_see_the_user_row(self, runtime):
        """The sidebar's count and first-message preview include the user."""
        from core.obs import ObsCollector

        sid = "sess-userpersist-count"
        with patch_adapter(_llm_forbidden_adapter()):
            await _collect(runtime.process("Hi", sid, obs=ObsCollector()))

        sessions = {s["id"]: s for s in runtime._store.list_sessions()}
        assert sessions[sid]["message_count"] == 2
        assert sessions[sid]["first_message"] == "Hi"


class TestMemoryWritePersistsUserMessage:
    @pytest.mark.asyncio
    async def test_write_confirmation_persists_user_then_reply(self, runtime, monkeypatch):
        """A direct memory write ('Remember that X') leaves user + confirm."""
        from core.obs import ObsCollector

        async def fake_memory_op(message, content=None, memory_type=None, **kwargs):
            return SimpleNamespace(success=True, content=f"Remembered: {content}")

        monkeypatch.setattr("tools.memory_tool.memory_op", fake_memory_op)

        sid = "sess-userpersist-memwrite"
        text = "Remember that my favorite color is teal."
        with patch_adapter(_chat_adapter("(unused — deterministic write path)")):
            await _collect(runtime.process(text, sid, obs=ObsCollector()))

        history = _history(runtime, sid)
        assert [m.role for m in history] == [Role.USER, Role.ASSISTANT]
        assert history[0].content == text
        assert history[1].content.startswith("Remembered:")
        # The write itself only confirmed because memory_op said so.
        assert "teal" in history[1].content

    @pytest.mark.asyncio
    async def test_resolution_failure_ask_persists_user_and_reply(
        self, runtime, monkeypatch
    ):
        """A bare referent that can't be resolved still logs the user's turn.

        The ask-for-detail reply persists (so the conversation survives a
        reload), and memory_op is never reached — a failed resolution must
        not write anything.
        """
        from core.obs import ObsCollector

        async def resolve_none(*args, **kwargs):
            return None

        async def forbidden_memory_op(*args, **kwargs):
            raise AssertionError("resolution failed — memory_op must not run")

        monkeypatch.setattr(
            "core.memory_resolver.resolve_memory_fact", resolve_none
        )
        monkeypatch.setattr("tools.memory_tool.memory_op", forbidden_memory_op)

        sid = "sess-userpersist-memask"
        text = "Remember the source for the EPL table"
        with patch_adapter(_chat_adapter("(unused — resolution fails first)")):
            await _collect(runtime.process(text, sid, obs=ObsCollector()))

        history = _history(runtime, sid)
        assert [m.role for m in history] == [Role.USER, Role.ASSISTANT]
        assert history[0].content == text
        assert history[1].content.startswith("I want to remember this correctly")


def patch_adapter(adapter: MagicMock):
    """Patch the adapter factory the runtime resolves its model through."""
    import unittest.mock as mock

    return mock.patch("core.engine.get_adapter", return_value=adapter)


class TestTurnIdentityInMetrics:
    """The v3 export lifts per-turn model/provider identity out of the
    persisted metrics — stamp it where a model actually produced the reply
    (conversational leg, agent finalize), never on the canned trivial leg,
    where stamping would fabricate the identity of a reply no model gave."""

    @pytest.mark.asyncio
    async def test_conversational_turn_stamps_model_and_provider(self, runtime, monkeypatch):
        from core.config import settings
        from core.obs import ObsCollector

        monkeypatch.setattr(settings, "localmind_adapter", "zai", raising=False)
        monkeypatch.setattr(
            "core.agent_runtime.active_parent_model", lambda: "glm-4.5-flash"
        )
        sid = "sess-identity-conv"
        with patch_adapter(_chat_adapter("Files, research, code.")):
            await _collect(
                runtime.process(
                    "What can you do?", sid, obs=ObsCollector(), client_intent="chat"
                )
            )

        history = _history(runtime, sid)
        metrics = history[1].metrics or {}
        assert metrics.get("model") == "glm-4.5-flash"
        assert metrics.get("provider") == "zai"

    @pytest.mark.asyncio
    async def test_trivial_canned_turn_stamps_no_identity(self, runtime, monkeypatch):
        from core.config import settings
        from core.obs import ObsCollector

        monkeypatch.setattr(settings, "localmind_adapter", "zai", raising=False)
        monkeypatch.setattr(
            "core.agent_runtime.active_parent_model", lambda: "glm-4.5-flash"
        )
        sid = "sess-identity-trivial"
        with patch_adapter(_llm_forbidden_adapter()):
            await _collect(runtime.process("Hi", sid, obs=ObsCollector()))

        history = _history(runtime, sid)
        metrics = history[1].metrics or {}
        assert "model" not in metrics
        assert "provider" not in metrics
