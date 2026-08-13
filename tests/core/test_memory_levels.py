"""
Tests for ADR-19 P1 (Session 177): context hierarchy + level-aware retrieval.

The user's framing (2026-08-12): "the same conversation can produce
different compressed contexts depending on the next task." P1 gives the
memory store the SAME idea: every fact is tagged with a context-hierarchy
level (turn / session / project / long_term) and retrieval can be
restricted to the levels a task type cares about — a debugging task pulls
session/turn context, a planning task pulls project/long-term decisions.

Covered:
- level_priorities(task_type) pure resolution (debug→session/turn,
  plan→project/long_term, ..., unknown→None = legacy no-op).
- store(level=...) tags memory_level metadata; invalid levels fall back.
- compose(levels=...) filters facts by their memory_level tag; facts
  without a tag (pre-P1 stores) default to long_term so nothing is lost.
- retrieve_for_task() wires task_type → levels → compose; unknown
  task_type = exact legacy behavior (no filter).
- The pipeline's two post-dispatcher compose sites call retrieve_for_task
  with the resolved task_type (verified via mock in the engine test).
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from core.memory import MEMORY_LEVELS, MemoryComposer, level_priorities


class TestLevelPriorities:
    """Pure resolution of task type → preferred memory levels."""

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
        # None = "no filter" = exact legacy behavior
        assert level_priorities(None) is None
        assert level_priorities("") is None
        assert level_priorities("nonsense") is None

    def test_levels_are_valid_hierarchy_members(self):
        for levels in level_priorities("debug"), level_priorities("plan"):
            assert all(l in MEMORY_LEVELS for l in levels)


class TestStoreTagsLevel:
    """store() persists the memory_level metadata tag."""

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
    """Build a recall_with_scores result: [(fact, distance, metadata), ...]."""
    now = 1_700_000_000.0
    return [
        (fact, 0.10, {"timestamp": str(now), "importance": "0.6", "access_count": "0", "id": f"id{i}", **meta})
        for i, (fact, meta) in enumerate(facts)
    ]


class TestComposeLevelFilter:
    """compose(levels=...) filters facts by their memory_level tag."""

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
        """Pre-P1 facts carry no memory_level → treated as long_term."""
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
                [
                    ("recent stack trace", {"memory_level": "session"}),
                    ("user prefers dark mode", {}),
                ]
            )
        )
        from core.models import Intent

        facts = await composer.compose("trace and error context", Intent.FILE_TASK, "s1")
        assert set(facts) == {"recent stack trace", "user prefers dark mode"}


class TestRetrieveForTask:
    """retrieve_for_task() resolves task_type → levels → compose."""

    @pytest.mark.asyncio
    async def test_unknown_task_type_passes_none_levels(self):
        composer = MemoryComposer()
        composer._store = AsyncMock()
        composer._store.recall_with_scores.return_value = _recall_fixture(
            [("user prefers dark mode", {})]
        )
        composer._store.count.return_value = 50
        # Spy on compose to verify levels=None is passed through unchanged.
        original_compose = composer.compose
        called = {}

        async def _spy(query, intent, session_id, top_k=6, levels=None):
            called["levels"] = levels
            return await original_compose(query, intent, session_id, top_k=top_k, levels=levels)

        composer.compose = _spy
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

        async def _spy(query, intent, session_id, top_k=6, levels=None):
            called["levels"] = levels
            return await original_compose(query, intent, session_id, top_k=top_k, levels=levels)

        composer.compose = _spy
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


class TestEngineWiresLevelAwareRetrieval:
    """The pipeline's post-dispatcher memory path calls retrieve_for_task
    with the resolved task_type (ADR-19 P1 wiring)."""

    @pytest.mark.asyncio
    async def test_agent_path_calls_retrieve_for_task(self):
        """An explicit canonical dispatcher hint (task_type='code') on a
        SHELL agent turn flows into the level-aware retrieval unchanged
        (ADR-19 P1 wiring, re-used by the Session 186 re-key tests)."""
        composer = await self._run_engine_agent_turn("sess-177", hint="code")
        # The level-aware re-retrieval must have called retrieve_for_task
        # with task_type="code" (code → project/session levels).
        assert composer.retrieve_for_task.await_count >= 1
        _, kwargs = composer.retrieve_for_task.await_args
        assert kwargs.get("task_type") == "code"

    # ── ADR-19 x ADR-22 re-key (Session 186) ────────────────────────────────
    # The dispatcher task_type is now a HINT: the agent settles the real
    # task type during planning (intent is the settled routing for AGENT
    # turns). The engine re-resolves hint + intent BEFORE level-aware
    # memory retrieval, so a misclassified/empty hint can no longer key the
    # wrong memory levels.

    async def _run_engine_agent_turn(self, session_id: str, hint: str = ""):
        """Drive Engine.process through the AGENT_LOOP path with a shell
        dispatcher stub carrying the given task_type hint. Returns the
        memory composer (to inspect the retrieve_for_task calls)."""
        from unittest.mock import MagicMock, patch

        from core.engine import Engine
        from core.models import (
            ExecutionMode,
            OrchestrationPlan,
            StreamChunk,
            TaskProfile,
        )

        engine = Engine()
        composer = AsyncMock()
        composer.retrieve_for_task.return_value = []
        composer.warm_start_facts.return_value = []
        composer.compose.return_value = []
        engine._memory = composer

        class _ShellDispatcher:
            def __init__(self, adapter):
                self._adapter = adapter

            async def dispatch(self, **kwargs):
                yield OrchestrationPlan(
                    profile=TaskProfile(
                        capabilities=["shell"],
                        execution_mode=ExecutionMode.AGENT_LOOP,
                        confidence=0.9,
                        reformulated="build the frontend app",
                        acknowledgement="Building that...",
                    ),
                    success_criteria=["app builds"],
                    fast_path=False,
                    dispatch_steps=[{"intent": "shell", "detail": "Build the app"}],
                    task_type=hint,
                )

        async def _fake_loop_run(**kwargs):
            yield StreamChunk(text="done", done=True)

        mock_adapter = MagicMock()
        mock_adapter.effective_context_window = 8192
        with patch("core.engine._pipeline.ThinkingDispatcher", _ShellDispatcher), patch(
            "core.engine.get_adapter", return_value=mock_adapter
        ), patch("core.engine._pipeline.AGENT_SELECTION_ENABLED", False), patch.object(
            engine._agent_loop, "run", _fake_loop_run
        ):
            chunks = [
                c
                async for c in engine.process("build the frontend app", session_id)
            ]
        assert len(chunks) > 0
        return composer

    @pytest.mark.asyncio
    async def test_agent_path_settles_empty_hint_to_intent(self):
        """An EMPTY dispatcher hint on a SHELL agent turn retrieves memory
        with the SETTLED task_type 'code' (intent fallback) — the pre-fix
        behavior keyed levels off the raw hint ('' → legacy no-filter), so
        an empty/misclassified hint retrieved the wrong memory levels."""
        composer = await self._run_engine_agent_turn("sess-186a", hint="")
        assert composer.retrieve_for_task.await_count >= 1
        _, kwargs = composer.retrieve_for_task.await_args
        assert kwargs.get("task_type") == "code"

    @pytest.mark.asyncio
    async def test_agent_path_corrects_chat_hint_on_shell_task(self):
        """A 'chat' hint on a SHELL routing is a misclassification ('chat'
        is the no-tool fallback) — retrieval must key off the corrected
        'code', not the wrong hint."""
        composer = await self._run_engine_agent_turn("sess-186b", hint="chat")
        assert composer.retrieve_for_task.await_count >= 1
        _, kwargs = composer.retrieve_for_task.await_args
        assert kwargs.get("task_type") == "code"

    @pytest.mark.asyncio
    async def test_agent_path_explicit_canonical_hint_wins(self):
        """An explicit canonical hint (debug) still keys the retrieval —
        the re-key only corrects empty/misclassified hints."""
        composer = await self._run_engine_agent_turn("sess-186c", hint="debug")
        assert composer.retrieve_for_task.await_count >= 1
        _, kwargs = composer.retrieve_for_task.await_args
        assert kwargs.get("task_type") == "debug"
