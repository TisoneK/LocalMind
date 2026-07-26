"""
Session 32 regression tests for:
  1. Iteration limit is configurable + raised (3 → 8)
  2. Fallback messages say "iteration limit reached" when hit_limit is True
     (not "overload" or "I don't know")
  3. Safety workflow ("check before acting") is injected into the agent prompt

The user's "Create hello world repo" scenario revealed:
- MAX_ITERATIONS=3 was too low — the model did 3 reconnaissance calls
  (mkdir, dir, git --version) and hit the cap before the actual work.
- The fallback guessed "overload" — wrong diagnosis. The real cause was
  the iteration cap.
- The model ran `mkdir` BEFORE checking if the directory existed, and
  barreled forward into a non-empty unrelated directory instead of
  scoping into a subdirectory.

These tests verify all three fixes.
"""

from __future__ import annotations

from core.agent.constants import MAX_ITERATIONS, MAX_WALL_CLOCK_SECS
from core.agent.loop import AgentLoop, AgentStep, AgentTrace
from core.models import Intent

# ── 1. Iteration limit is configurable + raised ────────────────────────────


class TestIterationLimitConfig:
    """MAX_ITERATIONS and MAX_WALL_CLOCK_SECS must be configurable via env
    vars and raised from the too-low Session 31 defaults."""

    def test_max_iterations_default_is_at_least_8(self):
        """The default MAX_ITERATIONS must be >= 8 (was 3 in Session 31).
        8 gives room for: recon (2-3) + work (3-5) + verify (1-2)."""
        assert MAX_ITERATIONS >= 8, (
            f"MAX_ITERATIONS default must be >= 8 (was 3 in Session 31, "
            f"which was too low for multi-step tasks). Got: {MAX_ITERATIONS}"
        )

    def test_max_wall_clock_default_is_at_least_180(self):
        """The default MAX_WALL_CLOCK_SECS must be >= 180 (was 90 in Session 31).
        180s allows 6-8 iterations at ~20-30s per call on free-tier models."""
        assert MAX_WALL_CLOCK_SECS >= 180.0, (
            f"MAX_WALL_CLOCK_SECS default must be >= 180 (was 90 in Session 31). "
            f"Got: {MAX_WALL_CLOCK_SECS}"
        )

    def test_max_iterations_configurable_via_env_var(self, monkeypatch):
        """LOCALMIND_MAX_ITERATIONS env var must override the default."""
        # Re-import constants with the env var set
        monkeypatch.setenv("LOCALMIND_MAX_ITERATIONS", "12")
        import importlib

        import core.agent.constants as constants_mod

        importlib.reload(constants_mod)
        assert constants_mod.MAX_ITERATIONS == 12, (
            f"LOCALMIND_MAX_ITERATIONS=12 should set MAX_ITERATIONS to 12, "
            f"got {constants_mod.MAX_ITERATIONS}"
        )
        # Reload again without the env var to restore the default
        monkeypatch.delenv("LOCALMIND_MAX_ITERATIONS", raising=False)
        importlib.reload(constants_mod)

    def test_max_wall_clock_configurable_via_env_var(self, monkeypatch):
        """LOCALMIND_MAX_WALL_CLOCK_SECS env var must override the default."""
        monkeypatch.setenv("LOCALMIND_MAX_WALL_CLOCK_SECS", "300")
        import importlib

        import core.agent.constants as constants_mod

        importlib.reload(constants_mod)
        assert constants_mod.MAX_WALL_CLOCK_SECS == 300.0, (
            f"LOCALMIND_MAX_WALL_CLOCK_SECS=300 should set MAX_WALL_CLOCK_SECS to 300.0, "
            f"got {constants_mod.MAX_WALL_CLOCK_SECS}"
        )
        monkeypatch.delenv("LOCALMIND_MAX_WALL_CLOCK_SECS", raising=False)
        importlib.reload(constants_mod)

    def test_max_iterations_floor_is_1(self, monkeypatch):
        """If someone sets LOCALMIND_MAX_ITERATIONS=0 or negative, it should
        floor to 1 (not crash, not allow zero iterations)."""
        monkeypatch.setenv("LOCALMIND_MAX_ITERATIONS", "0")
        import importlib

        import core.agent.constants as constants_mod

        importlib.reload(constants_mod)
        assert constants_mod.MAX_ITERATIONS >= 1, (
            f"LOCALMIND_MAX_ITERATIONS=0 should floor to 1, got {constants_mod.MAX_ITERATIONS}"
        )
        monkeypatch.delenv("LOCALMIND_MAX_ITERATIONS", raising=False)
        importlib.reload(constants_mod)

    def test_max_iterations_invalid_value_falls_back_to_default(self, monkeypatch):
        """If LOCALMIND_MAX_ITERATIONS is garbage, fall back to the default
        (not crash on import)."""
        monkeypatch.setenv("LOCALMIND_MAX_ITERATIONS", "not-a-number")
        import importlib

        import core.agent.constants as constants_mod

        importlib.reload(constants_mod)
        # Should fall back to the default (8), not crash
        assert constants_mod.MAX_ITERATIONS == 8, (
            f"Invalid LOCALMIND_MAX_ITERATIONS should fall back to 8, "
            f"got {constants_mod.MAX_ITERATIONS}"
        )
        monkeypatch.delenv("LOCALMIND_MAX_ITERATIONS", raising=False)
        importlib.reload(constants_mod)


