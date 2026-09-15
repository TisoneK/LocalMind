"""Session 147 regression tests — heading-only final answers get rescued.

Real-model evidence (2026-08-11, zen/deepseek-v4-flash-free): a git-status
request ran real commands successfully but the model ended the turn with a
bare heading ("**Git status**", 14 chars). needs_report() correctly fired
(the heading quotes no evidence), and the loop dumped the deterministic
"Worker report — tool execution evidence:" recap — the exact output shape
the user has flagged repeatedly as "not an answer".

Session 147 changes the normal-completion path: before the report, run ONE
focused synthesis call (plain chat, user's request + tool observations).
Only fall back to the report when synthesis fails, times out, or itself
produces a non-substantive reply.

Contract under test:
  1. A heading-only final answer is replaced by the synthesized answer.
  2. When synthesis returns empty, the deterministic report still fires
     (the honest-evidence fallback is preserved).
  3. End-to-end: a tool-bearing turn that ends with a heading yields the
     synthesized answer, NOT a "Worker report".
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from adapters.ollama import ToolCallResult
from core.agent.loop import AgentLoop
from core.agent.models import AgentStep, AgentTrace
from core.models import Intent, RiskLevel, StreamChunk, ToolResult


def _git_status_trace() -> AgentTrace:
    """A trace with one successful git status tool step."""
    return AgentTrace(
        steps=[
            AgentStep(
                iteration=1,
                thought="check the repo state",
                tool_name="git",
                tool_input='{"operation": "status"}',
                observation=(
                    "On branch main\nYour branch is up to date with "
                    "'origin/main'.\n\nUntracked files:\n\tbackend/_tmp_x.py"
                ),
            )
        ]
    )


def _synth_stream(text: str):
    async def _stream():
        yield StreamChunk(text=text, done=False)
        yield StreamChunk(text="", done=True)

    return _stream()


class TestFinalAnswerRescue:
    @pytest.mark.asyncio
    async def test_heading_only_answer_rescued_by_synthesis(self):
        loop = AgentLoop(adapter=MagicMock())
        mock_adapter = MagicMock()
        mock_adapter.chat = lambda messages, temperature=0.4: _synth_stream(
            "Working tree is clean — no uncommitted changes."
        )

        chunks = []
        async for chunk in loop._rescue_final_answer(
            loop_messages=[{"role": "user", "content": "check git status"}],
            observation_log="[Tool result]: On branch main",
            active_adapter=mock_adapter,
            trace=_git_status_trace(),
            provider_usage={},
        ):
            chunks.append(chunk)

        full = "".join(c.text for c in chunks)
        assert "Working tree is clean" in full, f"expected synthesis, got {full!r}"
        assert "Worker report" not in full, (
            "a substantive synthesis must NOT be followed by the evidence report"
        )

    @pytest.mark.asyncio
    async def test_heading_only_answer_falls_back_to_report_when_synthesis_empty(self):
        loop = AgentLoop(adapter=MagicMock())
        mock_adapter = MagicMock()

        async def empty_chat(messages, temperature=0.4):
            return
            yield

        mock_adapter.chat = empty_chat

        chunks = []
        async for chunk in loop._rescue_final_answer(
            loop_messages=[{"role": "user", "content": "check git status"}],
            observation_log="[Tool result]: On branch main",
            active_adapter=mock_adapter,
            trace=_git_status_trace(),
            provider_usage={},
        ):
            chunks.append(chunk)

        full = "".join(c.text for c in chunks)
        assert "Worker report" in full, (
            "when synthesis yields nothing, the honest evidence report must still fire"
        )

    @pytest.mark.asyncio
    async def test_heading_only_answer_not_swallowed_by_force_final_answer_fallback(self):
        """The rescue must not pick up _force_final_answer's own empty-stream
        evidence summary (that would bypass the report fallback decision)."""
        loop = AgentLoop(adapter=MagicMock())
        mock_adapter = MagicMock()
        mock_adapter.chat = lambda messages, temperature=0.4: _synth_stream(
            "Working tree is clean — no uncommitted changes."
        )

        chunks = []
        async for chunk in loop._rescue_final_answer(
            loop_messages=[{"role": "user", "content": "check git status"}],
            observation_log="[Tool result]: On branch main",
            active_adapter=mock_adapter,
            trace=_git_status_trace(),
            provider_usage={},
        ):
            chunks.append(chunk)

        full = "".join(c.text for c in chunks)
        assert "Worker report" not in full
        assert "Here is what actually ran" not in full, (
            "the internal evidence summary must not leak through the rescue path"
        )


    @pytest.mark.asyncio
    async def test_synthesis_stream_preserves_interior_word_spaces(self):
        """The final-synthesis path ran the TRIMMING
        `_strip_minimax_tool_calls` per streamed delta, which .strip()s each
        chunk and welds words together ("Herearethetrending"). The stream
        variant must be used so boundary spaces survive the join."""
        loop = AgentLoop(adapter=MagicMock())

        async def multi_chunk(messages, temperature=0.4):
            for delta in ["Here", " are", " the", " trending", " stories", " today"]:
                yield StreamChunk(text=delta, done=False)
            yield StreamChunk(text="", done=True)

        mock_adapter = MagicMock()
        mock_adapter.chat = multi_chunk

        chunks = []
        async for chunk in loop._force_final_answer(
            loop_messages=[{"role": "user", "content": "show me trending stories"}],
            observation_log="[Tool result]: stories",
            active_adapter=mock_adapter,
            trace=None,
            provider_usage={},
        ):
            chunks.append(chunk)

        full = "".join(c.text for c in chunks)
        assert "Here are the trending stories today" in full, (
            f"interior word spaces were welded together: {full!r}"
        )

    @pytest.mark.asyncio
    async def test_synthesis_leaked_dsml_markup_is_stripped(self):
        """The browser-validated run leaked a raw
        <｜DSML｜tool_calls> block into the final answer because the rescue
        path only ran the system-leak filter. The strip must apply."""
        loop = AgentLoop(adapter=MagicMock())
        mock_adapter = MagicMock()
        mock_adapter.chat = lambda messages, temperature=0.4: _synth_stream(
            'The<｜DSML｜tool_calls> <｜DSML｜invoke name="shell"> '
            '<｜DSML｜parameter name="command" string="true">cd /Users/bao/Code/LocalMind && git status'
            '</｜DSML｜parameter> </｜DSML｜invoke> </｜DSML｜tool_calls> '
            "The working tree is clean — no uncommitted changes to report."
        )

        chunks = []
        async for chunk in loop._rescue_final_answer(
            loop_messages=[{"role": "user", "content": "check git status"}],
            observation_log="[Tool result]: On branch main",
            active_adapter=mock_adapter,
            trace=_git_status_trace(),
            provider_usage={},
        ):
            chunks.append(chunk)

        full = "".join(c.text for c in chunks)
        assert "DSML" not in full, f"DSML markup leaked into answer: {full!r}"
        assert "<invoke" not in full, f"invoke markup leaked into answer: {full!r}"
        assert "working tree is clean" in full, f"expected synthesis, got {full!r}"


class TestEndToEndHeadingRescue:
    @pytest.mark.asyncio
    async def test_tool_turn_ending_in_heading_yields_synthesized_answer(self):
        loop = AgentLoop(adapter=MagicMock())
        seen = {"calls": 0}

        async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
            seen["calls"] += 1
            if seen["calls"] == 1:
                return ToolCallResult(
                    tool_name="git",
                    tool_args={"operation": "status"},
                    raw_content="",
                )
            return _synth_stream("**Git status**")

        async def synth_chat(messages, temperature=0.4):
            yield StreamChunk(text="Working tree is clean — no uncommitted changes.", done=False)
            yield StreamChunk(text="", done=True)

        async def fake_dispatch(intent, raw_input, allowed_tool_names=None):
            return (
                ToolResult(
                    content=(
                        "On branch main\nYour branch is up to date with "
                        "'origin/main'.\n\nUntracked files:\n\tbackend/_tmp_x.py"
                    ),
                    risk=RiskLevel.LOW,
                    source="git",
                ),
                False,
                0,
            )

        mock_adapter = MagicMock()
        mock_adapter.chat_with_tools = chat_with_tools
        mock_adapter.chat = synth_chat

        chunks = []
        with patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
             patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x), \
             patch("core.agent.loop.dispatch_with_retry", side_effect=fake_dispatch):
            async for chunk in loop.run(
                messages=[{"role": "user", "content": "Check git status"}],
                intent=Intent.SHELL,
                initial_tool_result=None,
                available_tools=[],
                adapter=mock_adapter,
                skip_planning=True,
            ):
                chunks.append(chunk)

        full = "".join(c.text for c in chunks)
        assert "Working tree is clean" in full, f"expected synthesized answer, got {full!r}"
        assert "Worker report" not in full, (
            "a tool-bearing turn ending in a heading must be rescued by synthesis, "
            "not dumped as a Worker report"
        )
