"""Passive context awareness (B-2026-09-15-15) — wiring + visible-write tests.

Covers three layers of the feature:
  1. The mixin pass (_maybe_store_response_facts Path 1): durable self-facts
     stated incidentally reach _store_fact_if_valid with the subject-hinted
     key, and the visible passive_context_stored event fires ONLY when the
     write actually landed (ADR-64: proactive writes are visible, never
     silent; the store's state must change before the UI says anything).
  2. Dedup across paths: a sentence the passive pass already proposed must
     not reach the store a second time through the generic candidate path.
  3. The conversational fast path runs the extraction (facts stated in
     casual conversation reach the store) while the one-direct-call
     contract of that path stays intact.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.obs import ObsCollector


def _make_mixin_with_fake_memory():
    """A minimal _MemoryMixin instance with a stubbed memory backend."""
    from core.engine._memory_mixin import _MemoryMixin

    mixin = _MemoryMixin.__new__(_MemoryMixin)
    memory = MagicMock()
    memory.search.return_value = []  # no dedup collisions
    memory.store = AsyncMock(return_value=True)
    mixin._memory = memory
    return mixin


class TestPassivePassStorage:
    @pytest.mark.asyncio
    async def test_stated_location_is_stored_with_subject_key(self):
        mixin = _make_mixin_with_fake_memory()
        mixin._store_fact_if_valid = AsyncMock(return_value=True)
        obs = ObsCollector()

        await mixin._maybe_store_response_facts(
            response_text="Got it!",
            session_id="s-passive-1",
            obs=obs,
            user_message="I'm based in Nairobi, by the way.",
        )

        calls = mixin._store_fact_if_valid.call_args_list
        assert len(calls) == 1, f"expected exactly one passive write: {calls}"
        call = calls[0]
        assert call.kwargs.get("source") == "conversation"
        assert call.kwargs.get("key") == "subject:location"
        assert "Nairobi" in call.args[0]

    @pytest.mark.asyncio
    async def test_visible_event_fires_only_on_actual_write(self):
        mixin = _make_mixin_with_fake_memory()
        obs = ObsCollector()

        # Write lands → exactly one visible event.
        mixin._store_fact_if_valid = AsyncMock(return_value=True)
        await mixin._maybe_store_response_facts(
            response_text="Noted.",
            session_id="s-passive-2",
            obs=obs,
            user_message="My name is Tisone.",
        )
        assert (
            len([e for e in obs.history() if e.type == "passive_context_stored"]) == 1
        )

        # Write refused (volatile / dedup / gate) → store unchanged →
        # NO event (ADR-64: the visible log mirrors the store's state).
        mixin._store_fact_if_valid = AsyncMock(return_value=False)
        obs_refused = ObsCollector()
        await mixin._maybe_store_response_facts(
            response_text="Noted.",
            session_id="s-passive-3",
            obs=obs_refused,
            user_message="My name is Tisone.",
        )
        assert (
            len([e for e in obs_refused.history() if e.type == "passive_context_stored"]) == 0
        )

    @pytest.mark.asyncio
    async def test_volatile_statement_is_refused_not_stored(self):
        """Policy (-3): the durability gate stays the only refuse authority —
        the passive path must not smuggle live values past it."""
        from core.memory_intent import extract_passive_facts

        mixin = _make_mixin_with_fake_memory()
        mixin._store_fact_if_valid = AsyncMock()
        obs = ObsCollector()

        # An ISP statement rides a "works at" shape only if the extractor
        # misfires; assert the extractor itself never proposes volatile
        # content and that nothing got stored.
        await mixin._maybe_store_response_facts(
            response_text="Okay.",
            session_id="s-passive-4",
            obs=obs,
            user_message="My IP address is 192.168.1.4.",
        )
        assert mixin._store_fact_if_valid.await_count == 0
        # Belt and braces: the extractor alone must not propose it either.
        assert extract_passive_facts("My ISP is Safaricom.") == []

    @pytest.mark.asyncio
    async def test_no_double_store_across_candidate_paths(self):
        """A sentence the passive pass proposed must not fire again through
        the generic candidate path in the same turn."""
        mixin = _make_mixin_with_fake_memory()
        mixin._store_fact_if_valid = AsyncMock(return_value=True)
        obs = ObsCollector()

        # "I prefer concise answers" matches BOTH the passive-style cue and
        # the deterministic candidate's preference cue.
        await mixin._maybe_store_response_facts(
            response_text="Sure thing.",
            session_id="s-passive-5",
            obs=obs,
            user_message="I prefer concise answers.",
        )

        stored_texts = [c.args[0] for c in mixin._store_fact_if_valid.call_args_list]
        assert len([t for t in stored_texts if "concise" in t]) == 1, (
            f"the same preference reached the store twice: {stored_texts}"
        )


class TestFastPathPassiveExtraction:
    """The conversational fast path must run the passive extraction — facts
    stated in casual conversation reach the store — while keeping that
    path's one-direct-call contract intact."""

    @pytest.fixture
    def runtime(self, tmp_path, monkeypatch):
        from core import config

        from core.engine import AgentRuntime
        from storage.db import SessionStore

        monkeypatch.setattr(config.settings, "localmind_home", str(tmp_path), raising=False)
        monkeypatch.setattr(
            config.settings, "localmind_db_path", str(tmp_path / "test.db"), raising=False
        )
        rt = AgentRuntime()
        rt._store = SessionStore(str(tmp_path / "test.db"))

        async def _no_memories() -> list[dict]:
            return []

        rt._memory = MagicMock()
        rt._memory.list_all_with_metadata = _no_memories
        rt._memory.search = AsyncMock(return_value=[])
        rt._memory.store = AsyncMock(return_value=True)
        rt._last_observation = {}
        return rt

    @pytest.mark.asyncio
    async def test_conversational_turn_stores_stated_fact_and_stays_visible(
        self, runtime, tmp_path, monkeypatch
    ):
        """A fact stated on a fast-path turn reaches the shared write path
        (subject-keyed) and fires the visible passive_context_stored event;
        the fast path stays a zero-extra-LLM-call path."""
        monkeypatch.setenv("LOCALMIND_HOME", str(tmp_path))

        adapter = MagicMock()
        adapter.thinking_enabled = False

        async def chat(messages, intent="chat", **kwargs):
            yield MagicMock(text="Happy to help with that.", done=False, error=None)
            yield MagicMock(text="", done=True, error=None)

        adapter.chat = chat
        adapter.chat_with_tools.side_effect = AssertionError(
            "the conversational fast path must not gain a second model call"
        )

        import unittest.mock as mock

        obs = ObsCollector()
        with mock.patch("core.engine.get_adapter", return_value=adapter):
            async for _ in runtime.process(
                "My name is Tisone.",
                "sess-passive-fastpath-2",
                obs=obs,
                client_intent="chat",
            ):
                pass

        # The write reached the real shared path, subject-keyed by name.
        store_calls = runtime._memory.store.await_args_list
        passive_writes = [
            c for c in store_calls if "Tisone" in str(c.kwargs.get("fact", ""))
        ]
        assert passive_writes, f"stated name never reached the store: {store_calls}"
        assert passive_writes[0].kwargs.get("key") == "subject:name"
        assert passive_writes[0].kwargs.get("source") == "conversation"

        # And the write is visible, not silent (ADR-64).
        assert any(
            e.type == "passive_context_stored" and "Tisone" in str(e.data)
            for e in obs.history()
        )


