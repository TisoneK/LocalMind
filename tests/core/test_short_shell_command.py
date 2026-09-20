"""`ls` is a complete command.

The loop refused any tool input under three characters as "degenerate" (meant for blank or
punctuation-only queries). A live turn ("run ls in the workspace") then rejected `ls`, the model
could never make it longer, and the acceptance gate replanned thirteen times.
"""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from core.agent.loop import AgentLoop, _input_is_degenerate
from core.models import Intent, StreamChunk, ToolResult
from core.obs import ObsCollector


class TestInputIsDegenerate:
    @pytest.mark.parametrize("cmd", ["ls", "df", "ps", "id", "cd", "w", "du", "pwd", "ls -la"])
    def test_real_commands_are_not_degenerate(self, cmd):
        assert not _input_is_degenerate("shell", cmd)

    @pytest.mark.parametrize("junk", ["", "?", ".", " . ", "??", "..", "  "])
    def test_blank_and_punctuation_only_are_still_rejected(self, junk):
        assert _input_is_degenerate("shell", junk)

    def test_short_input_is_still_rejected_for_other_tools(self):
        assert _input_is_degenerate("web_search", "ls")
        assert _input_is_degenerate("file_task", "a")

    def test_symbols_are_not_a_command(self):
        assert _input_is_degenerate("shell", "&&")
        assert _input_is_degenerate("shell", "1")


def test_the_loop_runs_ls_instead_of_refusing_it():
    from adapters.ollama import ToolCallResult

    seen = {"calls": 0}
    ran: list[str] = []

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        seen["calls"] += 1
        if seen["calls"] == 1:
            return ToolCallResult(tool_name="shell", tool_args={"command": "ls"})

        async def _stream():
            yield StreamChunk(text="The folder holds notes.txt.", done=False)
            yield StreamChunk(text="", done=True)

        return _stream()

    async def dispatch(intent, tool_input, *a, **k):
        ran.append(tool_input)
        return ToolResult(source="shell", content="notes.txt"), False, 0

    adapter = MagicMock()
    adapter.chat_with_tools = chat_with_tools
    adapter.chat = lambda *a, **k: iter(())
    obs = ObsCollector()

    async def go():
        with patch("core.agent.loop.dispatch_with_retry", dispatch):
            return [
                c
                async for c in AgentLoop(adapter=MagicMock()).run(
                    messages=[{"role": "user", "content": "run ls in the workspace"}],
                    intent=Intent.SHELL,
                    initial_tool_result=None,
                    available_tools=[],
                    adapter=adapter,
                    obs=obs,
                    skip_planning=True,
                )
            ]

    chunks = asyncio.run(go())
    assert ran == ["ls"]
    assert "notes.txt" in "".join(c.text for c in chunks)
