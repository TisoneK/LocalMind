"""Session 326 regression tests — harness-owned synthesized todos (B-2026-08-20-23).

The warm-kernel runtime (``agent_runtime`` passes ``skip_planning=True``) gates
out ALL plan→todo branches in ``loop.py``, so the Todos panel was structurally
empty — the only remaining emission path was the model-voluntary ``todo_write``
tool, which free-tier models never call. The fix synthesizes one todo per REAL
tool execution (created on dispatch, completed when it lands): the panel is a
rendered artifact of what happened, never dependent on the model planning,
narrating, or cooperating.

Contract under test:
  - a tool-running warm-kernel turn emits syn-* todos (created + completed)
  - describe_tool scaffolding does NOT become a todo
  - when a plan-based todo list exists, no synthetic todos are emitted
  - the label is distilled from the tool call itself, not model narration
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class _ParentConfig:
    """Minimal stand-in for the runtime's ParentAgent config — only the
    attributes AgentLoop.run() reads (name, allowed_tools, iteration caps)."""

    name = "parent"
    allowed_tools = None
    tools_enabled = True

import pytest
from adapters.ollama import ToolCallResult
from core.agent.initialization import InitializationDecision
from core.agent.loop import AgentLoop, _synthetic_todo_text
from core.models import Intent, RiskLevel, StreamChunk, ToolResult
from core.obs import ObsCollector


def _text_stream(text: str):
    async def _gen():
        yield StreamChunk(text=text, done=False)
        yield StreamChunk(text="", done=True)

    return _gen()


def _empty_stream():
    async def _gen():
        yield StreamChunk(text="", done=False)
        yield StreamChunk(text="", done=True)

    return _gen()


def _fake_dispatch(intent, raw_input, **kwargs):
    return (
        ToolResult(content="ok", risk=RiskLevel.LOW, source="shell"),
        False,
        0,
    )


async def _run(loop, adapter, *, skip_planning=True, agent_config=None, obs=None):
    chunks = []
    with patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), patch(
        "core.agent.loop._filter_system_leaks", side_effect=lambda x: x
    ), patch("core.agent.loop.dispatch_with_retry", side_effect=_fake_dispatch):
        async for chunk in loop.run(
            messages=[{"role": "user", "content": "list files"}],
            intent=Intent.SHELL,
            initial_tool_result=None,
            available_tools=[],
            adapter=adapter,
            obs=obs,
            skip_planning=skip_planning,
            agent_config=agent_config,
        ):
            chunks.append(chunk)
    return chunks


def _todo_events(obs: ObsCollector, event_type: str):
    return [e for e in obs.history() if e.type == event_type]


def _adapter_with_calls(*call_returns):
    adapter = MagicMock()
    seen = {"calls": 0}

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        result = call_returns[min(seen["calls"], len(call_returns) - 1)]
        seen["calls"] += 1
        if isinstance(result, ToolCallResult):
            return result
        if hasattr(result, "__aiter__"):
            return result  # already an async generator (text/empty stream)
        return result()

    adapter.chat_with_tools = chat_with_tools
    adapter.chat = lambda *a, **k: _text_stream("")()
    return adapter


class TestSynthesizedTodos:
    @pytest.mark.asyncio
    async def test_warm_kernel_tool_turn_emits_synth_todo_created_and_completed(self):
        """The warm-kernel path (skip_planning=True, the runtime's actual call)
        emits a synthesized todo per real tool call and completes it — the
        panel is populated without ANY model cooperation."""
        loop = AgentLoop(adapter=MagicMock())
        adapter = _adapter_with_calls(
            ToolCallResult(tool_name="shell", tool_args={"command": "ls -la"}, raw_content=""),
            _text_stream("The files are listed."),
        )
        obs = ObsCollector()

        await _run(
            loop,
            adapter,
            skip_planning=True,
            agent_config=_ParentConfig(),
            obs=obs,
        )

        created = _todo_events(obs, "todo_created")
        completed = _todo_events(obs, "todo_completed")
        assert created, "a tool-running warm-kernel turn must populate the Todos panel"
        assert created[0].data["id"] == "syn-0"
        assert created[0].data["text"].startswith("Run:"), created[0].data
        # No plan-based todos exist in the warm-kernel path.
        assert not [e for e in created if e.data["id"].startswith("plan-")]
        assert any(c.data["id"] == "syn-0" for c in completed), "the synthesized todo must complete"

    @pytest.mark.asyncio
    async def test_describe_tool_scaffolding_does_not_become_a_todo(self):
        """Loading tool docs (describe_tool) is scaffolding, not a task step —
        it must not clutter the panel."""
        loop = AgentLoop(adapter=MagicMock())
        adapter = _adapter_with_calls(
            ToolCallResult(tool_name="describe_tool", tool_args={"tool_name": "shell"}, raw_content=""),
            ToolCallResult(tool_name="shell", tool_args={"command": "ls -la"}, raw_content=""),
            _text_stream("done"),
        )
        obs = ObsCollector()

        await _run(loop, adapter, skip_planning=True, obs=obs)

        created = _todo_events(obs, "todo_created")
        # Only the real tool call becomes a todo — and it is the first one.
        assert len(created) == 1, [e.data for e in created]
        assert created[0].data["id"] == "syn-0"
        assert created[0].data["text"].startswith("Run:")

    @pytest.mark.asyncio
    async def test_plan_based_todos_suppress_synthetic_duplicates(self):
        """When a plan exists (parent init returned plan_steps), the loop emits
        the plan todos and NO synthetic ones — no double checklist."""
        loop = AgentLoop(adapter=MagicMock())
        adapter = _adapter_with_calls(
            ToolCallResult(tool_name="shell", tool_args={"command": "ls -la"}, raw_content=""),
            _text_stream("done"),
        )
        obs = ObsCollector()

        async def fake_init(active_adapter, messages, env_context, intent_history=None):
            yield "ack", "Working on it"
            yield "understanding", "objective"
            yield "decision", InitializationDecision(
                mode="execute",
                objective="list files",
                acknowledgement="Working on it",
                plan_steps=["Step A", "Step B"],
            )

        with patch.object(loop, "_initialize_parent_streaming", fake_init):
            await _run(
                loop,
                adapter,
                skip_planning=False,
                agent_config=_ParentConfig(),
                obs=obs,
            )

        created = _todo_events(obs, "todo_created")
        plan_ids = [e.data["id"] for e in created]
        assert plan_ids == ["plan-0", "plan-1"], plan_ids
        assert not [e for e in created if e.data["id"].startswith("syn-")], (
            "synthetic todos must not double the plan-based checklist"
        )

    def test_synthetic_todo_text_distilled_from_tool_call(self):
        """The label is terse and imperative, built from the tool call itself —
        never from model narration."""
        assert _synthetic_todo_text("shell", "mkdir -p Dev/test-run") == "Run: mkdir -p Dev/test-run"
        assert _synthetic_todo_text("file_write", "notes.txt: hello from deepseek").startswith("Write:")
        assert _synthetic_todo_text("file_task", "C:\\Dev\\test-run\\notes.txt").startswith("Read:")
        assert _synthetic_todo_text("web_search", "current weather") == "Search: current weather"
        # Unknown tools fall back to a verb-ified name; empty input → verb only.
        assert _synthetic_todo_text("some_custom_tool", "") == "some custom tool"
        assert _synthetic_todo_text("shell", "") == "Run"
