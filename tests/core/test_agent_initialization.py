"""Tests for the parent-agent initialization decision contract."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from adapters.ollama import ToolCallResult
from agents.parent import ParentAgent
from core.agent.initialization import (
    InitializationDecision,
    build_initialization_prompt,
    parse_initialization,
)
from core.agent.loop import AgentLoop
from core.models import Intent, StreamChunk, ToolResult
from core.obs import ObsCollector


def test_parse_execute_decision_preserves_plan_and_contract():
    decision = parse_initialization(
        '{"mode":"execute","acknowledgement":"I understand.",'
        '"objective":"Find the current weather",'
        '"tool_names":["web_search","web_fetch"],'
        '"plan_steps":["Search Kitengela weather today", "Fetch a reliable result"],'
        '"success_criteria":["current source found"],"confidence":0.92}'
    )

    assert isinstance(decision, InitializationDecision)
    assert decision.mode == "execute"
    assert decision.tool_names == ["web_search", "web_fetch"]
    assert decision.plan_steps[0].startswith("Search")
    assert decision.success_criteria == ["current source found"]
    assert "UNDERSTANDING: Find the current weather" in decision.plan_text()


def test_parse_direct_decision_returns_complete_answer():
    decision = parse_initialization(
        '```json\n{"mode":"direct","acknowledgement":"Hi!",'
        '"response":"Hello from LocalMind.","confidence":0.99}\n```'
    )

    assert decision.is_direct
    assert decision.response == "Hello from LocalMind."


def test_parse_clarify_decision_requires_one_question():
    decision = parse_initialization(
        '{"mode":"clarify","acknowledgement":"I can do that.",'
        '"clarifying_question":"Which project should I use?"}'
    )

    assert decision.is_clarification
    assert decision.clarifying_question == "Which project should I use?"


def test_invalid_or_empty_output_fails_open_to_parent_execution():
    decision = parse_initialization("not JSON from a provider")

    assert decision.mode == "execute"
    assert decision.plan_steps
    assert decision.raw == "not JSON from a provider"


def test_missing_direct_response_cannot_end_the_turn():
    decision = parse_initialization('{"mode":"direct","response":""}')

    assert decision.mode == "execute"
    assert decision.plan_steps


@pytest.mark.asyncio
async def test_parent_uses_initialization_for_direct_response_without_execution_call():
    class Adapter:
        def __init__(self):
            self.execution_calls = 0

        async def chat(self, messages, temperature=0.1, intent="chat"):
            yield StreamChunk(
                text=(
                    '{"mode":"direct","acknowledgement":"Hi!",'
                    '"response":"Hello from the parent agent."}'
                )
            )

        async def chat_with_tools(self, *args, **kwargs):
            self.execution_calls += 1
            raise AssertionError("direct initialization must not execute tools")

    adapter = Adapter()
    config = ParentAgent(adapter=None).config()
    obs = ObsCollector()
    chunks = [
        chunk
        async for chunk in AgentLoop(adapter=adapter).run(
            messages=[{"role": "user", "content": "Hi"}],
            intent=Intent.ANALYZE,
            initial_tool_result=None,
            available_tools=[],
            adapter=adapter,
            agent_config=config,
            allowed_tool_names=frozenset(),
            obs=obs,
        )
    ]

    assert "Hello from the parent agent." in "".join(chunk.text for chunk in chunks)
    assert adapter.execution_calls == 0
    assert sum(chunk.done for chunk in chunks) == 1
    timings = [event for event in obs.history() if event.type == "stage_timing"]
    assert any(event.data["stage"] == "agent_initialize" for event in timings)


@pytest.mark.asyncio
async def test_parent_initialization_precedes_tool_execution():
    class Adapter:
        def __init__(self):
            self.initialization_calls = 0
            self.execution_calls = 0

        async def chat(self, messages, temperature=0.1, intent="chat"):
            self.initialization_calls += 1
            yield StreamChunk(
                text=(
                    '{"mode":"execute","acknowledgement":"I will inspect it.",'
                    '"objective":"Run the requested command",'
                    '"tool_names":["shell"],"plan_steps":["Run `pwd`"],'
                    '"success_criteria":["command completed without error"]}'
                )
            )

        async def chat_with_tools(self, *args, **kwargs):
            self.execution_calls += 1
            if self.execution_calls == 1:
                return ToolCallResult(tool_name="shell", tool_args={"command": "pwd"})

            async def _answer():
                yield StreamChunk(text="The command completed.")
                yield StreamChunk(text="", done=True)

            return _answer()

    adapter = Adapter()
    config = ParentAgent(adapter=None).config()
    with patch(
        "core.agent.loop.dispatch_with_retry",
        return_value=(ToolResult(content="/workspace", source="shell"), False, 0),
    ):
        chunks = [
            chunk
            async for chunk in AgentLoop(adapter=adapter).run(
                messages=[{"role": "user", "content": "run pwd"}],
                intent=Intent.ANALYZE,
                initial_tool_result=None,
                available_tools=[{"intent": "shell", "description": "Run a command"}],
                adapter=adapter,
                agent_config=config,
                allowed_tool_names=frozenset({"shell"}),
                obs=ObsCollector(),
            )
        ]

    assert adapter.initialization_calls == 1
    assert adapter.execution_calls >= 2
    assert "The command completed." in "".join(chunk.text for chunk in chunks)


def test_initialization_prompt_exposes_all_tools_without_route_hint():
    prompt = build_initialization_prompt(
        "What is the weather?",
        [
            {"intent": "web_search", "description": "Search live sources"},
            {"intent": "shell", "description": "Run a local command"},
        ],
        env_context="Current date: 2026-08-14",
    )

    assert "web_search" in prompt
    assert "shell" in prompt
    assert 'mode": "direct|clarify|execute"' in prompt
    assert "intent classifier determined" not in prompt.lower()
