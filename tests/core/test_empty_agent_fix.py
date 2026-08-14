"""
Integration tests for the "Empty Agent" fix — P1 through P12.

These tests verify that the priority improvements to LocalMind's agent
personality, memory awareness, tool execution, and sub-agent framework
are all working correctly without requiring a live Ollama instance.

Test coverage:
  P1  — Enhanced base.md personality and memory awareness
  P3  — Memory weaving (reframed as knowledge, not data)
  P5  — Parallel tool execution (MultiToolCallResult)
  P6  — Skill .md file injection into agent prompts
  P9  — Reflection loop with actionable CORRECTION output
  P10 — Expert personas (6 intent-specific personas)
  P11 — Sub-agent framework v0.2
  P12 — Cross-session memory warm-start

P2 (native tool calling), P4 (auto memory extraction), P7 (confirmation gate),
and P8 (flywheel accuracy) were already implemented before the fix session.
"""
from __future__ import annotations

import time

# Prompts moved from <repo>/core/prompts/ to <repo>/backend/src/core/prompts/
# during the backend/src/ reorganization. This constant points to the correct
# location regardless of where the test file lives.
from pathlib import Path as _Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_PROMPTS_DIR = _Path(__file__).resolve().parent.parent.parent / "backend" / "src" / "core" / "prompts"

from core.models import Intent

# ── P1: Enhanced base.md personality ───────────────────────────────────────

class TestP1EnhancedPersonality:
    """Verify that the base.md prompt file contains the expected sections."""

    def test_base_md_exists_and_has_substance(self):
        base_path = _PROMPTS_DIR / "base.md"
        assert base_path.exists(), "base.md should exist"
        content = base_path.read_text()
        # The enhanced base.md should be significantly longer than the original 2-liner
        assert len(content) > 500, f"base.md too short ({len(content)} chars) — expected rich personality"

    def test_base_md_contains_memory_awareness(self):
        base_path = _PROMPTS_DIR / "base.md"
        content = base_path.read_text().lower()
        # Memory awareness section should be present
        assert "memory" in content, "base.md should mention memory usage"
        assert "remember" in content or "knowledge" in content, "base.md should frame memory as knowledge"

    def test_base_md_contains_ambiguity_handling(self):
        base_path = _PROMPTS_DIR / "base.md"
        content = base_path.read_text().lower()
        # Should have guidance for ambiguous situations
        assert "ambig" in content or "uncertain" in content, "base.md should address ambiguity"

    def test_base_md_contains_mistake_recovery(self):
        base_path = _PROMPTS_DIR / "base.md"
        content = base_path.read_text().lower()
        # Should have guidance for handling mistakes
        assert "mistake" in content or "error" in content or "wrong" in content, "base.md should address mistakes"

    def test_base_md_contains_useful_over_impressive_value(self):
        base_path = _PROMPTS_DIR / "base.md"
        content = base_path.read_text().lower()
        # "Useful over impressive" is the 6th core value added in P1
        assert "useful" in content, "base.md should contain 'Useful over impressive' value"


# ── P3: Memory weaving reframed as knowledge ──────────────────────────────

class TestP3MemoryWeaving:
    """Verify that memory facts are framed as knowledge, not raw data."""

    def test_chat_md_frames_memory_as_knowledge(self):
        chat_path = _PROMPTS_DIR / "chat.md"
        content = chat_path.read_text().lower()
        # Should frame facts as things the agent knows, not data from a store
        assert "know" in content, "chat.md should frame memory as knowledge"

    def test_agent_prompt_frames_memory_as_knowledge(self):
        from core.agent.prompts import build_agent_system_prompt
        prompt = build_agent_system_prompt(
            intent=Intent.CHAT,
            available_tools=[],
            memory_facts=["User prefers Python", "User uses Linux"],
        )
        prompt_lower = prompt.lower()
        # Should not use mechanical "retrieved from memory store" language
        assert "memory store" not in prompt_lower, "Should not use mechanical memory language"
        # Should contain the actual facts
        assert "python" in prompt_lower, "Should contain memory facts"
        assert "linux" in prompt_lower, "Should contain memory facts"


