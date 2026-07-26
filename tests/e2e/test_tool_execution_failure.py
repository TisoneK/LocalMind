"""
Session 31: E2E regression tests for the "Tools execution failure" bug.

The bug: when the agent loop completes (tools ran, MAX_ITERATIONS hit),
but the model returns an empty stream during final synthesis, the engine
fell back to a uselessly generic message:

    "I wasn't able to complete that request. The tool may have failed
     or returned no useful output. Please try rephrasing your request."

This message:
  1. Tells the user nothing about what tools actually ran
  2. Mis-attributes the failure to the user's phrasing (almost never the cause)
  3. Gives no concrete next step beyond "rephrase"

The fix (this session):
  - AgentLoop._force_final_answer() now tracks whether the model produced
    any non-empty text. If not, it yields a fallback that surfaces the
    observation log (failed-tool details) OR a clear "model overload"
    suggestion.
  - AgentLoop streaming path now checks if full_text is empty after the
    model stream ends (all chunks filtered out). If so, yields a
    _summarize_trace_for_user() fallback that lists every tool that ran.
  - Engine._pipeline.py fallback message replaced with intent-aware text
    that suggests concrete next steps (switch model, one step at a time).

These tests verify all three fix points + the end-to-end behavior.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.agent.loop import AgentLoop
from core.models import Intent, StreamChunk

# ── 1. _force_final_answer: empty model stream yields observation log ─────


class TestForceFinalAnswerEmptyStream:
    """When the model returns zero chunks (or all chunks are empty),
    _force_final_answer must yield a meaningful fallback — not silently
    return nothing."""

    @pytest.mark.asyncio
    async def test_empty_stream_yields_fallback_with_observation_log(self):
        """If observation_log has content, the fallback should include it."""
        loop = AgentLoop(adapter=MagicMock())

        # Adapter that yields ZERO chunks (model returned empty stream)
        async def empty_chat(messages, temperature=0.4):
            return
            yield  # make this an async generator

        mock_adapter = MagicMock()
        mock_adapter.chat = empty_chat

        observation_log = (
            "[Tool: shell | Input: mkdir test_repo | Status: FAILED | 120ms]\n"
            "Command failed: permission denied\n"
        )

        chunks = []
        async for chunk in loop._force_final_answer(
            loop_messages=[{"role": "user", "content": "test"}],
            observation_log=observation_log,
            active_adapter=mock_adapter,
        ):
            chunks.append(chunk)

        # MUST yield at least one chunk — never silently return empty
        assert len(chunks) >= 1, (
            "_force_final_answer must yield a fallback on empty model stream — "
            "silently returning nothing causes the engine's generic "
            "'I wasn't able to complete that request' message."
        )
        text = "".join(c.text for c in chunks)
        assert text.strip(), "Fallback text must be non-empty"
        # Should surface the observation log content (not just a generic message)
        assert "shell" in text.lower() or "permission denied" in text.lower(), (
            "Fallback should surface what tools actually ran (from observation_log), "
            f"got: {text!r}"
        )

    @pytest.mark.asyncio
    async def test_empty_stream_with_empty_observation_log_yields_model_suggestion(self):
        """If observation_log is empty (all tools succeeded), the fallback
        should suggest switching models / one step at a time — not the
        generic 'rephrase your request' message."""
        loop = AgentLoop(adapter=MagicMock())

        async def empty_chat(messages, temperature=0.4):
            return
            yield

        mock_adapter = MagicMock()
        mock_adapter.chat = empty_chat

        chunks = []
        async for chunk in loop._force_final_answer(
            loop_messages=[{"role": "user", "content": "test"}],
            observation_log="",  # no failed tools
            active_adapter=mock_adapter,
        ):
            chunks.append(chunk)

        assert len(chunks) >= 1
        text = "".join(c.text for c in chunks)
        assert text.strip()
        # Should suggest concrete next steps
        assert "model" in text.lower() or "switch" in text.lower(), (
            "Fallback should suggest switching models or other concrete next steps, "
            f"got: {text!r}"
        )
        # MUST NOT contain the old generic message
        assert "rephrasing" not in text.lower(), (
            "Old generic 'rephrasing your request' message must be gone"
        )

    @pytest.mark.asyncio
    async def test_nonempty_stream_passes_through_unchanged(self):
        """When the model DOES return text, the fallback must NOT fire."""
        loop = AgentLoop(adapter=MagicMock())

        async def chat_with_text(messages, temperature=0.4):
            yield StreamChunk(text="I created the repo at ", done=False)
            yield StreamChunk(text="C:\\Users\\test\\hello", done=False)
            yield StreamChunk(text="", done=True)

        mock_adapter = MagicMock()
        mock_adapter.chat = chat_with_text

        chunks = []
        async for chunk in loop._force_final_answer(
            loop_messages=[{"role": "user", "content": "test"}],
            observation_log="[Tool: shell | Status: OK]",
            active_adapter=mock_adapter,
        ):
            chunks.append(chunk)

        text = "".join(c.text for c in chunks)
        assert "I created the repo" in text
        # Must NOT contain the fallback text
        assert "couldn't synthesize" not in text.lower()
        assert "empty response" not in text.lower()


# ── 2. _summarize_trace_for_user: lists tools that actually ran ────────────


class TestSummarizeTraceForUser:
    """The trace-summary helper builds a user-facing list of tools that ran,
    so the user knows what happened even when the model output is empty."""

    def test_returns_empty_string_when_no_tools_ran(self):
        """If the trace has only thinking steps (no tool calls), return empty
        so the caller knows there's nothing to summarize."""
        from core.agent.loop import AgentStep, AgentTrace

        trace = AgentTrace()
        trace.steps = [
            AgentStep(
                iteration=1, thought="I should help", tool_name=None,
                tool_input=None, observation=None,
            ),
        ]
        result = AgentLoop._summarize_trace_for_user(trace, observation_log="")
        assert result == "", (
            "Empty trace (no tools) should return empty string so caller "
            "falls through to model-overload suggestion"
        )

    def test_lists_each_tool_call_with_status(self):
        """When tools ran, the summary should list each one with its status."""
        from core.agent.loop import AgentStep, AgentTrace

        trace = AgentTrace()
        trace.steps = [
            AgentStep(
                iteration=1, thought="", tool_name="shell",
                tool_input="mkdir test_repo", observation="",
                tool_failed=False, retry_count=0, latency_ms=100,
            ),
            AgentStep(
                iteration=2, thought="", tool_name="file_write",
                tool_input="hello.py: print('hi')", observation="",
                tool_failed=False, retry_count=0, latency_ms=50,
            ),
        ]
        result = AgentLoop._summarize_trace_for_user(trace, observation_log="")
        assert "shell" in result
        assert "file_write" in result
        assert "mkdir test_repo" in result
        assert "ok" in result.lower()  # both succeeded

    def test_includes_error_snippet_for_failed_tools(self):
        """When a tool failed, the summary should surface the error."""
        from core.agent.loop import AgentStep, AgentTrace

        trace = AgentTrace()
        trace.steps = [
            AgentStep(
                iteration=1, thought="", tool_name="shell",
                tool_input="rm -rf /", observation="Command blocked for safety",
                tool_failed=True, retry_count=0, latency_ms=10,
            ),
        ]
        result = AgentLoop._summarize_trace_for_user(trace, observation_log="")
        assert "shell" in result
        assert "failed" in result.lower()
        assert "Command blocked" in result

    def test_includes_observation_log_when_present(self):
        """When observation_log has content, surface it under 'Details:'."""
        from core.agent.loop import AgentStep, AgentTrace

        trace = AgentTrace()
        trace.steps = [
            AgentStep(
                iteration=1, thought="", tool_name="shell",
                tool_input="ls", observation="",
                tool_failed=True, retry_count=0, latency_ms=10,
            ),
        ]
        obs_log = "[Tool: shell | Status: FAILED]\nPermission denied\n"
        result = AgentLoop._summarize_trace_for_user(trace, observation_log=obs_log)
        assert "Details:" in result
        assert "Permission denied" in result

    def test_suggests_switching_models(self):
        """The summary should suggest switching models or one-step-at-a-time."""
        from core.agent.loop import AgentStep, AgentTrace

        trace = AgentTrace()
        trace.steps = [
            AgentStep(
                iteration=1, thought="", tool_name="shell",
                tool_input="ls", observation="",
                tool_failed=False, retry_count=0, latency_ms=10,
            ),
        ]
        result = AgentLoop._summarize_trace_for_user(trace, observation_log="")
        assert "model" in result.lower() or "switch" in result.lower(), (
            "Summary should suggest switching models as a concrete next step"
        )


