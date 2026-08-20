"""Session 323 regression tests — task-anchored recovery nudges.

The user's real trace (deepseek-v4-flash, "create a new coding project in
dev/{name}/"): the model planned well but narrated tool intent instead of
emitting tool calls; the tool-talk detector intercepted the narration and
injected a TASK-BLIND nudge ("Call the tool now using the function-calling
format"). The model read that as "prove you can call a tool" and re-ran
reconnaissance (ls / Get-ChildItem) — two turns, eight tool steps, zero
files created.

Session 314 anchored the empty-reasoning nudge with the user's original
question; this session gives the tool-talk, forced-tool, and empty-response
nudges the same anchor PLUS an advancement hint when tools already ran this
turn, so a nudge can never bounce the model back into tools it already used.

Contract under test:
  - the forced-tool nudge includes the user's original request
  - the tool-talk nudge includes the original request AND the names of tools
    already run this turn, telling the model not to repeat them
  - the empty-response nudge includes the original request
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from adapters.ollama import ToolCallResult
from core.agent.loop import AgentLoop
from core.models import Intent, RiskLevel, StreamChunk, ToolResult


async def _run(loop, adapter, message="create a project in dev/myapp"):
    chunks = []
    with patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
         patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x), \
         patch("core.agent.loop.dispatch_with_retry", side_effect=_fake_dispatch):
        async for chunk in loop.run(
            messages=[{"role": "user", "content": message}],
            intent=Intent.SHELL,
            initial_tool_result=None,
            available_tools=[],
            adapter=adapter,
        ):
            chunks.append(chunk)
    return chunks


def _fake_dispatch(intent, raw_input, **kwargs):
    return (
        ToolResult(
            content="file1.txt\nfile2.txt",
            risk=RiskLevel.LOW,
            source="shell",
        ),
        False,
        0,
    )


def _empty_stream():
    async def _gen():
        yield StreamChunk(text="", done=False)
        yield StreamChunk(text="", done=True)
    return _gen()


def _text_stream(text):
    async def _gen():
        yield StreamChunk(text=text, done=False)
        yield StreamChunk(text="", done=True)
    return _gen()


def _joined(messages) -> str:
    return " ".join(m.get("content", "") or "" for m in messages).lower()


class TestForcedToolNudgeAnchored:
    @pytest.mark.asyncio
    async def test_forced_tool_nudge_includes_original_request(self):
        """Text-without-tool on iter-0 gets the forced-tool nudge WITH the
        user's original request embedded (Session 314 pattern), so the model
        re-anchors on the task instead of treating the nudge as a generic
        'prove you can call a tool' prompt."""
        loop = AgentLoop(adapter=MagicMock())
        seen = {"calls": 0, "request_seen": False, "nudge_seen": False}

        async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
            seen["calls"] += 1
            if seen["calls"] == 1:
                assert tool_choice == "required"
                return _text_stream("Let me tell you about the files without looking.")
            if seen["calls"] == 2:
                joined = _joined(messages)
                seen["nudge_seen"] = "requires a tool call" in joined
                # The nudge must embed the ORIGINAL user request, not just the
                # generic "call the tool now" text.
                seen["request_seen"] = 'the user\'s request was: "create a project in dev/myapp"' in joined
                return ToolCallResult(
                    tool_name="shell",
                    tool_args={"command": "ls -la"},
                    raw_content="",
                )
            return _text_stream("Done.")

        mock_adapter = MagicMock()
        mock_adapter.chat_with_tools = chat_with_tools
        mock_adapter.chat = _text_stream("")

        await _run(loop, mock_adapter)

        assert seen["calls"] == 3
        assert seen["nudge_seen"], "the forced-tool nudge must reach the model"
        assert seen["request_seen"], (
            "the forced-tool nudge must embed the user's original request, got: "
            f"{seen!r}"
        )


class TestToolTalkNudgeAnchored:
    @pytest.mark.asyncio
    async def test_tool_talk_nudge_after_tools_ran_includes_advancement_hint(self):
        """The money case from the user's trace: after a tool already ran
        (recon), the model narrates tool intent instead of calling. The
        tool-talk nudge must (a) embed the user's original request and (b)
        name the tools already run and tell the model NOT to repeat them —
        so the nudge drives the next real step (e.g. file creation) instead
        of bouncing back into re-recon."""
        loop = AgentLoop(adapter=MagicMock())
        seen = {"calls": 0, "request_seen": False, "advance_seen": False}

        async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
            seen["calls"] += 1
            if seen["calls"] == 1:
                # Recon already done this turn — the step the user's trace
                # kept re-running.
                return ToolCallResult(
                    tool_name="shell",
                    tool_args={"command": "ls -la"},
                    raw_content="",
                )
            if seen["calls"] == 2:
                # deepseek-v4-flash behavior: narrate intent, no tool call.
                return _text_stream("Let me call the shell tool to check again.")
            if seen["calls"] == 3:
                joined = _joined(messages)
                seen["request_seen"] = 'the user\'s request was: "create a project in dev/myapp"' in joined
                seen["advance_seen"] = (
                    "you have already run these tools this turn: shell" in joined
                    and "do not repeat them" in joined
                    and "next step" in joined
                )
                return ToolCallResult(
                    tool_name="shell",
                    tool_args={"command": "mkdir -p dev/myapp"},
                    raw_content="",
                )
            return _text_stream("Done — project created.")

        mock_adapter = MagicMock()
        mock_adapter.chat_with_tools = chat_with_tools
        mock_adapter.chat = _text_stream("")

        chunks = await _run(loop, mock_adapter)
        full = "".join(c.text for c in chunks)

        assert seen["calls"] == 4, f"tool→tool-talk→nudge→tool→answer, got {seen['calls']} calls"
        assert seen["request_seen"], "the tool-talk nudge must embed the user's original request"
        assert seen["advance_seen"], (
            "the tool-talk nudge must name already-run tools and forbid repeating them "
            "(the re-recon loop from the user's trace)"
        )
        assert "Done — project created." in full


class TestEmptyResponseNudgeAnchored:
    @pytest.mark.asyncio
    async def test_empty_response_nudge_includes_original_request(self):
        """An empty iter-0 response gets the forced-tool nudge with the
        user's original request embedded."""
        loop = AgentLoop(adapter=MagicMock())
        seen = {"calls": 0, "request_seen": False}

        async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
            seen["calls"] += 1
            if seen["calls"] == 1:
                return _empty_stream()
            if seen["calls"] == 2:
                seen["request_seen"] = (
                    'the user\'s request was: "create a project in dev/myapp"' in _joined(messages)
                )
                return ToolCallResult(
                    tool_name="shell",
                    tool_args={"command": "mkdir -p dev/myapp"},
                    raw_content="",
                )
            return _text_stream("Done.")

        mock_adapter = MagicMock()
        mock_adapter.chat_with_tools = chat_with_tools
        mock_adapter.chat = _text_stream("")

        await _run(loop, mock_adapter)

        assert seen["calls"] == 3
        assert seen["request_seen"], "the empty-response nudge must embed the user's original request"