class TestPath2SuggestionGuard:
    """Path 2 (response-confirmed) must never store the MODEL'S OWN PROSE.

    Live-caught 2026-09-19 (passive-context harness, fix-1 trace): a question
    turn's assistant tail "If you prefer a more relaxed setting with good
    food and coffee, Artcaffe has several convenient locations…" was stored
    as a durable user PREFERENCE — the 'you prefer'/'you like' markers fire
    on nearly every assistant suggestion, and the pollution predates the
    passive feature (birth-tested to the initial commit)."""

    @pytest.mark.asyncio
    async def test_assistant_suggestion_is_not_stored_as_preference(self):
        mixin = _make_mixin_with_fake_memory()
        mixin._store_fact_if_valid = AsyncMock()
        obs = ObsCollector()

        await mixin._maybe_store_response_facts(
            response_text=(
                "Nairobi has many great evening spots! For a lively vibe, The "
                "Alchemist Bar in Westlands is popular. If you prefer a more "
                "relaxed setting with good food and coffee, Artcaffe has "
                "several convenient locations. Want me to narrow it down?"
            ),
            session_id="s-suggest-1",
            obs=obs,
            user_message="What's a good evening spot around here?",
        )

        assert mixin._store_fact_if_valid.await_count == 0, (
            "the model's own suggestion prose reached the store"
        )

    @pytest.mark.asyncio
    async def test_genuine_confirmation_sentence_is_still_stored(self):
        """A real completion ABOUT the user (an answer echo) still stores —
        keyed to the same subject row as the user's own statement."""
        mixin = _make_mixin_with_fake_memory()
        mixin._store_fact_if_valid = AsyncMock(return_value=True)
        obs = ObsCollector()

        await mixin._maybe_store_response_facts(
            response_text=(
                "Nice to meet you, Tisone! I have noted the introduction you "
                "shared with me just now. To confirm, your name is Tisone, and "
                "I will keep that in mind for every conversation we have going "
                "forward in this workspace. There is plenty I can help with, "
                "from research to files and code."
            ),
            session_id="s-suggest-2",
            obs=obs,
            user_message="My name is Tisone.",
        )

        calls = mixin._store_fact_if_valid.call_args_list
        assistant_calls = [c for c in calls if c.kwargs.get("source") == "assistant"]
        assert assistant_calls, "a genuine confirmation echo stopped storing"

    @pytest.mark.asyncio
    async def test_generic_candidate_emit_is_honest(self):
        """The candidate path's event fires only on an actual write — never
        claiming a store change that didn't happen."""
        mixin = _make_mixin_with_fake_memory()
        mixin._store_fact_if_valid = AsyncMock(return_value=False)  # refused
        obs = ObsCollector()

        await mixin._maybe_store_response_facts(
            response_text="Got it.",
            session_id="s-suggest-3",
            obs=obs,
            user_message="No, browser is a first-class capability, not a fallback.",
        )

        assert (
            len([e for e in obs.history() if e.type == "memory_candidate_stored"]) == 0
        )