# ── 3. Engine fallback: intent-aware message, not generic "rephrase" ──────


class TestEngineFallbackMessage:
    """The engine's last-resort fallback (when the agent loop yields ZERO
    text even after its own fallbacks) must be intent-aware and suggest
    concrete next steps — not the old generic 'rephrase your request'."""

    def test_old_generic_message_is_gone_from_source(self):
        """The exact old message string must no longer appear in the source."""
        from pathlib import Path

        pipeline_path = (
            Path(__file__).resolve().parent.parent.parent
            / "backend" / "src" / "core" / "engine" / "_pipeline.py"
        )
        source = pipeline_path.read_text()
        # The old message attributed failure to the user's phrasing —
        # this mis-attribution is the core UX bug we're fixing.
        assert "Please try rephrasing your request" not in source, (
            "Old generic 'Please try rephrasing your request' message must be removed "
            "from _pipeline.py — it mis-attributes the failure to the user's phrasing."
        )
        assert "tool may have failed or returned no useful output" not in source, (
            "Old generic 'tool may have failed or returned no useful output' message "
            "must be removed — it tells the user nothing useful."
        )

    def test_new_fallback_mentions_concrete_next_steps(self):
        """The new fallback should suggest switching models / one-step-at-a-time."""
        from pathlib import Path

        pipeline_path = (
            Path(__file__).resolve().parent.parent.parent
            / "backend" / "src" / "core" / "engine" / "_pipeline.py"
        )
        source = pipeline_path.read_text()
        # New message must mention at least one concrete next step
        assert "Switch to a larger model" in source, (
            "New fallback should suggest switching to a larger model"
        )
        assert "one step at a time" in source, (
            "New fallback should suggest doing one step at a time"
        )


