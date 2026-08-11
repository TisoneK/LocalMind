'''Session 134 regression tests — dispatcher execution-plan reuse.

The 4-7 model-call chain per tool request was: dispatcher (call #1, which
ALREADY emits an execution_plan) → agent planning (call #2, re-deriving the
same plan) → loop iterations (calls #3+). The plan call is now skipped when
the dispatcher produced a usable plan, and the dispatcher's steps are
injected as orchestrator_context + Todos.

These tests pin the pure helpers (routing_helpers) that decide reuse and
the loop's todo-seeding from passed plan steps.
'''

from __future__ import annotations

import asyncio

import pytest
from core.agent.loop import AgentLoop
from core.engine.routing_helpers import _dispatcher_plan_context, _dispatcher_plan_steps
from core.execution_graph import ExecutionGraph, build_graph_from_plan_steps
from core.models import Intent, StreamChunk
from core.obs import ObsCollector


def _graph_with_labels():
    return build_graph_from_plan_steps(
        [
            {"id": "s1", "capability": "shell", "tool": "shell", "label": "Run git status in the repo root"},
            {"id": "s2", "capability": "shell", "tool": "shell", "label": "Show diff if changes exist"},
        ]
    )


def test_empty_graph_is_not_usable():
    assert _dispatcher_plan_context(ExecutionGraph()) == ""
    assert _dispatcher_plan_steps(ExecutionGraph()) == []


def test_none_graph_is_not_usable():
    assert _dispatcher_plan_context(None) == ""
    assert _dispatcher_plan_steps(None) == []


def test_labeled_graph_formats_numbered_plan():
    ctx = _dispatcher_plan_context(_graph_with_labels())
    assert ctx == (
        "1. Run git status in the repo root (via shell)\n"
        "2. Show diff if changes exist (via shell)"
    )
    steps = _dispatcher_plan_steps(_graph_with_labels())
    assert steps == ["Run git status in the repo root", "Show diff if changes exist"]


def test_unlabeled_nodes_are_not_a_usable_plan():
    # Fallback plans / degenerate LLM output produce nodes without labels —
    # these must NOT count as a reusable plan (planner stays in place).
    graph = build_graph_from_plan_steps(
        [
            {"id": "s1", "capability": "shell", "tool": "shell", "label": ""},
        ]
    )
    assert _dispatcher_plan_context(graph) == ""
    assert _dispatcher_plan_steps(graph) == []


def test_single_labeled_node_is_usable():
    graph = build_graph_from_plan_steps(
        [{"id": "s1", "capability": "sysinfo", "tool": "sysinfo", "label": "Get current time"}]
    )
    assert _dispatcher_plan_context(graph) == "1. Get current time (via sysinfo)"
    assert _dispatcher_plan_steps(graph) == ["Get current time"]


class _FakeAdapter:
    """Minimal adapter stub — chat_with_tools returns a plain-text final
    answer stream (no tool calls), so the loop streams it and finishes on
    the first iteration without touching real tools."""

    def __init__(self):
        self.calls = []

    async def chat_with_tools(self, **kwargs):
        self.calls.append(kwargs)

        async def _stream():
            yield StreamChunk(text="done", done=True)

        return _stream()


async def _drain(agen):
    out = []
    async for chunk in agen:
        out.append(chunk)
    return out


@pytest.mark.asyncio
async def test_loop_seeds_todos_from_passed_plan_steps_without_planning_call():
    """skip_planning=True + plan_steps must emit todo_created for the passed
    steps and must NOT run the planner (no separate planning model call)."""
    obs = ObsCollector()
    adapter = _FakeAdapter()
    loop = AgentLoop(adapter=adapter)
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "check git status"}]

    chunks = await _drain(
        loop.run(
            messages=messages,
            intent=Intent.SHELL,
            initial_tool_result=None,
            available_tools=[],
            obs=obs,
            skip_planning=True,
            plan_steps=["Run git status in the repo root", "Show diff if changes exist"],
            adapter=adapter,
        )
    )

    # Todo events for both steps.
    todo_events = [e for e in obs.history() if e.type == "todo_created"]
    assert len(todo_events) == 2
    assert todo_events[0].data["text"] == "Run git status in the repo root"
    assert todo_events[1].data["id"] == "plan-1"

    # No planning phase events (planner skipped).
    assert not [e for e in obs.history() if e.type == "agent_planning_start"]

    # The final answer still streams.
    assert any(chunk.done for chunk in chunks)


def test_loop_without_plan_steps_keeps_empty_plan():
    """When planning is skipped and no plan_steps are passed (existing simple
    intent fast path), the loop still works with an empty plan."""
    obs = ObsCollector()
    adapter = _FakeAdapter()
    loop = AgentLoop(adapter=adapter)
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hello"}]

    async def _run():
        chunks = []
        async for chunk in loop.run(
            messages=messages,
            intent=Intent.CHAT,
            initial_tool_result=None,
            available_tools=[],
            obs=obs,
            skip_planning=True,
            adapter=adapter,
        ):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(_run())
    assert any(chunk.done for chunk in chunks)
    assert not [e for e in obs.history() if e.type == "todo_created"]
