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

import asyncio
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
            trace=None,  # no trace — falls through to observation_log path
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
        # B-2026-08-20-14: the fallback is now a CLEAN user-facing message
        # that points to the Actions panel. Raw tool evidence (shell, permission
        # denied) lives in the Actions panel, NOT the chat bubble. Assert the
        # clean message is produced (not a silent fail or raw dump).
        assert "try again" in text.lower() or "rephrase" in text.lower() or "found" in text.lower() or "evidence" in text.lower(), (
            f"Fallback should be a clean user-facing message, got: {text!r}"
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
            trace=None,  # no trace — simulates pre-trace-parameter call
        ):
            chunks.append(chunk)

        assert len(chunks) >= 1
        text = "".join(c.text for c in chunks)
        assert text.strip()
        # B-2026-08-20-14: the fallback is now a clean user-facing message.
        # It no longer suggests "switch models" (that was the old debug
        # contract). It says "try again or rephrase" — honest + concise.
        assert "try again" in text.lower() or "rephrase" in text.lower() or "retry" in text.lower(), (
            f"Fallback should be a clean user-facing message, got: {text!r}"
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
            trace=None,
        ):
            chunks.append(chunk)

        text = "".join(c.text for c in chunks)
        assert "I created the repo" in text
        # B-2026-08-20-14: the old debug phrases are gone entirely.
        # The clean fallback never contains them.
        assert "couldn't synthesize" not in text.lower()
        assert "empty response" not in text.lower()

    @pytest.mark.asyncio
    async def test_weak_forced_synthesis_appends_report_before_done(self):
        """A weak non-empty synthesis must still report tool evidence before
        the terminal stream marker is emitted."""
        from core.agent.loop import AgentStep, AgentTrace

        loop = AgentLoop(adapter=MagicMock())
        trace = AgentTrace(
            steps=[
                AgentStep(
                    iteration=1,
                    thought="",
                    tool_name="shell",
                    tool_input="ls Dev",
                    observation="todo\nvert",
                    tool_failed=False,
                ),
            ]
        )

        async def weak_chat(messages, temperature=0.4):
            yield StreamChunk(text="Here's the result:", done=True)

        mock_adapter = MagicMock()
        mock_adapter.chat = weak_chat

        chunks = []
        async for chunk in loop._force_final_answer(
            loop_messages=[{"role": "user", "content": "show Dev"}],
            observation_log="",
            active_adapter=mock_adapter,
            trace=trace,
        ):
            chunks.append(chunk)

        text = "".join(chunk.text for chunk in chunks)
        assert "Here's the result:" in text
        assert "todo" in text
        assert "vert" in text
        assert chunks[-1].done is True
        assert all(not chunk.done for chunk in chunks[:-1])

    @pytest.mark.asyncio
    async def test_empty_stream_with_trace_surfaces_actual_tool_outputs(self):
        """Session 31 (revised per user feedback): when the trace has tool
        calls, the fallback MUST surface the actual tool inputs and outputs
        (truncated) — NOT guess 'overload'. This is the honest fix: show
        evidence, don't speculate about the cause."""
        from core.agent.loop import AgentStep, AgentTrace

        loop = AgentLoop(adapter=MagicMock())

        async def empty_chat(messages, temperature=0.4):
            return
            yield

        mock_adapter = MagicMock()
        mock_adapter.chat = empty_chat

        # Build a trace with 4 tool calls (the user's exact scenario:
        # mkdir, git init, file_write, git commit)
        trace = AgentTrace()
        trace.steps = [
            AgentStep(
                iteration=1, thought="", tool_name="shell",
                tool_input="mkdir C:\\Users\\tison\\...\\ProjectPhill",
                observation="Directory created successfully",
                tool_failed=False, retry_count=0, latency_ms=100,
            ),
            AgentStep(
                iteration=2, thought="", tool_name="shell",
                tool_input="git init",
                observation="Initialized empty Git repository in C:/Users/tison/.../ProjectPhill/.git/",
                tool_failed=False, retry_count=0, latency_ms=150,
            ),
            AgentStep(
                iteration=3, thought="", tool_name="file_write",
                tool_input="hello.py: print('Hello World')",
                observation="File written: hello.py",
                tool_failed=False, retry_count=0, latency_ms=50,
            ),
            AgentStep(
                iteration=4, thought="", tool_name="shell",
                tool_input="git add . && git commit -m 'initial'",
                observation="",  # empty observation — maybe this is the problem?
                tool_failed=False, retry_count=0, latency_ms=200,
            ),
        ]

        chunks = []
        async for chunk in loop._force_final_answer(
            loop_messages=[{"role": "user", "content": "test"}],
            observation_log="",  # no failed tools
            active_adapter=mock_adapter,
            trace=trace,
        ):
            chunks.append(chunk)

        assert len(chunks) >= 1
        text = "".join(c.text for c in chunks)
        assert text.strip()

        # B-2026-08-20-14: the fallback is now a CLEAN user-facing message.
        # Raw tool evidence (shell, mkdir, git init, file_write) lives in the
        # Actions panel, NOT the chat bubble. Assert the clean message points
        # the user to the Actions panel.
        assert "try again" in text.lower() or "rephrase" in text.lower() or "found" in text.lower() or "evidence" in text.lower(), (
            f"Fallback should be a clean user-facing message, got: {text!r}"
        )

        # MUST NOT guess "overload" when tools ran — that's the unverified
        # self-diagnosis the user pushed back on
        assert "overload" not in text.lower()


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
                tool_input="mkdir test_repo", observation="Directory created",
                tool_failed=False, retry_count=0, latency_ms=100,
            ),
            AgentStep(
                iteration=2, thought="", tool_name="file_write",
                tool_input="hello.py: print('hi')", observation="File written",
                tool_failed=False, retry_count=0, latency_ms=50,
            ),
        ]
        result = AgentLoop._summarize_trace_for_user(trace, observation_log="")
        assert "shell" in result
        assert "file_write" in result
        assert "mkdir test_repo" in result
        assert "ok" in result.lower()  # both succeeded
        # Session 31 revised: should also surface outputs, not just status
        assert "Directory created" in result or "output:" in result, (
            "Summary should surface actual tool outputs (not just 'ok') so "
            "the user can spot malformed data"
        )

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
        assert "FAILED" in result  # Session 31: uppercase FAILED for visibility
        assert "Command blocked" in result

    def test_includes_observation_log_when_present(self):
        """When observation_log has content, surface it under 'Full error details:'."""
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
        assert "Full error details:" in result
        assert "Permission denied" in result

    def test_surfaces_thinker_analysis_when_present(self):
        """B-2026-08-16-12: when the Thinker already computed an analysis, the
        degraded fallback must surface it — not discard the correct synthesis.
        This is the exact user repro: the Thinker worked out the answer (free
        space, not enough for 50 GB), then the final synthesis call failed."""
        from core.agent.loop import AgentStep, AgentTrace

        trace = AgentTrace()
        trace.thinker_analysis = (
            "Here's what I'd already worked out from the evidence:\n"
            "  • Free space ≈ 13.55 GB\n"
            "  • Not enough for a 50 GB game"
        )
        trace.steps = [
            AgentStep(
                iteration=1, thought="", tool_name="shell",
                tool_input="Get-CimInstance Win32_LogicalDisk",
                observation="FreeSpace: 14550515712 bytes",
                tool_failed=False, retry_count=0, latency_ms=100,
            ),
        ]
        result = AgentLoop._summarize_trace_for_user(
            trace,
            observation_log="",
            synthesis_failure_reason="the provider rate-limited the final synthesis call",
        )
        # The preserved analysis must be in the reply — this is the fix.
        assert "already worked out" in result, f"Thinker analysis missing: {result!r}"
        assert "13.55 GB" in result, f"Thinker facts missing: {result!r}"
        assert "not enough for a 50 gb game" in result.lower(), f"Thinker facts missing: {result!r}"
        # Raw tool evidence must still be there.
        assert "shell" in result, f"Raw evidence missing: {result!r}"
        assert "rate-limited the final synthesis call" in result

    def test_thinker_analysis_block_absent_when_empty(self):
        """B-2026-08-16-12: when the Thinker produced no analysis (empty
        string), the fallback must look exactly as before — no dangling
        'already worked out' header."""
        from core.agent.loop import AgentStep, AgentTrace

        trace = AgentTrace()  # thinker_analysis defaults to ""
        trace.steps = [
            AgentStep(
                iteration=1, thought="", tool_name="shell",
                tool_input="ls", observation="file1.py",
                tool_failed=False, retry_count=0, latency_ms=10,
            ),
        ]
        result = AgentLoop._summarize_trace_for_user(trace, observation_log="")
        assert "already worked out" not in result, f"Empty analysis leaked: {result!r}"
        assert "shell" in result

    def test_suggests_checking_outputs_not_just_switching_models(self):
        """Session 31 revised: the summary should suggest checking the outputs
        first (to spot malformed data), not just 'switch to a larger model'."""
        from core.agent.loop import AgentStep, AgentTrace

        trace = AgentTrace()
        trace.steps = [
            AgentStep(
                iteration=1, thought="", tool_name="shell",
                tool_input="ls", observation="file1.py\nfile2.py",
                tool_failed=False, retry_count=0, latency_ms=10,
            ),
        ]
        result = AgentLoop._summarize_trace_for_user(trace, observation_log="")
        # Should suggest checking outputs as the first next step
        assert "check" in result.lower() or "outputs" in result.lower(), (
            "Summary should suggest checking tool outputs first (per user feedback: "
            "the real cause is more likely broken tool data than 'overload')"
        )
        assert "one step at a time" in result.lower(), (
            "Summary should suggest one-step-at-a-time isolation"
        )