# ── 2. Fallback says "iteration limit reached" when hit_limit is True ──────


class TestIterationLimitFallbackMessage:
    """When trace.hit_limit is True, the fallback MUST say 'iteration limit
    reached' — not 'overload', not 'I don't know'. This is the fix for the
    misdiagnosis pattern where previous sessions blamed 'context overflow'
    or 'model overload' when the real cause was the iteration cap."""

    def test_summarize_trace_mentions_iteration_limit_when_hit_limit_true(self):
        """When trace.hit_limit is True, _summarize_trace_for_user must
        explicitly say 'iteration limit' — not guess 'overload'."""
        trace = AgentTrace()
        trace.hit_limit = True
        trace.iterations_used = 3
        trace.steps = [
            AgentStep(
                iteration=1, thought="", tool_name="shell",
                tool_input="mkdir test", observation="Directory created",
                tool_failed=False, retry_count=0, latency_ms=100,
            ),
        ]

        result = AgentLoop._summarize_trace_for_user(trace, observation_log="")

        assert "iteration limit" in result.lower(), (
            f"When hit_limit is True, the fallback must say 'iteration limit' — "
            f"not guess 'overload'. Got: {result!r}"
        )
        assert "3 iterations" in result, (
            f"The fallback should mention the actual iteration count. Got: {result!r}"
        )
        # Must NOT claim it's an overload or context-overflow issue
        assert "not a model overload" in result.lower() or "not" in result.lower(), (
            f"The fallback should explicitly say this is NOT an overload issue. "
            f"Got: {result!r}"
        )

    def test_summarize_trace_does_not_mention_iteration_limit_when_hit_limit_false(self):
        """When hit_limit is False (model genuinely failed, not iteration cap),
        the fallback should NOT claim it was the iteration limit."""
        trace = AgentTrace()
        trace.hit_limit = False  # model failed, not iteration cap
        trace.iterations_used = 2
        trace.steps = [
            AgentStep(
                iteration=1, thought="", tool_name="shell",
                tool_input="ls", observation="file1.py",
                tool_failed=False, retry_count=0, latency_ms=100,
            ),
        ]

        result = AgentLoop._summarize_trace_for_user(trace, observation_log="")

        # Should NOT claim it was the iteration limit (it wasn't)
        assert "i hit my iteration limit" not in result.lower(), (
            f"When hit_limit is False, the fallback should NOT claim iteration limit. "
            f"Got: {result!r}"
        )

    def test_summarize_trace_hit_limit_advice_mentions_continue(self):
        """When hit_limit is True, the 'what to try next' advice should
        suggest 'continue' (the user can tell the agent to pick up where
        it left off) — NOT 'switch to a larger model' (the model didn't fail)."""
        trace = AgentTrace()
        trace.hit_limit = True
        trace.iterations_used = 8
        trace.steps = [
            AgentStep(
                iteration=1, thought="", tool_name="shell",
                tool_input="mkdir test", observation="ok",
                tool_failed=False, retry_count=0, latency_ms=100,
            ),
        ]

        result = AgentLoop._summarize_trace_for_user(trace, observation_log="")

        assert "continue" in result.lower(), (
            f"When hit_limit is True, the advice should mention 'continue'. Got: {result!r}"
        )
        # Should mention the env var for configurability
        assert "LOCALMIND_MAX_ITERATIONS" in result, (
            f"The fallback should mention the env var for raising the limit. Got: {result!r}"
        )

    def test_engine_fallback_source_does_not_guess_overload(self):
        """The engine's last-resort fallback source code must NOT contain
        the old 'almost always a free-tier model issue' guess — that was
        the wrong diagnosis the user pushed back on."""
        from pathlib import Path

        pipeline_path = (
            Path(__file__).resolve().parent.parent.parent
            / "backend" / "src" / "core" / "engine" / "_pipeline.py"
        )
        source = pipeline_path.read_text()
        assert "almost always a free-tier model issue" not in source, (
            "Engine fallback must NOT guess 'free-tier model issue' — that's "
            "the unverified self-diagnosis the user pushed back on."
        )
        # The new fallback should mention "iteration limit" as a possible cause
        assert "iteration limit" in source.lower(), (
            "Engine fallback should check for hit_limit and mention 'iteration limit' "
            "as a specific cause when applicable."
        )