# ── P5: Parallel tool execution (MultiToolCallResult) ─────────────────────

class TestP5ParallelToolExecution:
    """Verify MultiToolCallResult and parallel dispatch."""

    def test_multi_tool_call_result_dataclass(self):
        from adapters.ollama import MultiToolCallResult, ToolCallResult
        tc1 = ToolCallResult(tool_name="web_search", tool_args={"query": "test"}, raw_content="")
        tc2 = ToolCallResult(tool_name="code_exec", tool_args={"code": "print(1)"}, raw_content="")
        result = MultiToolCallResult(calls=[tc1, tc2])
        assert result.is_parallel is True
        assert result.first.tool_name == "web_search"
        assert len(result.calls) == 2

    def test_multi_tool_call_backward_compat(self):
        from adapters.ollama import MultiToolCallResult, ToolCallResult
        tc = ToolCallResult(tool_name="shell", tool_args={"command": "ls"}, raw_content="")
        result = MultiToolCallResult(calls=[tc])
        # .first should give backward-compatible access
        assert result.first.tool_name == "shell"
        # Single call is not parallel
        assert result.is_parallel is False


# ── P6: Skill .md file injection ──────────────────────────────────────────

class TestP6SkillInjection:
    """Verify skill .md files are injected into agent prompts."""

    def test_skill_files_exist(self):
        skills_dir = _PROMPTS_DIR / "skills"
        assert skills_dir.exists(), "skills/ directory should exist"
        skill_files = list(skills_dir.glob("*.md"))
        assert len(skill_files) >= 5, f"Expected at least 5 skill files, found {len(skill_files)}"

    def test_coding_skill_has_content(self):
        coding_path = _PROMPTS_DIR / "skills" / "coding.md"
        assert coding_path.exists(), "coding.md should exist"
        content = coding_path.read_text()
        assert len(content) > 100, "coding.md should have substantial content"
        assert "code" in content.lower() or "write" in content.lower()

    def test_skill_injected_into_agent_prompt(self):
        from core.agent.prompts import build_agent_system_prompt
        prompt = build_agent_system_prompt(
            intent=Intent.CODE_EXEC,
            available_tools=[],
            memory_facts=[],
        )
        # CODE_EXEC intent should inject coding.md content
        prompt_lower = prompt.lower()
        # The coding skill should mention something about code practices
        assert "code" in prompt_lower or "debug" in prompt_lower or "function" in prompt_lower

    def test_all_intents_mapped_to_skills(self):
        from core.context_builder import _intent_fragment_name
        # Every AGENT intent should map to a skill file
        agent_intents = [Intent.CODE_EXEC, Intent.FILE_WRITE, Intent.FILE_EDIT,
                         Intent.MEMORY_OP, Intent.SHELL]
        for intent in agent_intents:
            fragment = _intent_fragment_name(intent)
            assert fragment is not None, f"Intent {intent.value} should map to a skill fragment"
            assert len(fragment) > 0, f"Intent {intent.value} should have non-empty fragment name"


# ── P9: Reflection loop with CORRECTION ───────────────────────────────────