# ── 4. End-to-end: simulate the user's exact scenario ────────────────────


class TestEndToEndSilentFailureScenario:
    """Simulate the user's reported scenario:
       - User asks: "Create hello world repo in C:\\Users\\tison\\..."
       - Model calls shell + file_write (both succeed)
       - Model returns empty stream during synthesis
       - User MUST get a meaningful message (not the generic one)

    This test verifies the fix at the AgentLoop level — the engine
    pipeline has too many side effects (DB, SSE, session state) to test
    cleanly here. The loop-level test is sufficient because the engine's
    fallback only fires when the loop yields zero text chunks, and we've
    made the loop ALWAYS yield text on the silent-failure path.
    """

    @pytest.mark.asyncio
    async def test_loop_yields_meaningful_text_when_model_returns_empty(self):
        """After MAX_ITERATIONS with tool calls, if _force_final_answer
        gets an empty model stream, the loop must still yield text —
        either the observation log summary or the model-overload message."""
        from adapters.ollama import ToolCallResult

        loop = AgentLoop(adapter=MagicMock())

        # Mock adapter: iter 1 = shell tool call, iter 2 = file_write call,
        # iter 3 = empty text stream (model choke), _force_final_answer
        # gets an empty stream too.
        call_count = {"chat_with_tools": 0, "chat": 0}

        async def chat_with_tools(messages, tools, temperature=0.3, intent=None):
            call_count["chat_with_tools"] += 1
            if call_count["chat_with_tools"] <= 2:
                # First two calls: model picks a tool
                tool_name = "shell" if call_count["chat_with_tools"] == 1 else "file_write"
                return ToolCallResult(
                    tool_name=tool_name,
                    tool_args={"command": "mkdir test", "path": "test/hello.py", "content": "print('hi')"},
                    raw_content="Let me help with that",
                )
            # Third call: model produces empty text stream (the bug scenario)
            async def _empty_stream():
                return
                yield
            return _empty_stream()

        async def empty_chat(messages, temperature=0.4):
            # _force_final_answer also gets empty stream
            return
            yield

        mock_adapter = MagicMock()
        mock_adapter.chat_with_tools = chat_with_tools
        mock_adapter.chat = empty_chat

        # Mock tool dispatch so tools "succeed"
        from core.models import RiskLevel, ToolResult
        successful_result = ToolResult(
            content="OK", risk=RiskLevel.LOW, source="shell", success=True,
        )

        with patch("core.agent.loop.dispatch_with_retry") as mock_dispatch, \
             patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
             patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x):
            mock_dispatch.return_value = (successful_result, False, 0)

            chunks = []
            async for chunk in loop.run(
                messages=[{"role": "user", "content": "Create hello world repo"}],
                intent=Intent.SHELL,
                initial_tool_result=None,
                available_tools=[],
                adapter=mock_adapter,
            ):
                chunks.append(chunk)

        # MUST yield at least one chunk with non-empty text
        text_chunks = [c for c in chunks if c.text and c.text.strip()]
        assert len(text_chunks) >= 1, (
            "AgentLoop must yield meaningful text even when the model returns "
            "an empty stream after tool execution — this is the 'Tools execution "
            "failure' bug the user reported."
        )
        full_text = "".join(c.text for c in chunks)
        # Must NOT contain the old generic message
        assert "Please try rephrasing" not in full_text, (
            "Old generic 'rephrasing your request' message must NOT appear — "
            f"got: {full_text!r}"
        )
        # Should mention either: tools that ran, or model overload suggestion
        assert (
            "shell" in full_text.lower()
            or "file_write" in full_text.lower()
            or "model" in full_text.lower()
            or "switch" in full_text.lower()
        ), (
            f"Fallback should surface what tools ran OR suggest switching models; "
            f"got: {full_text!r}"
        )
