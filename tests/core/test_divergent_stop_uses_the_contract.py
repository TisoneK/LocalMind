"""The divergent-tool budget must see the turn's success contract.

`TaskState` stores the contract as `success_criteria`; the budget check read an attribute named
`criteria`, which does not exist, so it never saw one. Every turn that made five real tool calls
was force-stopped as a "goose chase" — including a turn with a complete contract whose steps were
all succeeding (check, write, edit, read back) — and its plan was left unfinished.
"""
import asyncio
from unittest.mock import MagicMock, patch

from core.agent.loop import AgentLoop
from core.models import Intent, StreamChunk, ToolResult
from core.obs import ObsCollector

COMMANDS = ["ls", "pwd", "whoami", "date", "uname", "echo hello"]


def _run(success_criteria):
    from adapters.ollama import ToolCallResult

    seen = {"calls": 0}
    ran: list[str] = []

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        seen["calls"] += 1
        if seen["calls"] <= len(COMMANDS):
            return ToolCallResult(tool_name="shell", tool_args={"command": COMMANDS[seen["calls"] - 1]})

        async def _stream():
            yield StreamChunk(text="All six commands ran.", done=False)
            yield StreamChunk(text="", done=True)

        return _stream()

    async def dispatch(intent, tool_input, *a, **k):
        ran.append(tool_input)
        return ToolResult(source="shell", content=f"output of {tool_input}"), False, 0

    adapter = MagicMock()
    adapter.chat_with_tools = chat_with_tools
    adapter.chat = lambda *a, **k: iter(())
    obs = ObsCollector()

    async def go():
        with patch("core.agent.loop.dispatch_with_retry", dispatch):
            return [
                c
                async for c in AgentLoop(adapter=MagicMock()).run(
                    messages=[{"role": "user", "content": "run these six commands and show me each"}],
                    intent=Intent.SHELL,
                    initial_tool_result=None,
                    available_tools=[],
                    adapter=adapter,
                    obs=obs,
                    skip_planning=True,
                    success_criteria=success_criteria,
                )
            ]

    asyncio.run(go())
    stops = obs.drain_matching({"agent_loop_divergent_stop"})
    return ran, stops


def test_a_turn_with_a_contract_is_not_cut_short_after_five_tools():
    ran, stops = _run(["six command outputs are shown"])
    assert not stops
    assert len(ran) == len(COMMANDS)


def test_a_turn_with_no_contract_still_gets_the_goose_chase_stop():
    ran, stops = _run(None)
    assert len(stops) == 1
    assert len(ran) < len(COMMANDS)