class TestP9ReflectionLoop:
    """Verify the reflection self-critique produces actionable corrections."""

    @pytest.mark.asyncio
    async def test_reflect_on_answer_stores_correction(self):
        """When reflection finds an issue, a correction is emitted as an obs event.
        Session 31: corrections are NO LONGER stored as visible chat messages —
        they're obs events only. This test verifies the obs event is emitted."""
        from core.engine import Engine
        engine = Engine()
        from core.obs import ObsCollector
        obs = ObsCollector()

        # Mock adapter to return a review with CORRECTION
        async def mock_chat(messages, temperature=0.0, **kwargs):
            review_text = "ISSUE: The agent fabricated file names.\nCORRECTION: The actual files are main.py and utils.py only."
            for char in review_text:
                yield MagicMock(text=char, done=False, error=None)
            yield MagicMock(text="", done=True, error=None)

        mock_adapter = MagicMock()
        mock_adapter.chat = mock_chat

        with patch("core.engine.get_adapter", return_value=mock_adapter):
            await engine._reflect_on_answer(
                # Response must be 20+ words for reflection to run
                response_text="The files in the directory are main.py, utils.py, and config.py and also some other files that were created recently by the user",
                intent=Intent.SHELL,
                message="list files",
                session_id="test-reflect-session",
                obs=obs,
            )

        # Session 31: correction should be emitted as an obs event, NOT
        # stored as a visible chat message.
        events = obs.drain()
        correction_events = [e for e in events if e.type == "reflection_correction"]
        assert len(correction_events) >= 1, (
            f"Expected at least 1 reflection_correction obs event, got {len(correction_events)}"
        )
        # The correction text should be in the event
        correction_text = correction_events[0].data.get("correction", "")
        assert "main.py" in correction_text or "utils.py" in correction_text, (
            f"Expected correction text to mention main.py/utils.py, got: {correction_text}"
        )

    @pytest.mark.asyncio
    async def test_reflect_emits_obs_event(self):
        """Reflection should emit reflection_correction obs event."""
        from core.engine import Engine
        engine = Engine()
        from core.obs import ObsCollector
        obs = ObsCollector()

        async def mock_chat(messages, temperature=0.0, **kwargs):
            review_text = "ISSUE: Wrong answer.\nCORRECTION: The correct answer is 42 and this is a long enough correction text."
            for char in review_text:
                yield MagicMock(text=char, done=False, error=None)
            yield MagicMock(text="", done=True, error=None)

        mock_adapter = MagicMock()
        mock_adapter.chat = mock_chat

        with patch("core.engine.get_adapter", return_value=mock_adapter):
            await engine._reflect_on_answer(
                # Response must be 20+ words for reflection to run
                response_text="The answer is seven which is completely wrong and this needs to be a long enough response for reflection to even run on it properly.",
                intent=Intent.CODE_EXEC,
                message="what is 6*7",
                session_id="test-obs-reflect",
                obs=obs,
            )

        events = obs.drain()
        correction_events = [e for e in events if e.type == "reflection_correction"]
        assert len(correction_events) >= 1, f"Should emit reflection_correction event, got {[e.type for e in events]}"

    @pytest.mark.asyncio
    async def test_reflect_skips_short_responses(self):
        """Very short responses should be skipped for reflection."""
        from core.engine import Engine
        engine = Engine()
        engine._store = MagicMock()

        from core.obs import ObsCollector
        obs = ObsCollector()

        # Should not make any adapter calls for short responses
        await engine._reflect_on_answer(
            response_text="OK",
            intent=Intent.SHELL,
            message="test",
            session_id="test-short-reflect",
            obs=obs,
        )

        # No store.append calls — no correction for short responses
        engine._store.append.assert_not_called()


# ── P10: Expert personas ──────────────────────────────────────────────────

