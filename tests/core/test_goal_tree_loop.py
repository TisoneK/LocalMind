"""
B-2026-08-23-8: the goal TREE — deterministic hierarchical sub-goals.

Every derived top-level goal (file/folder deliverable) carries ordered
sub-goals (check → prep → write → verify), each feeding the next. The
tree is derived ONCE with the flat checklist (Session 330 contract — the
denominator never mutates) and is:
  - seeded as nested Todos rows (plan-{i}-sub-{j}) after their parent,
  - injected into the model context as an ordered route,
  - completed together with the parent (never advanced separately).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.agent.loop import _render_goal_route


def test_render_goal_route_empty_when_no_tree():
    assert _render_goal_route(None) == ""
    assert _render_goal_route([]) == ""
    assert _render_goal_route([{"goal": "  ", "sub_goals": []}]) == ""


def test_render_goal_route_ordered_and_numbered():
    rendered = _render_goal_route(
        [
            {
                "goal": "file exists at a.txt with content",
                "sub_goals": [
                    "check whether a.txt already exists (read it if so)",
                    "write a.txt with the full content",
                    "verify a.txt exists with the expected content",
                ],
            },
            {
                "goal": "folder created at path-test",
                "sub_goals": [
                    "check whether the folder path-test already exists",
                ],
            },
        ]
    )
    lines = rendered.splitlines()
    assert lines[0] == "# Goal route (follow in order; each step feeds the next)"
    assert "Goal 1: file exists at a.txt with content" in lines
    assert "   1. check whether a.txt already exists (read it if so)" in lines
    assert "   2. write a.txt with the full content" in lines
    assert "   3. verify a.txt exists with the expected content" in lines
    assert "Goal 2: folder created at path-test" in lines


# ── loop integration ─────────────────────────────────────────────────────────


def _make_adapter(script: list):
    """Fake adapter returning the scripted ToolCallResults, then streaming.
    Also records every `messages` list it was called with so the test can
    assert the goal route was injected into the prompt."""
    from core.models import StreamChunk

    calls = list(script)
    seen_messages: list[list] = []

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        seen_messages.append(list(messages))
        if calls:
            return calls.pop(0)

        async def _stream():
            yield StreamChunk(text="Done.", done=False)
            yield StreamChunk(text="", done=True)

        return _stream()

    async def empty_chat(messages, temperature=0.4, **kwargs):
        if False:
            yield None

    adapter = MagicMock()
    adapter.chat_with_tools = chat_with_tools
    adapter.chat = empty_chat
    return adapter, calls, seen_messages


def _patch_filters():
    from contextlib import ExitStack

    stack = ExitStack()
    stack.enter_context(patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x))
    stack.enter_context(patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x))
    return stack


async def _run_loop(adapter, obs_collector, intent, message, plan_steps=None, goal_tree=None):
    from core.agent.loop import AgentLoop

    loop = AgentLoop(adapter=MagicMock())
    with _patch_filters():
        async for _ in loop.run(
            messages=[{"role": "user", "content": message}],
            intent=intent,
            initial_tool_result=None,
            available_tools=[],
            adapter=adapter,
            obs=obs_collector,
            # skip_planning routes to the plan_steps seeding branch (the
            # warm-kernel parent path this feature rides on).
            skip_planning=True,
            plan_steps=plan_steps,
            goal_tree=goal_tree,
        ):
            pass


@pytest.mark.asyncio
async def test_loop_seeds_subgoal_todos_and_injects_route():
    """The runtime passes plan_steps + goal_tree → the loop must emit
    plan-{i}-sub-{j} todo rows after their parent AND inject the ordered
    goal route into the model context."""
    from adapters.ollama import ToolCallResult
    from core.models import Intent
    from core.obs import ObsCollector

    goal_tree = [
        {
            "goal": "file exists at a.txt with content",
            "sub_goals": [
                "check whether a.txt already exists (read it if so)",
                "write a.txt with the full content",
                "verify a.txt exists with the expected content",
            ],
        },
        {
            "goal": "folder created at path-test",
            "sub_goals": [
                "check whether the folder path-test already exists",
                "create the folder path-test only if it is missing",
                "verify the folder path-test exists",
            ],
        },
    ]
    plan_steps = [g["goal"] for g in goal_tree]

    script = [
        ToolCallResult(
            tool_name="file_write",
            tool_args={"path": "/tmp/lm-goal-x/a.txt", "content": "hello"},
        ),
        ToolCallResult(
            tool_name="file_write",
            tool_args={"path": "/tmp/lm-goal-x/b.txt", "content": "world"},
        ),
    ]
    adapter, leftover, seen_messages = _make_adapter(script)
    obs_collector = ObsCollector()

    with patch("core.config._allowed_user_folders", return_value=["/tmp"]):
        await _run_loop(
            adapter,
            obs_collector,
            Intent.FILE_WRITE,
            "create a.txt and path-test",
            plan_steps=plan_steps,
            goal_tree=goal_tree,
        )

    # Sub-goal todos seeded right after their parents.
    created = {
        evt.data.get("id"): evt.data.get("text")
        for evt in obs_collector.drain_matching({"todo_created"})
    }
    assert "plan-0" in created
    assert "plan-0-sub-0" in created
    assert "plan-0-sub-1" in created
    assert "plan-0-sub-2" in created
    assert "plan-1-sub-0" in created
    assert created["plan-0-sub-0"].startswith("check whether a.txt")
    assert created["plan-1-sub-0"].startswith("check whether the folder path-test")

    # The goal route must be inside the system prompt the model saw.
    all_context = "\n".join(
        str(m.get("content") or "")
        for msgs in seen_messages
        for m in msgs
        if m.get("role") == "system"
    )
    assert "# Goal route" in all_context
    assert "Goal 1: file exists at a.txt with content" in all_context
    assert "   2. write a.txt with the full content" in all_context

    assert not leftover
