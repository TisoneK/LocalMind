"""Session 359 — memory end-to-end fixes.

Three gaps closed:
- Gap A: memory_op's SQLite fallback omitted `timestamp` from metadata, so
  warm_start_facts treated the fact as ancient (age = now - 0) and the agent
  never saw what it stored when embeddings are unavailable.
- Gap B: the deterministic write path re-extracted content with a buggier
  regex ("note down my project" → stored "down my project") and always tagged
  it "semantic", dropping the classifier's memory_type.
- Gap C: extract_memory_candidates()/should_store_candidate() were dead code —
  corrections, stated preferences, and source knowledge from tool outcomes
  were never gathered from chat evidence post-turn.
"""
from __future__ import annotations

import json
import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.memory_intent import classify_memory_intent
from core.obs import ObsCollector
from tools.memory_tool import memory_op


def _make_mixin_with_fake_memory(store=None):
    """A minimal _MemoryMixin instance with a stubbed memory backend."""
    from core.engine._memory_mixin import _MemoryMixin

    mixin = _MemoryMixin.__new__(_MemoryMixin)
    memory = MagicMock()
    memory.search.return_value = []  # no dedup collisions
    memory.store = AsyncMock(return_value=True)
    mixin._memory = memory
    if store is not None:
        mixin._memory = store
    return mixin


class TestGapAFallbackTimestamp:
    """The end-to-end breaker: fallback-stored facts must be retrievable."""

    @pytest.mark.asyncio
    async def test_fallback_store_writes_timestamp(self, tmp_path, monkeypatch):
        """The fallback row carries a timestamp so warm_start_facts sees it as fresh."""
        from core.config import settings

        monkeypatch.setattr(settings, "localmind_home", str(tmp_path))
        monkeypatch.setattr(settings, "localmind_db_path", str(tmp_path / "localmind.db"))

        # Force the vector path to fail so the plain-SQLite fallback runs.
        with patch("storage.vector.VectorStore.store", new=AsyncMock(return_value=False)):
            result = await memory_op("remember that I prefer Python")

        assert result.success is True
        assert "Remembered" in result.content

        conn = sqlite3.connect(str(tmp_path / "localmind.db"))
        row = conn.execute("SELECT metadata FROM vector_facts").fetchone()
        conn.close()
        assert row is not None, "fallback store wrote nothing"
        meta = json.loads(row[0])
        assert "timestamp" in meta, "fallback metadata must carry a timestamp"
        assert meta["fallback"] == "true"

    @pytest.mark.asyncio
    async def test_warm_start_facts_retrieves_fallback_fact(self, tmp_path, monkeypatch):
        """End-to-end: store via fallback → warm_start_facts returns the fact."""
        from core.config import settings
        from core.memory import MemoryComposer
        from storage.vector import VectorStore

        monkeypatch.setattr(settings, "localmind_home", str(tmp_path))
        monkeypatch.setattr(settings, "localmind_db_path", str(tmp_path / "localmind.db"))

        with patch("storage.vector.VectorStore.store", new=AsyncMock(return_value=False)):
            await memory_op("remember that I prefer Python")

        composer = MemoryComposer(vector_store=VectorStore())
        warm = await composer.warm_start_facts(session_id="explicit_memory_op", max_facts=3)
        assert any("prefer Python" in f for f in warm), f"fact not retrievable: {warm}"