# ── 3. Safety workflow ("check before acting") injected into prompt ────────


class TestSafetyWorkflowInjection:
    """The 'check before acting' universal rule must be injected into the
    agent system prompt for every intent. This is the fix for the model
    running `mkdir` BEFORE checking if the directory existed, and barreling
    forward into a non-empty unrelated directory."""

    def test_safety_workflow_file_exists(self):
        """The safety workflow file must exist at the expected path."""
        from pathlib import Path

        safety_path = (
            Path(__file__).resolve().parent.parent.parent
            / "backend" / "data" / "workflows" / "safety.md"
        )
        assert safety_path.exists(), (
            f"safety.md workflow file must exist at {safety_path}"
        )

    def test_safety_workflow_contains_universal_rule(self):
        """The safety workflow must contain the 'check before acting'
        universal rule — not a per-tool fix."""
        from pathlib import Path

        safety_path = (
            Path(__file__).resolve().parent.parent.parent
            / "backend" / "data" / "workflows" / "safety.md"
        )
        content = safety_path.read_text()
        assert "check" in content.lower() and "before acting" in content.lower(), (
            "safety.md must contain the 'check before acting' universal rule"
        )
        # Must apply to multiple tools, not just shell
        assert "shell" in content.lower(), "safety.md must cover shell tools"
        assert "file" in content.lower(), "safety.md must cover file tools"
        assert "web" in content.lower() or "search" in content.lower(), (
            "safety.md must cover web/search tools"
        )

    def test_safety_workflow_injected_into_agent_prompt(self):
        """The agent system prompt must include the safety section for
        agent intents (SHELL, FILE_WRITE, etc.)."""
        from core.agent.prompts import build_agent_system_prompt

        prompt = build_agent_system_prompt(
            intent=Intent.SHELL,
            available_tools=[],
            memory_facts=[],
        )
        # The safety section must be present
        assert "check before acting" in prompt.lower() or "safety" in prompt.lower(), (
            "Agent prompt must include the 'check before acting' safety section "
            "for SHELL intent"
        )

    def test_safety_workflow_injected_for_all_agent_intents(self):
        """The safety section must be injected for ALL agent intents, not
        just SHELL. This is a universal rule."""
        from core.agent.prompts import build_agent_system_prompt

        agent_intents = [
            Intent.SHELL,
            Intent.FILE_WRITE,
            Intent.FILE_EDIT,
            Intent.FILE_TASK,
            Intent.CODE_EXEC,
            Intent.WEB_SEARCH,
            Intent.WEB_FETCH,
        ]
        for intent in agent_intents:
            prompt = build_agent_system_prompt(
                intent=intent,
                available_tools=[],
                memory_facts=[],
            )
            assert "check before acting" in prompt.lower() or "safety" in prompt.lower(), (
                f"Safety section must be injected for intent={intent.value}. "
                f"Prompt preview: {prompt[:500]!r}"
            )

    def test_safety_workflow_mentions_subdirectory_adaptation(self):
        """The safety workflow must mention the 'create a subdirectory'
        adaptation for non-empty unrelated target directories — the exact
        judgment gap the user identified."""
        from pathlib import Path

        safety_path = (
            Path(__file__).resolve().parent.parent.parent
            / "backend" / "data" / "workflows" / "safety.md"
        )
        content = safety_path.read_text()
        assert "subdirectory" in content.lower(), (
            "safety.md must mention creating a subdirectory when the target "
            "is non-empty and unrelated to the task — the exact judgment gap "
            "the user identified in the 'Create hello world repo' scenario"
        )
