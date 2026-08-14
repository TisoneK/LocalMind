"""Memory hierarchy and parent-runtime wiring tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from core.memory import MEMORY_LEVELS, MemoryComposer, level_priorities


class TestLevelPriorities:
    def test_debug_prefers_session_and_turn(self):
        assert level_priorities("debug") == ("session", "turn", "long_term")

    def test_plan_prefers_project_and_long_term(self):
        assert level_priorities("plan") == ("project", "long_term")

    def test_code_prefers_project_and_session(self):
        assert level_priorities("code") == ("project", "session")

    def test_research_prefers_long_term_and_project(self):
        assert level_priorities("research") == ("long_term", "project")

    def test_chat_prefers_long_term(self):
        assert level_priorities("chat") == ("long_term",)

    def test_verify_prefers_session(self):
        assert level_priorities("verify") == ("session",)

    def test_unknown_task_type_is_none_noop(self):
        assert level_priorities(None) is None
        assert level_priorities("") is None
        assert level_priorities("nonsense") is None

    def test_levels_are_valid_hierarchy_members(self):
        for levels in level_priorities("debug"), level_priorities("plan"):
            assert all(level in MEMORY_LEVELS for level in levels)


class TestStoreTagsLevel:
    @pytest.mark.asyncio
    async def test_store_defaults_to_long_term(self):
        composer = MemoryComposer()
        composer._store = AsyncMock()
        await composer.store("fact", "s1")
        _, kwargs = composer._store.store.await_args
        assert kwargs["extra_metadata"]["memory_level"] == "long_term"

    @pytest.mark.asyncio
    async def test_store_explicit_level(self):
        composer = MemoryComposer()
        composer._store = AsyncMock()
        await composer.store("fact", "s1", level="project")
        _, kwargs = composer._store.store.await_args
        assert kwargs["extra_metadata"]["memory_level"] == "project"

    @pytest.mark.asyncio
    async def test_store_invalid_level_falls_back_to_long_term(self):
        composer = MemoryComposer()
        composer._store = AsyncMock()
        await composer.store("fact", "s1", level="bogus")
        _, kwargs = composer._store.store.await_args
        assert kwargs["extra_metadata"]["memory_level"] == "long_term"


def _recall_fixture(facts):
    now = 1_700_000_000.0
    return [
        (
            fact,
            0.10,
            {
                "timestamp": str(now),
                "importance": "0.6",
                "access_count": "0",
                "id": f"id{i}",
                **meta,
            },
        )
        for i, (fact, meta) in enumerate(facts)
    ]


class TestComposeLevelFilter:
    def _composer(self, raw):
        composer = MemoryComposer()
        composer._store = AsyncMock()
        composer._store.recall_with_scores.return_value = raw
        composer._store.count.return_value = 50
        return composer

    @pytest.mark.asyncio
    async def test_levels_restrict_recall(self):
        composer = self._composer(
            _recall_fixture(
                [
                    ("recent stack trace from this session", {"memory_level": "session"}),
                    ("project convention: pytest for tests", {"memory_level": "project"}),
                    ("user prefers dark mode", {"memory_level": "long_term"}),
                ]
            )
        )
        from core.models import Intent

        facts = await composer.compose(
            "project conventions and tooling", Intent.FILE_TASK, "s1", levels=("project",)
        )
        assert facts == ["project convention: pytest for tests"]
        assert "recent stack trace" not in facts
        assert "dark mode" not in facts

    @pytest.mark.asyncio
    async def test_untagged_facts_default_to_long_term(self):
        composer = self._composer(
            _recall_fixture(
                [
                    ("user prefers dark mode", {}),
                    ("recent stack trace", {"memory_level": "session"}),
                ]
            )
        )
        from core.models import Intent

        facts = await composer.compose(
            "user preferences and past choices", Intent.FILE_TASK, "s1", levels=("long_term",)
        )
        assert facts == ["user prefers dark mode"]

    @pytest.mark.asyncio
    async def test_levels_none_is_legacy_no_filter(self):
        composer = self._composer(
            _recall_fixture(
                [("recent stack trace", {"memory_level": "session"}), ("user prefers dark mode", {})]
            )
        )
        from core.models import Intent

        facts = await composer.compose("trace and error context", Intent.FILE_TASK, "s1")
        assert set(facts) == {"recent stack trace", "user prefers dark mode"}


class TestRetrieveForTask:
    @pytest.mark.asyncio
    async def test_unknown_task_type_passes_none_levels(self):
        composer = MemoryComposer()
        composer._store = AsyncMock()
        composer._store.recall_with_scores.return_value = _recall_fixture(
            [("user prefers dark mode", {})]
        )
        composer._store.count.return_value = 50
        original_compose = composer.compose
        called = {}

        async def spy(query, intent, session_id, top_k=6, levels=None):
            called["levels"] = levels
            return await original_compose(query, intent, session_id, top_k=top_k, levels=levels)

        composer.compose = spy
        from core.models import Intent

        await composer.retrieve_for_task("hi", Intent.CHAT, "s1", task_type=None)
        assert called["levels"] is None

    @pytest.mark.asyncio
    async def test_resolves_task_type_to_levels(self):
        composer = MemoryComposer()
        composer._store = AsyncMock()
        composer._store.recall_with_scores.return_value = _recall_fixture(
            [("project convention", {"memory_level": "project"})]
        )
        composer._store.count.return_value = 50
        original_compose = composer.compose
        called = {}

        async def spy(query, intent, session_id, top_k=6, levels=None):
            called["levels"] = levels
            return await original_compose(query, intent, session_id, top_k=top_k, levels=levels)

        composer.compose = spy
        from core.models import Intent

        await composer.retrieve_for_task("write tests", Intent.CHAT, "s1", task_type="code")
        assert called["levels"] == ("project", "session")

    @pytest.mark.asyncio
    async def test_code_task_retrieves_project_facts_only(self):
        composer = MemoryComposer()
        composer._store = AsyncMock()
        composer._store.recall_with_scores.return_value = _recall_fixture(
            [
                ("project convention: pytest", {"memory_level": "project"}),
                ("user prefers dark mode", {"memory_level": "long_term"}),
            ]
        )
        composer._store.count.return_value = 50
        from core.models import Intent

        facts = await composer.retrieve_for_task(
            "write tests for the new module", Intent.FILE_TASK, "s1", task_type="code"
        )
        assert facts == ["project convention: pytest"]


class TestParentRuntimeMemoryBoundary:
    """Memory retrieval is context assembly, not dispatcher routing."""

    @pytest.mark.asyncio
    async def test_parent_runtime_uses_unclassified_memory_context(self):
        from core.engine import Engine
        from core.models import StreamChunk

        engine = Engine()
        composer = AsyncMock()
        composer.retrieve_for_task.return_value = []
        composer.warm_start_facts.return_value = []
        engine._memory = composer

        async def fake_run(**kwargs):
            yield StreamChunk(text="done", done=True)

        adapter = MagicMock()
        adapter.effective_context_window = 8192
        with patch("core.engine.get_adapter", return_value=adapter), patch.object(
            engine._agent_loop, "run", fake_run
        ):
            chunks = [
                chunk
                async for chunk in engine.process("build the app", "parent-memory-1")
            ]

        assert chunks
        assert composer.retrieve_for_task.await_count == 1
        _, kwargs = composer.retrieve_for_task.await_args
        assert kwargs["task_type"] == ""