class TestRecallOperation:
    """The tool advertises operation=recall; a 'recall X' message must search,
    never fall through to the store path (which stored junk 'recall')."""

    @pytest.mark.asyncio
    async def test_recall_matches_stored_fact(self, tmp_path, monkeypatch):
        from core.config import settings

        monkeypatch.setattr(settings, "localmind_home", str(tmp_path))
        monkeypatch.setattr(settings, "localmind_db_path", str(tmp_path / "localmind.db"))

        # Store one fact via the fallback path first.
        with patch("storage.vector.VectorStore.store", new=AsyncMock(return_value=False)):
            await memory_op("remember that I prefer concise answers")

        # Now recall it — must return the fact, NOT store "recall".
        # "preferences" prefix-matches "prefer" in the stored fact.
        result = await memory_op("recall my preferences")
        assert result.success is True
        assert "prefer concise" in result.content
        assert "From memory" in result.content

        # Nothing new may have been stored by the recall itself.
        conn = sqlite3.connect(str(tmp_path / "localmind.db"))
        rows = conn.execute("SELECT content FROM vector_facts").fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0][0] == "I prefer concise answers"

    @pytest.mark.asyncio
    async def test_recall_no_match_surfaces_recent_facts(self, tmp_path, monkeypatch):
        """A loose query must surface recent facts, never store the query as junk."""
        from core.config import settings

        monkeypatch.setattr(settings, "localmind_home", str(tmp_path))
        monkeypatch.setattr(settings, "localmind_db_path", str(tmp_path / "localmind.db"))

        with patch("storage.vector.VectorStore.store", new=AsyncMock(return_value=False)):
            await memory_op("remember that I prefer concise answers")

        # "favorite color" doesn't overlap the stored fact — falls back to
        # recent facts instead of an empty miss, and stores nothing.
        result = await memory_op("recall my favorite color")
        assert result.success is True
        assert "prefer concise" in result.content  # recent-facts fallback

        conn = sqlite3.connect(str(tmp_path / "localmind.db"))
        rows = conn.execute("SELECT content FROM vector_facts").fetchall()
        conn.close()
        assert len(rows) == 1  # recall must not have stored anything

    @pytest.mark.asyncio
    async def test_bare_recall_lists_recent_never_stores(self, tmp_path, monkeypatch):
        """A bare 'recall' (no query) must list facts, never store junk."""
        from core.config import settings

        monkeypatch.setattr(settings, "localmind_home", str(tmp_path))
        monkeypatch.setattr(settings, "localmind_db_path", str(tmp_path / "localmind.db"))

        with patch("storage.vector.VectorStore.store", new=AsyncMock(return_value=False)):
            await memory_op("remember that I prefer concise answers")

        result = await memory_op("recall")
        assert result.success is True
        assert "prefer concise" in result.content

        conn = sqlite3.connect(str(tmp_path / "localmind.db"))
        rows = conn.execute("SELECT content FROM vector_facts").fetchall()
        conn.close()
        assert len(rows) == 1  # bare recall must not have stored anything
        assert rows[0][0] == "I prefer concise answers"

    def test_text_tools_accepts_query_alias_for_recall(self):
        """The model often sends {'operation': 'recall', 'query': ...} — the
        dispatcher must forward the query as content so the recall works."""
        from core.agent.text_tools import _extract_tool_input

        out = _extract_tool_input("memory_op", {"operation": "recall", "query": "my preferences"})
        assert out == "recall my preferences"
        out2 = _extract_tool_input("memory_op", {"operation": "recall", "content": "my preferences"})
        assert out2 == "recall my preferences"

    @pytest.mark.asyncio
    async def test_store_path_still_works(self, tmp_path, monkeypatch):
        from core.config import settings

        monkeypatch.setattr(settings, "localmind_home", str(tmp_path))
        monkeypatch.setattr(settings, "localmind_db_path", str(tmp_path / "localmind.db"))

        store = MagicMock()
        store.store = AsyncMock(return_value=True)
        with patch("storage.vector.VectorStore", return_value=store):
            result = await memory_op("remember that I prefer Python")
        assert result.success is True
        assert "Python" in store.store.await_args.kwargs["fact"]

    @pytest.mark.asyncio
    async def test_colon_cue_stores_fact_not_framing(self, tmp_path, monkeypatch):
        """'Remember this: <fact>. Just acknowledge.' must store the fact alone."""
        from core.config import settings

        monkeypatch.setattr(settings, "localmind_home", str(tmp_path))
        monkeypatch.setattr(settings, "localmind_db_path", str(tmp_path / "localmind.db"))

        store = MagicMock()
        store.store = AsyncMock(return_value=True)
        with patch("storage.vector.VectorStore", return_value=store):
            result = await memory_op(
                "Remember this: my project is called Falcon. Just acknowledge."
            )
        assert result.success is True
        fact = store.store.await_args.kwargs["fact"]
        assert fact == "my project is called Falcon"
        assert "this:" not in fact and "acknowledge" not in fact.lower()
        assert result.content == "Remembered: *my project is called Falcon*"

    @pytest.mark.asyncio
    async def test_quantified_things_cue_stores_fact_not_framing(
        self, tmp_path, monkeypatch
    ):
        """'Remember two things: X and Y' must not persist the 'two things:' tail."""
        from core.config import settings

        monkeypatch.setattr(settings, "localmind_home", str(tmp_path))
        monkeypatch.setattr(settings, "localmind_db_path", str(tmp_path / "localmind.db"))

        store = MagicMock()
        store.store = AsyncMock(return_value=True)
        with patch("storage.vector.VectorStore", return_value=store):
            result = await memory_op(
                "Remember two things: my project is called Falcon "
                "and my sister's name is Ama"
            )
        assert result.success is True
        fact = store.store.await_args.kwargs["fact"]
        assert fact == "my project is called Falcon and my sister's name is Ama"


