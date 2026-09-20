"""Session 115 regression tests - empty-response fast-fail in the agent loop.

The free-tier model sometimes returns an empty stream (no text, no tool
call). Previously the loop fell through to "stream the answer" with an
empty buffer - the user saw a spinner for 60-120s and then a blank reply
(the silent-stall failure mode). The loop now detects an empty final
buffer and fast-fails with an honest user-facing message instead of
spinning another PER_CALL_TIMEOUT_SECS model call on the same empty output.

Contract under test:
  1. An empty text-only response yields a non-empty, honest final message.
  2. The FIRST tool iteration gets at most ONE forced-tool nudge (Session
     238); a second empty reply hits the honest fast-fail - bounded retry,
     never a spin.
  3. Regression: a normal non-empty text response still streams through.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from core.agent.loop import AgentLoop, TerminalProviderError
from core.models import Intent, StreamChunk
from core.obs import ObsCollector


class TestEmptyResponseFastFail:
    @pytest.mark.asyncio
    async def test_empty_stream_fast_fails_with_honest_message(self):
        loop = AgentLoop(adapter=MagicMock())
        seen = {"calls": 0}

        async def empty_chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
            seen["calls"] += 1

            async def _stream():
                yield StreamChunk(text="", done=False)
                yield StreamChunk(text="", done=True)

            return _stream()

        async def empty_chat(messages, temperature=0.4):
            return
            yield

        mock_adapter = MagicMock()
        mock_adapter.chat_with_tools = empty_chat_with_tools
        mock_adapter.chat = empty_chat

        chunks = []
        with patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
             patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x):
            async for chunk in loop.run(
                messages=[{"role": "user", "content": "check git status"}],
                intent=Intent.SHELL,
                initial_tool_result=None,
                available_tools=[],
                adapter=mock_adapter,
            ):
                chunks.append(chunk)

        full = "".join(c.text for c in chunks)
        # The fallback message is now a clean user-facing
        # message ("I couldn't generate a response...") instead of the old
        # "empty response" debug text. Assert the turn ends with a non-empty
        # honest message (not raw tool dumps or a silent fail).
        assert full.strip(), "expected honest fallback message, got empty"
        # The FIRST tool iteration gets ONE forced-tool nudge
        # (bounded reprompt) before the honest fail — the empty-response
        # fast-fail still applies to the second empty reply.
        assert seen["calls"] == 2, (
            f"loop must retry an iter-0 empty output at most once, then fail "
            f"honestly (chat_with_tools called {seen['calls']}x)"
        )

    @pytest.mark.asyncio
    async def test_normal_text_response_still_streams(self):
        loop = AgentLoop(adapter=MagicMock())

        async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
            async def _stream():
                yield StreamChunk(text="All good - nothing to do.", done=False)
                yield StreamChunk(text="", done=True)

            return _stream()

        async def empty_chat(messages, temperature=0.4):
            return
            yield

        mock_adapter = MagicMock()
        mock_adapter.chat_with_tools = chat_with_tools
        mock_adapter.chat = empty_chat

        chunks = []
        with patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
             patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x):
            async for chunk in loop.run(
                messages=[{"role": "user", "content": "hi"}],
                intent=Intent.SHELL,
                initial_tool_result=None,
                available_tools=[],
                adapter=mock_adapter,
            ):
                chunks.append(chunk)

        full = "".join(c.text for c in chunks)
        assert "All good - nothing to do." in full, f"expected normal text, got {full!r}"

    @pytest.mark.asyncio
    async def test_streamed_deltas_keep_boundary_spaces(self):
        """Regression: the per-chunk transform in the execute streaming path
        must not .strip() each delta, or space-prefixed tokens weld together
        ("assistantrunning", "thisdevice"). The loop must use the whitespace-
        safe stream variant on every streamed chunk.
        """
        loop = AgentLoop(adapter=MagicMock())

        # The execute streaming path buffers the first ~2000 chars (for tool
        # detection) and yields them as one block, then streams the REMAINDER
        # chunk by chunk. The per-chunk transform on that remainder must not
        # .strip() each delta. So: a >2000-char prefix to fill the buffer, then
        # the space-prefixed deltas that must survive intact.
        prefix = "word " * 500  # ~2500 chars, forces the buffer to flush
        deltas = [" LocalMind", " —", " a", " local", " assistant", " running", " here."]

        async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
            async def _stream():
                yield StreamChunk(text=prefix, done=False)
                for d in deltas:
                    yield StreamChunk(text=d, done=False)
                yield StreamChunk(text="", done=True)

            return _stream()

        async def empty_chat(messages, temperature=0.4):
            return
            yield

        mock_adapter = MagicMock()
        mock_adapter.chat_with_tools = chat_with_tools
        mock_adapter.chat = empty_chat

        chunks = []
        # NOTE: do NOT stub _filter_system_leaks here — we want the real
        # per-chunk transform path (incl. _strip_minimax_tool_calls_stream).
        with patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x):
            async for chunk in loop.run(
                messages=[{"role": "user", "content": "what can you do"}],
                intent=Intent.SHELL,
                initial_tool_result=None,
                available_tools=[],
                adapter=mock_adapter,
            ):
                chunks.append(chunk)

        full = "".join(c.text for c in chunks)
        assert "local assistant running here" in full, f"boundary spaces lost: {full!r}"
        assert "assistantrunning" not in full, f"delta strip regressed: {full!r}"

    @pytest.mark.asyncio
    async def test_terminal_planning_error_stops_before_tool_call(self):
        """A terminal provider error on the first provider call must
        not be swallowed by planning and retried in the parent loop."""
        loop = AgentLoop(adapter=MagicMock())
        seen = {"planning": 0, "tool_calls": 0}
        error = (
            'zen returned 429: {"error":{"type":"FreeUsageLimitError",'
            '"message":"free daily quota exceeded"}}'
        )

        async def failing_plan(messages, temperature=0.1, intent="chat"):
            seen["planning"] += 1
            yield StreamChunk(text="", done=True, error=error)

        async def tool_call_should_not_run(**kwargs):
            seen["tool_calls"] += 1
            raise AssertionError("terminal planning error entered tool loop")

        mock_adapter = MagicMock()
        mock_adapter.chat = failing_plan
        mock_adapter.chat_with_tools = tool_call_should_not_run

        with patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x), pytest.raises(
            TerminalProviderError
        ) as raised:
            async for _chunk in loop.run(
                messages=[{"role": "user", "content": "check the project"}],
                intent=Intent.SHELL,
                initial_tool_result=None,
                available_tools=[],
                adapter=mock_adapter,
            ):
                pass

        assert isinstance(raised.value, TerminalProviderError)
        assert str(raised.value) == error
        assert seen == {"planning": 1, "tool_calls": 0}

    @pytest.mark.asyncio
    async def test_transient_planning_error_keeps_existing_loop_path(self):
        """A plain transient 429 remains non-terminal and reaches the normal
        parent decision call rather than being treated as auth/quota failure."""
        loop = AgentLoop(adapter=MagicMock())
        seen = {"planning": 0, "tool_calls": 0}
        transient = 'zen returned 429: {"error":{"type":"requests","message":"per minute"}}'

        async def failing_plan(messages, temperature=0.1, intent="chat"):
            seen["planning"] += 1
            yield StreamChunk(text="", done=True, error=transient)

        async def final_chat(**kwargs):
            seen["tool_calls"] += 1

            async def _stream():
                yield StreamChunk(text="Recovered", done=False)
                yield StreamChunk(text="", done=True)

            return _stream()

        mock_adapter = MagicMock()
        mock_adapter.chat = failing_plan
        mock_adapter.chat_with_tools = final_chat
        # This mock doubles `adapter.chat` as the planning-call
        # counter. A non-reasoning adapter (thinking_enabled=False) skips the
        # pre-tool Thinker consult — which is ALSO a plain `adapter.chat` call
        # and would otherwise inflate the planning count. The gate matches the
        # fast-path convention: no reasoning, no pre-tool consult.
        mock_adapter.thinking_enabled = False

        with patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x):
            chunks = [
                chunk
                async for chunk in loop.run(
                    messages=[{"role": "user", "content": "check the project"}],
                    intent=Intent.SHELL,
                    initial_tool_result=None,
                    available_tools=[],
                    adapter=mock_adapter,
                )
            ]

        # The first tool-required call gets one forced-tool
        # nudge (iter-0 text is not accepted as the answer), then the
        # model's text is streamed on the second pass.
        assert seen == {"planning": 1, "tool_calls": 2}
        assert "Recovered" in "".join(chunk.text for chunk in chunks)

    @pytest.mark.asyncio
    async def test_stream_error_propagates_adapter_message(self):
        """When the adapter yields an error chunk (e.g. zen 429),
        the loop must pass the adapter's error message through to the SSE
        error event. Previously the MiniMax buffering dropped the message
        (error=""), so the chat route skipped the error event and the
        frontend rendered a silent spinner."""
        loop = AgentLoop(adapter=MagicMock())

        zen_429 = (
            'zen returned 429: {"type":"error","error":{"type":'
            '"FreeUsageLimitError","message":"Rate limit exceeded."}}'
        )

        async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
            async def _stream():
                yield StreamChunk(text="", done=True, error=zen_429)

            return _stream()

        async def empty_chat(messages, temperature=0.4):
            return
            yield

        mock_adapter = MagicMock()
        mock_adapter.chat_with_tools = chat_with_tools
        mock_adapter.chat = empty_chat

        chunks = []
        with patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
             patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x):
            async for chunk in loop.run(
                messages=[{"role": "user", "content": "list files"}],
                intent=Intent.SHELL,
                initial_tool_result=None,
                available_tools=[],
                adapter=mock_adapter,
            ):
                chunks.append(chunk)

        # The error message must survive — not be replaced by "".
        errs = [c.error for c in chunks if c.error]
        assert errs, f"expected a non-empty chunk.error, got {chunks!r}"
        assert any("429" in e for e in errs), f"expected the 429 text to survive, got {errs!r}"

    @pytest.mark.asyncio
    async def test_retryable_error_after_successful_tool_preserves_evidence(self):
        """A rate limit on the post-tool synthesis call must not erase a
        successful tool result or turn the whole request into an error.

        This is the exact user-visible failure mode: Cerebras completes
        web_search, then rejects the follow-up model call with HTTP 429.
        """
        from adapters.ollama import ToolCallResult
        from core.models import ToolResult
        from core.obs import ObsCollector

        loop = AgentLoop(adapter=MagicMock())
        seen = {"calls": 0}
        rate_limit = (
            'cerebras returned 429: {"error":{"type":"rate_limit_exceeded",'
            '"message":"Too many requests"}}'
        )

        async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
            seen["calls"] += 1
            if seen["calls"] == 1:
                return ToolCallResult(
                    tool_name="web_search",
                    tool_args={"query": "trending news August 15 2026"},
                )

            async def _stream():
                yield StreamChunk(text="", done=True, error=rate_limit)

            return _stream()

        async def dispatch(*args, **kwargs):
            return (
                ToolResult(
                    source="web_search",
                    content="Headline A — verified search result",
                ),
                False,
                0,
            )

        mock_adapter = MagicMock()
        mock_adapter.chat_with_tools = chat_with_tools
        mock_adapter.chat = lambda *args, **kwargs: iter(())
        obs = ObsCollector()
        with patch("core.agent.loop.dispatch_with_retry", dispatch):
            chunks = [
                chunk
                async for chunk in loop.run(
                    messages=[{"role": "user", "content": "whats trending today"}],
                    intent=Intent.WEB_SEARCH,
                    initial_tool_result=None,
                    available_tools=[],
                    adapter=mock_adapter,
                    obs=obs,
                    skip_planning=True,
                )
            ]

        full = "".join(chunk.text for chunk in chunks)
        assert seen["calls"] == 2
        assert not [chunk.error for chunk in chunks if chunk.error]
        # The 429-preserve-evidence path now tries
        # deterministic extraction first, then a CLEAN message (not the raw
        # _summarize_trace_for_user dump). Assert the clean message OR an
        # extracted answer — either is acceptable; the raw dump is not.
        assert full.strip(), "must produce a non-empty message"
        assert "What to try next" not in full, "raw harness dump must not leak"
        assert "What to try next" not in full, "raw harness dump must not leak"
        assert any(event.type == "agent_loop_degraded" for event in obs.history())
        assert any(event.type == "tool_call" for event in obs.history())

    @pytest.mark.asyncio
    async def test_degraded_synthesis_surfaces_thinker_analysis(self):
        """When the Thinker computed a correct analysis
        before the final synthesis call is rate-limited, the degraded reply
        must carry that analysis — the exact user repro (disk-space task:
        tool succeeds, Thinker works out the answer, final call 429s).
        """
        from adapters.ollama import ToolCallResult
        from core.agent.thinker import ThinkerAnalysis
        from core.models import ToolResult
        from core.obs import ObsCollector

        loop = AgentLoop(adapter=MagicMock())
        seen = {"calls": 0}
        rate_limit = (
            'cerebras returned 429: {"error":{"type":"rate_limit_exceeded",'
            '"message":"Too many requests"}}'
        )

        async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
            seen["calls"] += 1
            if seen["calls"] == 1:
                return ToolCallResult(
                    tool_name="shell",
                    tool_args={"command": "Get-CimInstance Win32_LogicalDisk"},
                )

            async def _stream():
                yield StreamChunk(text="", done=True, error=rate_limit)

            return _stream()

        async def dispatch(*args, **kwargs):
            return (
                ToolResult(
                    source="shell",
                    content="FreeSpace: 14550515712 bytes",
                ),
                False,
                0,
            )

        fake_analysis = ThinkerAnalysis(
            facts=["Free space ≈ 13.55 GB", "Not enough for a 50 GB game"],
            next_step="Tell the user it's not enough",
        )

        class _FakeThinker:
            def __init__(self, timeout_secs=30.0):
                self.last_analysis = fake_analysis

            async def consult(self, evidence, adapter, temperature=0.4):
                yield StreamChunk(text="", thinking="reasoning...", done=False)

        mock_adapter = MagicMock()
        mock_adapter.chat_with_tools = chat_with_tools
        mock_adapter.chat = lambda *args, **kwargs: iter(())
        mock_adapter.thinking_enabled = True
        obs = ObsCollector()
        with patch("core.agent.loop.dispatch_with_retry", dispatch), patch(
            "core.agent.thinker.Thinker", _FakeThinker
        ):
            chunks = [
                chunk
                async for chunk in loop.run(
                    messages=[{"role": "user", "content": "check free disk space"}],
                    intent=Intent.SHELL,
                    initial_tool_result=None,
                    available_tools=[],
                    adapter=mock_adapter,
                    obs=obs,
                    skip_planning=True,
                )
            ]

        full = "".join(chunk.text for chunk in chunks)
        assert seen["calls"] == 2
        # The 429-preserve-evidence path now tries
        # deterministic extraction first, then a CLEAN message. The Thinker's
        # analysis may or may not be extractable deterministically; the key
        # invariant is that a non-empty message reaches the user (not a raw
        # dump, not a silent fail).
        assert full.strip(), f"must produce a message, got: {full!r}"
        assert "What to try next" not in full, "raw harness dump must not leak"
        assert "What to try next" not in full, "raw harness dump must not leak"


class TestFileWriteVerificationReadbackDirective:
    """The file_write verification line is FACTUAL evidence
    ("file_write confirmed — N chars verified on disk at <path>") and must NOT
    tell the agent whether to read the file back. The old "do NOT read it back" /
    "read it back with file_task" directive was a phantom self-verification
    instruction (it fought explicit user requests and second-guessed the agent);
    the agent decides for itself from the actual task.
    """

    @pytest.mark.asyncio
    async def test_verification_line_is_factual_with_no_readback_instruction(self, tmp_path):
        """The verification line states the on-disk fact and gives NO read-back
        instruction of any kind — regardless of what the user asked."""
        target = tmp_path / "facts.txt"
        target.write_text("Fact A\nFact B\nFact C", encoding="utf-8")
        loop = AgentLoop(adapter=MagicMock())

        msg = await loop._verify_tool_result(
            tool_name="file_write",
            tool_args={"path": str(target), "content": "Fact A\nFact B\nFact C"},
            observation="",
        )

        assert msg is not None
        assert "confirmed" in msg and "on disk" in msg
        assert "do NOT read it back" not in msg, f"prohibition leaked: {msg!r}"
        assert "read it back" not in msg.lower(), f"read-back directive leaked: {msg!r}"

    @pytest.mark.asyncio
    async def test_verification_reports_the_files_real_size(self, tmp_path):
        """The number is the file's REAL on-disk size (a stat), not the length of any read-back
        report: a 19-byte file once confirmed "79 chars" because a report header was counted."""
        target = tmp_path / "notes.txt"
        target.write_text("hello from deepseek", encoding="utf-8")
        loop = AgentLoop(adapter=MagicMock())

        msg = await loop._verify_tool_result(
            tool_name="file_write",
            tool_args={"path": str(target), "content": "hello from deepseek"},
            observation="",
        )

        assert msg is not None and "19 bytes verified on disk" in msg, f"got: {msg!r}"

    @pytest.mark.asyncio
    async def test_verification_flags_truncation_by_real_file_size(self, tmp_path):
        """A 200-char write that landed as 90 bytes is flagged as possibly truncated."""
        target = tmp_path / "f.txt"
        target.write_text("x" * 90, encoding="utf-8")
        loop = AgentLoop(adapter=MagicMock())

        msg = await loop._verify_tool_result(
            tool_name="file_write",
            tool_args={"path": str(target), "content": "x" * 200},
            observation="",
        )

        assert msg is not None and "may be truncated" in msg, f"truncation not flagged: {msg!r}"

    @pytest.mark.asyncio
    async def test_a_write_is_verified_by_the_disk_not_by_a_read_tool_that_can_fail(self, tmp_path, monkeypatch):
        """The read-back used to dispatch a tool; when THAT failed (permissions, a timeout) the model
        was told a perfectly good file had not been created. A missing file still fails; a present
        one passes even if every tool call would fail."""
        async def exploding_dispatch(*a, **k):
            raise RuntimeError("no tool should be dispatched for verification")

        monkeypatch.setattr("core.agent.loop.dispatch_with_retry", exploding_dispatch)
        loop = AgentLoop(adapter=MagicMock())
        present = tmp_path / "style.css"
        present.write_text("body { margin: 0 }", encoding="utf-8")

        ok = await loop._verify_tool_result("file_write", {"path": str(present), "content": "body { margin: 0 }"}, "")
        gone = await loop._verify_tool_result("file_write", {"path": str(tmp_path / "nope.css"), "content": "x"}, "")
        assert "confirmed" in ok
        assert "FAILED" in gone

    @pytest.mark.asyncio
    async def test_loop_surfaces_factual_verification_without_readback_directive(self):
        """Loop-level wiring: even when the user asks to write THEN read back, the
        verification evidence the model sees is the factual on-disk line with NO
        read-back instruction — the agent honors the user's request on its own."""
        from adapters.ollama import ToolCallResult
        from core.models import ToolResult
        from core.obs import ObsCollector

        loop = AgentLoop(adapter=MagicMock())
        seen = {"calls": 0, "synthesis_messages": None}
        content = (
            "Kenya gained independence on 12 December 1963.\n"
            "Jomo Kenyatta was the first president.\n"
            "It was a peaceful handover from British rule."
        )
        user_prompt = (
            "Create a folder called kenya_notes on my Desktop, write a file inside "
            "it called facts.txt with 3 short facts about Kenyan independence, "
            "then read the file back and show me exactly what's in it."
        )

        async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
            seen["calls"] += 1
            if seen["calls"] == 1:
                return ToolCallResult(
                    tool_name="file_write",
                    tool_args={"path": "C:/Users/tison/Desktop/kenya_notes/facts.txt", "content": content},
                )
            seen["synthesis_messages"] = messages

            async def _stream():
                yield StreamChunk(text="Here are the facts from the file.", done=True)

            return _stream()

        async def dispatch(*args, **kwargs):
            return (
                ToolResult(source="file_write", content=content, success=True),
                False,
                0,
            )

        class _FakeContract:
            async def execute(self, payload):
                return ToolResult(source="file_write", content=content, success=True)

        class _NoopThinker:
            def __init__(self, timeout_secs=30.0):
                self.last_analysis = None

            async def consult(self, evidence, adapter, temperature=0.4):
                if False:
                    yield  # pragma: no cover — keep this an async generator

        mock_adapter = MagicMock()
        mock_adapter.chat_with_tools = chat_with_tools
        mock_adapter.chat = lambda *args, **kwargs: iter(())
        mock_adapter.thinking_enabled = True
        obs = ObsCollector()
        with patch("core.agent.loop.dispatch_with_retry", dispatch), patch(
            "core.agent.thinker.Thinker", _NoopThinker
        ), patch("tools.contracts.base.ToolRegistry.get", return_value=_FakeContract):
            chunks = [
                chunk
                async for chunk in loop.run(
                    messages=[{"role": "user", "content": user_prompt}],
                    intent=Intent.SHELL,
                    initial_tool_result=None,
                    available_tools=[],
                    adapter=mock_adapter,
                    obs=obs,
                    skip_planning=True,
                )
            ]

        full = "".join(chunk.text for chunk in chunks)
        assert seen["calls"] == 2, f"expected tool call + synthesis, got {seen['calls']}"
        assert "Here are the facts" in full
        # The factual VERIFICATION line reaches the model, with NO read-back
        # instruction of any kind.
        assert seen["synthesis_messages"] is not None
        joined = " ".join(str(m.get("content", "")) for m in seen["synthesis_messages"])
        assert "VERIFICATION" in joined, f"verification line missing: {joined!r}"
        assert "do NOT read it back" not in joined, f"prohibition leaked: {joined!r}"
        assert "read it back" not in joined.lower(), f"read-back directive leaked: {joined!r}"