class TestP10ExpertPersonas:
    """Verify intent-specific expert personas are injected into prompts."""

    def test_coder_persona_for_code_exec(self):
        from core.agent.prompts import build_agent_system_prompt
        prompt = build_agent_system_prompt(
            intent=Intent.CODE_EXEC,
            available_tools=[],
            memory_facts=[],
        )
        prompt_lower = prompt.lower()
        # Should have The Coder persona characteristics
        assert "code" in prompt_lower or "coder" in prompt_lower or "engineer" in prompt_lower

    def test_writer_persona_for_file_write(self):
        from core.agent.prompts import build_agent_system_prompt
        prompt = build_agent_system_prompt(
            intent=Intent.FILE_WRITE,
            available_tools=[],
            memory_facts=[],
        )
        prompt_lower = prompt.lower()
        # Should have The Writer persona characteristics
        assert "write" in prompt_lower or "writer" in prompt_lower or "content" in prompt_lower

    def test_debugger_persona_for_file_edit(self):
        from core.agent.prompts import build_agent_system_prompt
        prompt = build_agent_system_prompt(
            intent=Intent.FILE_EDIT,
            available_tools=[],
            memory_facts=[],
        )
        prompt_lower = prompt.lower()
        # Should have The Debugger persona characteristics
        assert "debug" in prompt_lower or "fix" in prompt_lower or "diagnos" in prompt_lower

    def test_researcher_persona_for_web_search(self):
        from core.agent.prompts import build_agent_system_prompt
        prompt = build_agent_system_prompt(
            intent=Intent.WEB_SEARCH,
            available_tools=[],
            memory_facts=[],
        )
        prompt_lower = prompt.lower()
        # Should have The Researcher persona characteristics
        assert "research" in prompt_lower or "search" in prompt_lower or "fact" in prompt_lower

    def test_operator_persona_for_shell(self):
        from core.agent.prompts import build_agent_system_prompt
        prompt = build_agent_system_prompt(
            intent=Intent.SHELL,
            available_tools=[],
            memory_facts=[],
        )
        prompt_lower = prompt.lower()
        # Should have The Operator persona characteristics
        assert "shell" in prompt_lower or "command" in prompt_lower or "system" in prompt_lower

    def test_archivist_persona_for_memory_op(self):
        from core.agent.prompts import build_agent_system_prompt
        prompt = build_agent_system_prompt(
            intent=Intent.MEMORY_OP,
            available_tools=[],
            memory_facts=[],
        )
        prompt_lower = prompt.lower()
        # Should have The Archivist persona characteristics
        assert "memory" in prompt_lower or "fact" in prompt_lower or "store" in prompt_lower


# ── ADR-8: Agent-owned delegation routing ─────────────────────────────────

class TestAgentOwnedDelegationRouting:
    """The parent agent owns cross-domain delegation; no legacy heuristic remains."""

    def test_legacy_sub_agent_module_is_removed(self):
        from pathlib import Path

        module_path = Path(__file__).parents[2] / "backend" / "src" / "core" / "agent" / "sub_agent.py"
        assert not module_path.exists()

    def test_task_profile_selects_coding_agent_with_delegation_tools(self):
        from agents import select_agent_by_task_profile
        from core.models import Intent

        agent_class = select_agent_by_task_profile("shell_command", Intent.SHELL)
        assert agent_class is not None
        config = agent_class(adapter=None).config()
        assert config.name == "coding"
        assert "delegate" in config.allowed_tools
        assert "delegate_parallel" in config.allowed_tools

    def test_task_profile_selects_research_agent_for_web_search(self):
        from agents import select_agent_by_task_profile
        from core.models import Intent

        agent_class = select_agent_by_task_profile("web_search", Intent.WEB_SEARCH)
        assert agent_class is not None
        config = agent_class(adapter=None).config()
        assert config.name == "research"
        assert "delegate" in config.allowed_tools


# ── P12: Cross-session memory warm-start ──────────────────────────────────

