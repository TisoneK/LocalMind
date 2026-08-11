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

    # Session 142: the loop closes out the current plan step's todo when
    # the turn ends WITHOUT narration (the common silent tool-run case).
    # Previously the executed step stayed 'pending' — the user's real run
    # showed "task ran but checkbox stayed unchecked".
    completed = [e for e in obs.history() if e.type == "todo_completed"]
    assert completed, "loop must emit todo_completed for the silent (non-narration) turn end"
    assert completed[-1].data["id"] == "plan-0"
    assert completed[-1].data.get("completed") is True

    # The final answer still streams.
    assert any(chunk.done for chunk in chunks)


@pytest.mark.asyncio
async def test_loop_attaches_plan_step_label_as_tool_call_reasoning():
    """Session 142: the 'why' for a tool call under a plan step must be the
    plan-step label. The frontend renders `why: {action.reasoning}` in the
    Actions/tool-step cards; before this fix only the model's pre-tool
    narration (thought=) was attached, so a SILENT tool run (empty
    narration — the common free-tier case) rendered a blank 'why:' even
    though the plan step label was in scope the whole time.

    Drive a real MultiToolCallResult through the loop (single shell call,
    no narration), with dispatch patched to a canned result, and assert the
    emitted tool_call obs events carry reasoning == the active plan step."""
    from adapters.ollama import MultiToolCallResult, ToolCallResult

    obs = ObsCollector()
    adapter = _FakeAdapter()
    loop = AgentLoop(adapter=adapter)
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "show projects in dev"}]

    plan = ["List the contents of the dev directory to show all projects"]

    calls = []

    class _ToolCallingAdapter:
        """Returns a silent (no narration) shell tool call, then a plain
        final answer — exercising the silent-tool-run shape from the user's
        real failure (blank why: + unchecked todo)."""

        def __init__(self):
            self.phase = 0

        async def chat_with_tools(self, **kwargs):
            self.phase += 1
            calls.append(kwargs)
            if self.phase == 1:
                tc = ToolCallResult(
                    tool_name="shell",
                    tool_args={"command": "dir C:\\Users\\tison\\dev"},
                    raw_content="",
                )
                return MultiToolCallResult(calls=[tc])

            async def _stream():
                yield StreamChunk(text="done", done=True)

            return _stream()

    from unittest.mock import patch as _patch

    from core.models import RiskLevel, ToolResult

    async def _fake_dispatch(tool_intent, tool_input, max_retries=1, base_delay=0, adapter=None, allowed_tool_names=None):
        return ToolResult(
            content=" Volume in drive C has no label.\n Directory of C:\\Users\\tison\\dev",
            source="shell",
            risk=RiskLevel.LOW,
        ), False, 0

    with _patch("core.agent.loop.dispatch_with_retry", _fake_dispatch):
        await _drain(
            loop.run(
                messages=messages,
                intent=Intent.SHELL,
                initial_tool_result=None,
                available_tools=[],
                obs=obs,
                skip_planning=True,
                plan_steps=plan,
                adapter=_ToolCallingAdapter(),
            )
        )

    # The tool_call started/done events must carry the plan-step label as
    # the 'why' (reasoning=) — the field the frontend renders as `why:`.
    tool_events = [e for e in obs.history() if e.type == "tool_call"]
    assert tool_events, "expected tool_call obs events"
    for evt in tool_events:
        assert evt.data.get("reasoning") == plan[0], (
            "tool_call must attach the active plan-step label as reasoning; "
            f"got {evt.data.get('reasoning')!r}"
        )

    # The silent tool run also closes the current plan step's todo at turn end.
    completed = [e for e in obs.history() if e.type == "todo_completed"]
    assert completed, "silent tool run must still complete the plan todo"


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
