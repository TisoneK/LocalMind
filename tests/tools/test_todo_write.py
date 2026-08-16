"""Tests for todo_write — the agent's live UI todo control surface (ADR-43)."""

import pytest

from core.agent.loop import _emit_todo_write_events
from tools.todo_write import _coerce_todos, todo_write


# ── Tool: parse + normalize ───────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_todo_write_wrapper_form_normalizes():
    r = await todo_write(
        '{"todos": [{"text": "read file", "status": "in_progress"}, '
        '{"text": "summarize", "status": "pending"}, '
        '{"text": "ship", "status": "completed"}]}'
    )
    assert r.success
    todos = r.metadata["todos"]
    assert [t["text"] for t in todos] == ["read file", "summarize", "ship"]
    assert [t["id"] for t in todos] == ["t1", "t2", "t3"]  # positional ids
    assert todos[0]["status"] == "in_progress" and todos[0]["completed"] is False
    assert todos[2]["status"] == "completed" and todos[2]["completed"] is True


@pytest.mark.asyncio
async def test_todo_write_bare_list_and_string_items():
    r = await todo_write('["step a", "step b"]')  # bare list of strings
    todos = r.metadata["todos"]
    assert [t["text"] for t in todos] == ["step a", "step b"]
    assert all(t["status"] == "pending" and not t["completed"] for t in todos)


@pytest.mark.asyncio
async def test_todo_write_completed_flag_implies_status():
    r = await todo_write('{"todos": [{"text": "x", "completed": true}]}')
    assert r.metadata["todos"][0]["status"] == "completed"


@pytest.mark.asyncio
async def test_todo_write_rejects_non_json():
    r = await todo_write("please make a todo list")
    assert not r.success and r.error_type == "validation_error"


def test_coerce_drops_empty_and_bad_items():
    todos = _coerce_todos({"todos": [{"text": "  "}, 42, {"no_text": "y"}, {"text": "keep"}]})
    assert [t["text"] for t in todos] == ["keep"]


def test_coerce_unknown_status_falls_back_to_pending():
    todos = _coerce_todos([{"text": "x", "status": "banana"}])
    assert todos[0]["status"] == "pending"


# ── Loop: emission of todo_* obs events ───────────────────────────────────────
class _Obs:
    def __init__(self):
        self.events = []

    def emit(self, event_type, **data):
        self.events.append((event_type, data))


class _Result:
    def __init__(self, todos, success=True):
        self.success = success
        self.metadata = {"todos": todos}


def test_emit_clears_then_creates_each_todo():
    obs = _Obs()
    todos = [
        {"id": "t1", "text": "a", "completed": False, "status": "in_progress"},
        {"id": "t2", "text": "b", "completed": True, "status": "completed"},
    ]
    _emit_todo_write_events("todo_write", _Result(todos), obs)

    types = [e[0] for e in obs.events]
    assert types == ["todo_cleared", "todo_created", "todo_created"]  # full replace
    first = obs.events[1][1]
    assert first == {"id": "t1", "text": "a", "completed": False, "status": "in_progress"}
    assert obs.events[2][1]["completed"] is True


def test_emit_ignores_other_tools_and_failures():
    obs = _Obs()
    _emit_todo_write_events("shell", _Result([{"id": "t1", "text": "a"}]), obs)
    _emit_todo_write_events("todo_write", _Result([{"text": "a"}], success=False), obs)
    _emit_todo_write_events("todo_write", None, obs)
    assert obs.events == []