class TestP12CrossSessionWarmStart:
    """Verify cross-session memory warm-start for new sessions."""

    @pytest.mark.asyncio
    async def test_warm_start_returns_recent_important_facts(self):
        from core.memory import MemoryComposer
        composer = MemoryComposer()
        mock_store = AsyncMock()
        now = time.time()
        mock_store.list_all_with_metadata.return_value = [
            {"fact": "User prefers Python for scripting", "timestamp": str(now), "importance": "0.8", "access_count": "5"},
            {"fact": "User runs Ubuntu 22.04", "timestamp": str(now), "importance": "0.7", "access_count": "3"},
            {"fact": "User's project is called DataPipeline", "timestamp": str(now - 86400 * 10), "importance": "0.5", "access_count": "1"},
        ]
        composer._store = mock_store
        facts = await composer.warm_start_facts(session_id="new-session")
        assert len(facts) >= 1, "Warm-start should return at least one fact"
        # Most important/recent facts should come first
        assert any("python" in f.lower() for f in facts), "Should include Python preference"

    @pytest.mark.asyncio
    async def test_warm_start_max_facts_cap(self):
        from core.memory import MemoryComposer
        composer = MemoryComposer()
        mock_store = AsyncMock()
        now = time.time()
        many_facts = [
            {"fact": f"Fact number {i}", "timestamp": str(now - i * 100), "importance": "0.5", "access_count": "0"}
            for i in range(20)
        ]
        mock_store.list_all_with_metadata.return_value = many_facts
        composer._store = mock_store
        facts = await composer.warm_start_facts(session_id="new-session", max_facts=3)
        assert len(facts) <= 3, f"Warm-start should respect max_facts cap, got {len(facts)}"

    @pytest.mark.asyncio
    async def test_warm_start_high_importance_boosted(self):
        from core.memory import MemoryComposer
        composer = MemoryComposer()
        mock_store = AsyncMock()
        now = time.time()
        # Old but very important fact
        mock_store.list_all_with_metadata.return_value = [
            {"fact": "Critical: User has a nut allergy", "timestamp": str(now - 86400 * 20), "importance": "0.9", "access_count": "1"},
            {"fact": "Recent trivial note", "timestamp": str(now - 100), "importance": "0.2", "access_count": "0"},
        ]
        composer._store = mock_store
        facts = await composer.warm_start_facts(session_id="new-session")
        # High-importance facts should be boosted even when old
        assert any("nut" in f.lower() or "allergy" in f.lower() for f in facts), \
            "High-importance facts should be included even when old"

    @pytest.mark.asyncio
    async def test_warm_start_excludes_very_old_facts(self):
        from core.memory import MemoryComposer
        composer = MemoryComposer()
        mock_store = AsyncMock()
        very_old = time.time() - 86400 * 60  # 60 days ago
        mock_store.list_all_with_metadata.return_value = [
            {"fact": "Ancient fact from months ago", "timestamp": str(very_old), "importance": "0.3", "access_count": "0"},
        ]
        composer._store = mock_store
        facts = await composer.warm_start_facts(session_id="new-session")
        # Very old, low-importance facts should be excluded
        assert len(facts) == 0, "Very old low-importance facts should be excluded"

    @pytest.mark.asyncio
    async def test_warm_start_no_embedding_overhead(self):
        """Warm-start should use metadata only, no embedding calls."""
        from core.memory import MemoryComposer
        composer = MemoryComposer()
        mock_store = AsyncMock()
        mock_store.list_all_with_metadata.return_value = []

        # Ensure recall_with_scores is NOT called (would require embedding)
        composer._store = mock_store
        await composer.warm_start_facts(session_id="test")
        mock_store.recall_with_scores.assert_not_called()


# ── Constants and config ──────────────────────────────────────────────────

class TestAgentConstants:
    """Verify agent constants are set correctly for the enhanced agent."""

    def test_reflect_enabled(self):
        from core.agent.constants import REFLECT_ENABLED
        assert REFLECT_ENABLED is True

    def test_reflect_max_tokens_reasonable(self):
        from core.agent.constants import REFLECT_MAX_TOKENS
        assert 100 <= REFLECT_MAX_TOKENS <= 512, "Reflection tokens should be reasonable"

    def test_reflect_intents_excludes_chat(self):
        from core.agent.constants import REFLECT_INTENTS
        assert Intent.CHAT not in REFLECT_INTENTS, "CHAT should not be reflected"

    def test_plan_enabled(self):
        from core.agent.constants import PLAN_ENABLED
        assert PLAN_ENABLED is True

    def test_verify_enabled(self):
        from core.agent.constants import VERIFY_ENABLED
        assert VERIFY_ENABLED is True

    def test_max_iterations_sufficient(self):
        from core.agent.constants import MAX_ITERATIONS
        assert MAX_ITERATIONS >= 3, f"Need enough iterations for Plan→Execute→Verify, got {MAX_ITERATIONS}"

    def test_agent_intents_include_shell(self):
        from core.agent.constants import AGENT_INTENTS
        assert Intent.SHELL in AGENT_INTENTS, "SHELL should go through agent loop"