class TestGapBClassifierContentThrough:
    """The deterministic write path must store the classifier's extraction."""

    @pytest.mark.asyncio
    async def test_memory_op_stores_provided_content_verbatim(self, tmp_path, monkeypatch):
        """'note down my project uses FastAPI' must NOT store 'down my project...'."""
        from core.config import settings

        monkeypatch.setattr(settings, "localmind_home", str(tmp_path))
        monkeypatch.setattr(settings, "localmind_db_path", str(tmp_path / "localmind.db"))

        store = MagicMock()
        store.store = AsyncMock(return_value=True)
        with patch("storage.vector.VectorStore", return_value=store):
            result = await memory_op(
                "note down my project uses FastAPI",
                content="my project uses FastAPI",
                memory_type="user_fact",
            )

        assert result.success is True
        stored_fact = store.store.await_args.kwargs["fact"]
        assert stored_fact == "my project uses FastAPI"
        assert "down" not in stored_fact
        extra = store.store.await_args.kwargs["extra_metadata"]
        assert extra["memory_type"] == "user_fact"

    @pytest.mark.asyncio
    async def test_classifier_content_matches_memory_op_path(self, tmp_path, monkeypatch):
        """The agent_runtime wiring: classifier content/type → memory_op args."""
        from core.config import settings

        monkeypatch.setattr(settings, "localmind_home", str(tmp_path))
        monkeypatch.setattr(settings, "localmind_db_path", str(tmp_path / "localmind.db"))

        intent = classify_memory_intent("keep in mind the user wants dark mode")
        assert intent.is_write is True
        assert intent.content == "user wants dark mode"

        store = MagicMock()
        store.store = AsyncMock(return_value=True)
        with patch("storage.vector.VectorStore", return_value=store):
            await memory_op(
                intent.raw_message,
                content=intent.content or None,
                memory_type=intent.memory_type.value,
            )

        stored_fact = store.store.await_args.kwargs["fact"]
        assert stored_fact == "user wants dark mode"
        extra = store.store.await_args.kwargs["extra_metadata"]
        assert extra["memory_type"] == "user_preference"


class TestGapCChatEvidenceGathering:
    """extract_memory_candidates must now run post-turn from chat evidence."""

    @pytest.mark.asyncio
    async def test_correction_is_stored_post_turn(self):
        """A short correction turn must reach _store_fact_if_valid (Path 2 would skip it)."""
        mixin = _make_mixin_with_fake_memory()
        mixin._store_fact_if_valid = AsyncMock()

        obs = ObsCollector()
        await mixin._maybe_store_response_facts(
            response_text="Got it.",
            session_id="s1",
            obs=obs,
            user_message="No, browser is a first-class capability, not a fallback.",
        )

        calls = mixin._store_fact_if_valid.call_args_list
        sources = [c.kwargs.get("source") for c in calls]
        assert "user_correction" in sources, f"correction never stored: {calls}"
        event_types = [e.type for e in obs.history()]
        assert "memory_candidate_stored" in event_types

    @pytest.mark.asyncio
    async def test_source_knowledge_from_tool_evidence_is_stored(self):
        """A tool output with a URL must produce a source-knowledge candidate."""
        mixin = _make_mixin_with_fake_memory()
        mixin._store_fact_if_valid = AsyncMock()

        obs = ObsCollector()
        obs.emit(
            "tool_call",
            tool="web_fetch",
            status="done",
            output="Source: https://weathermetro.com/weather/kitengela\nContent: Temperature 25°C, clear skies.",
        )
        await mixin._maybe_store_response_facts(
            response_text="Here's the weather you asked about.",
            session_id="s1",
            obs=obs,
            user_message="What's the weather?",
        )

        calls = mixin._store_fact_if_valid.call_args_list
        sources = [c.kwargs.get("source") for c in calls]
        assert "tool_outcome" in sources, f"source knowledge never stored: {calls}"

    @pytest.mark.asyncio
    async def test_ephemeral_turn_stores_nothing(self):
        """Ephemeral talk ('I'm having lunch') must not be stored."""
        mixin = _make_mixin_with_fake_memory()
        mixin._store_fact_if_valid = AsyncMock()

        obs = ObsCollector()
        await mixin._maybe_store_response_facts(
            response_text="Enjoy your lunch!",
            session_id="s1",
            obs=obs,
            user_message="I'm having lunch now.",
        )

        assert mixin._store_fact_if_valid.await_count == 0