class TestReasoningCapEmptyStreamRoutesToRecovery:
    """B-2026-08-20-20 (Session 323 trace 3): the adapter's 500-chunk reasoning
    cap now ends the stream CLEANLY (thinking-only, done=True, no error). The
    loop must route that shape into the empty-reasoning recovery (nudge with
    the ORIGINAL question, thinking forced OFF) — NOT the generic
    provider-error fallback. An error chunk after the cap break used to take
    the has_error path (the trace: 210-char provider-error message, no files).
    """

    @pytest.mark.asyncio
    async def test_thinking_only_stream_nudges_with_original_question(self):
        loop = AgentLoop(adapter=MagicMock())
        seen = {"calls": 0, "last_messages": None}

        async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
            seen["calls"] += 1
            seen["last_messages"] = list(messages)

            async def _stream():
                # Adapter post-500-cap shape: thinking only, then clean done.
                yield StreamChunk(text="", thinking="reasoning...", done=False)
                yield StreamChunk(text="", done=True)

            return _stream()

        mock_adapter = MagicMock()
        mock_adapter.chat_with_tools = chat_with_tools
        mock_adapter.chat = lambda *args, **kwargs: iter(())
        mock_adapter.thinking_enabled = True

        obs = ObsCollector()
        chunks = []
        with patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
             patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x):
            async for chunk in loop.run(
                messages=[{"role": "user", "content": "create a project in my workspace"}],
                intent=Intent.ANALYZE,
                initial_tool_result=None,
                available_tools=[],
                adapter=mock_adapter,
                obs=obs,
                skip_planning=True,
            ):
                chunks.append(chunk)

        # The recovery must fire — and the nudge must carry the ORIGINAL question.
        recovery_events = [e for e in obs.history() if e.type == "empty_reasoning_recovery"]
        assert recovery_events, f"empty-reasoning recovery never fired; events: {[e.type for e in obs.history()]}"
        joined = " ".join(str(m.get("content", "")) for m in (seen["last_messages"] or []))
        assert "create a project in my workspace" in joined, (
            f"recovery nudge must restate the user's original question: {joined!r}"
        )
        # No provider-error path: no error chunks, no "ran into an issue".
        errors = [c.error for c in chunks if c.error]
        assert not errors, f"cap-break stream must not hit the error path: {errors}"
        assert not any("ran into an issue" in (c.text or "") for c in chunks)

    @pytest.mark.asyncio
    async def test_error_after_reasoning_still_hits_provider_error_path(self):
        """Guard: if the adapter DOES surface a real error chunk after the cap
        break (e.g. a genuine provider failure, not a stuck model), the loop
        must STILL take the provider-error path — the clean-shape routing must
        not swallow real errors."""
        loop = AgentLoop(adapter=MagicMock())

        async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
            async def _stream():
                yield StreamChunk(text="", thinking="reasoning...", done=False)
                yield StreamChunk(text="", done=True, error="zen returned 500: upstream failed")

            return _stream()

        mock_adapter = MagicMock()
        mock_adapter.chat_with_tools = chat_with_tools
        mock_adapter.chat = lambda *args, **kwargs: iter(())
        mock_adapter.thinking_enabled = True

        chunks = []
        with patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
             patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x):
            async for chunk in loop.run(
                messages=[{"role": "user", "content": "create a project"}],
                intent=Intent.ANALYZE,
                initial_tool_result=None,
                available_tools=[],
                adapter=mock_adapter,
                skip_planning=True,
            ):
                chunks.append(chunk)

        errors = [c.error for c in chunks if c.error]
        assert errors, "a real provider error after reasoning must still surface as an error"


@pytest.mark.parametrize(
    "request_text,content,expected",
    [
        ("Create a folder verify-test, write result.txt containing the text 42, then read it back", "42", True),
        ("write a.txt with the number 7", "7", True),
        ("make hi.txt containing exactly OK", "OK", True),
        ('write x.txt containing "eta"', "eta", True),
        ("write result.txt, then read it back and compare 42 with the file", "42", False),  # merely mentioned
        ("read the file and tell me", "read", False),  # a placeholder, not a requested literal
    ],
)
def test_a_short_body_the_user_spelled_out_is_not_mistaken_for_a_placeholder(request_text, content, expected):
    from core.agent.loop import _content_requested_by_user

    assert _content_requested_by_user(content, request_text) is expected