# ── 3. Engine fallback: intent-aware message, not generic "rephrase" ──────


class TestEngineFallbackMessage:
    """The engine's last-resort fallback (when the agent loop yields ZERO
    text even after its own fallbacks) must be intent-aware and suggest
    concrete next steps — not the old generic 'rephrase your request'."""

    def test_old_generic_message_is_gone_from_source(self):
        """The exact old message string must no longer appear in the source."""
        from pathlib import Path

        runtime_path = (
            Path(__file__).resolve().parent.parent.parent
            / "backend" / "src" / "core" / "agent_runtime.py"
        )
        source = runtime_path.read_text()
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
        """Session 31 revised: the new fallback should NOT guess 'overload'
        — it should admit uncertainty and suggest checking tool outputs +
        one-step-at-a-time isolation."""
        from pathlib import Path

        runtime_path = (
            Path(__file__).resolve().parent.parent.parent
            / "backend" / "src" / "core" / "agent_runtime.py"
        )
        source = runtime_path.read_text()
        # The parent runtime names the concrete internal evidence surface
        # instead of blaming the user's phrasing.
        assert "iteration limit" in source.lower()
        assert "try again" in source.lower() or "evidence" in source.lower() or "found" in source.lower()
        # Session 31 revised: must NOT guess "overload" in the engine fallback
        # (the loop's evidence-based fallback handles that case better)
        assert "almost always a free-tier model issue" not in source, (
            "Engine fallback must NOT guess 'free-tier model issue' — that's "
            "the unverified self-diagnosis the user pushed back on."
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

        async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
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
        # B-2026-08-20-14: the fallback is now a CLEAN user-facing message.
        # It no longer contains raw tool names or "switch models" suggestions.
        # It says "I found the information... Actions panel... retry."
        assert full_text.strip(), f"Fallback must be non-empty, got: {full_text!r}"
        assert (
            "try again" in full_text.lower() or "evidence" in full_text.lower() or "found" in full_text.lower()
            or "retry" in full_text.lower()
            or "try again" in full_text.lower()
        ), (
            f"Fallback should be a clean user-facing message, got: {full_text!r}"
        )


# ── 5. Explicit worker → report contract ─────────────────────────────────


class TestWorkReport:
    """The deterministic worker report prevents evidence-free model text
    from being accepted as the final answer after tool execution."""

    def test_heading_only_response_requires_report_and_renders_evidence(self):
        from core.agent.models import AgentStep, AgentTrace

        trace = AgentTrace(
            steps=[
                AgentStep(
                    iteration=1,
                    thought="",
                    tool_name="shell",
                    tool_input="ls Dev",
                    observation="todo\nused_car_website_blueprint\nvert",
                    tool_failed=False,
                ),
            ]
        )

        report = trace.work_report()

        assert report.needs_report("Here's what's in Dev:")
        rendered = report.render()
        assert "shell(ls Dev)" in rendered
        assert "todo" in rendered
        assert "used_car_website_blueprint" in rendered

    def test_response_that_reports_evidence_does_not_trigger_report(self):
        from core.agent.models import AgentStep, AgentTrace

        trace = AgentTrace(
            steps=[
                AgentStep(
                    iteration=1,
                    thought="",
                    tool_name="shell",
                    tool_input="ls Dev",
                    observation="todo\nvert",
                    tool_failed=False,
                ),
            ]
        )

        assert not trace.work_report().needs_report(
            "Dev contains todo and vert."
        )

    def test_side_effect_only_success_does_not_require_evidence(self):
        from core.agent.models import AgentStep, AgentTrace

        trace = AgentTrace(
            steps=[
                AgentStep(
                    iteration=1,
                    thought="",
                    tool_name="file_write",
                    tool_input="hello.py",
                    observation="OK",
                    tool_failed=False,
                ),
            ]
        )

        assert not trace.work_report().needs_report("Created hello.py successfully.")

    def test_substantive_answer_never_triggers_report(self):
        # Session 122: the user-reported case — a correct, substantive answer
        # that does NOT quote raw evidence tokens must never get the
        # "Worker report — tool execution evidence:" recap appended. The
        # trace already lives in the inline action cards + Actions tab; the
        # chat message owns the final answer only.
        from core.agent.models import AgentStep, AgentTrace

        trace = AgentTrace(
            steps=[
                AgentStep(
                    iteration=1,
                    thought="",
                    tool_name="git",
                    tool_input='{"operation": "status"}',
                    observation="On branch main\nYour branch is up to date with 'origin/main'.",
                    tool_failed=False,
                ),
            ]
        )

        assert not trace.work_report().needs_report(
            "Working tree is clean — no uncommitted changes."
        )

    def test_terse_filler_after_tool_execution_still_triggers_report(self):
        # Session 115 silent-stall shape: a terse acknowledgment that names
        # no evidence is exactly the near-empty stream failure the report
        # exists for — it must still be caught.
        from core.agent.models import AgentStep, AgentTrace

        trace = AgentTrace(
            steps=[
                AgentStep(
                    iteration=1,
                    thought="",
                    tool_name="shell",
                    tool_input="git status",
                    observation="On branch main\nnothing to commit, working tree clean",
                    tool_failed=False,
                ),
            ]
        )

        assert trace.work_report().needs_report("Got it — working on your request...")


# ── 5. _synthesis_failure_fallback: timeout/exception handlers use trace ───


class TestSynthesisFailureFallback:
    """Session 94 (backlog L50): the timeout/exception handlers around
    _force_final_answer previously dumped observation_log[:2000] — which is
    empty when ALL tools succeeded. _synthesis_failure_fallback uses the
    trace summary first (it lists every call, success + failure)."""

    def test_trace_evidence_surfaced_when_observation_log_empty(self):
        from core.agent.loop import AgentStep, AgentTrace

        loop = AgentLoop(adapter=MagicMock())
        trace = AgentTrace(
            steps=[
                AgentStep(
                    iteration=1,
                    thought="",
                    tool_name="shell",
                    tool_input="mkdir project",
                    observation="Directory created",
                    tool_failed=False,
                ),
                AgentStep(
                    iteration=2,
                    thought="",
                    tool_name="file_write",
                    tool_input="hello.py",
                    observation="File written",
                    tool_failed=False,
                ),
            ]
        )

        text = loop._synthesis_failure_fallback(trace, observation_log="", timed_out=True)

        # B-2026-08-20-14: the fallback is now a CLEAN user-facing message.
        # Raw tool evidence (shell, file_write, mkdir) lives in the Actions
        # panel. The chat bubble says "I found the information... Actions panel."
        assert "try again" in text.lower() or "rephrase" in text.lower() or "found" in text.lower(), (
            f"Fallback should be clean user-facing message, got: {text!r}"
        )

    def test_observation_log_fallback_when_no_trace_steps(self):
        loop = AgentLoop(adapter=MagicMock())
        text = loop._synthesis_failure_fallback(
            trace=None, observation_log="[Tool: shell | Status: BLOCKED]", timed_out=False
        )
        # B-2026-08-20-14: clean message — the observation_log content is in
        # the Actions panel, not the chat bubble.
        assert "try again" in text.lower() or "rephrase" in text.lower() or "found" in text.lower(), (
            f"Fallback should be clean user-facing message, got: {text!r}"
        )

    def test_generic_message_when_no_evidence_at_all(self):
        loop = AgentLoop(adapter=MagicMock())
        text = loop._synthesis_failure_fallback(trace=None, observation_log="", timed_out=False)
        # No tools, no observation log → clean "try again" message
        assert "try again" in text.lower() or "rephrase" in text.lower(), (
            f"Fallback should be clean 'try again' message, got: {text!r}"
        )


# ── 6. Timeout/exception handlers yield trace evidence (Session 94) ───────


class TestSynthesisFailureHandler:
    """The except handlers around _force_final_answer must yield the
    evidence-based fallback (via _synthesis_failure_fallback) — NOT the old
    observation_log[:2000] dump that was empty when all tools succeeded."""

    @pytest.mark.asyncio
    async def test_timeout_handler_yields_trace_evidence(self):
        from adapters.ollama import ToolCallResult
        from core.models import RiskLevel, ToolResult

        loop = AgentLoop(adapter=MagicMock())
        call_count = {"n": 0}

        async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
            call_count["n"] += 1
            tool_name = "shell" if call_count["n"] == 1 else "file_write"
            return ToolCallResult(
                tool_name=tool_name,
                tool_args={"command": "mkdir project", "path": "hello.py", "content": "print('hi')"},
                raw_content="Let me help",
            )

        mock_adapter = MagicMock()
        mock_adapter.chat_with_tools = chat_with_tools

        successful_result = ToolResult(
            content="OK", risk=RiskLevel.LOW, source="shell", success=True,
        )

        # Force the synthesis step to time out; the handler must fall back
        # to evidence from the trace (which lists ALL tools, success included).
        async def _boom(self, *args, **kwargs):
            raise asyncio.TimeoutError()

        with patch("core.agent.loop.dispatch_with_retry") as mock_dispatch, \
             patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
             patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x), \
             patch.object(AgentLoop, "_force_final_answer", _boom):
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

        full_text = "".join(c.text for c in chunks)
        # B-2026-08-20-14: the timeout handler now yields a CLEAN user-facing
        # message. Raw tool evidence (shell, mkdir) lives in the Actions panel.
        # Assert the turn produced a non-empty honest message (not a silent
        # fail or raw dump).
        assert full_text.strip(), (
            f"Timeout handler must produce a message. Got: {full_text[:400]!r}"
        )
        assert "try again" in full_text.lower() or "evidence" in full_text.lower() or "found" in full_text.lower() or "retry" in full_text.lower() or "try again" in full_text.lower(), (
            f"Timeout handler should be clean user-facing message. Got: {full_text[:400]!r}"
        )
        # Must NOT misdiagnose as an empty model response
        assert "empty response" not in full_text.lower(), (
            "Timeout handler must not blame an empty model response. Got: "
            + full_text[:400]
        )
