"""
todo_write — the agent's control surface for the live UI Todos panel.

The agent calls this with the FULL current todo list (create / update / mark
complete in one shot, mirroring the reference agent's TodoWrite). It is a pure,
fast helper: it validates and normalizes the list, then hands the state back —
nothing more (no planning, no "understanding"). The AgentLoop reads the returned
`metadata["todos"]` and emits the `todo_cleared` / `todo_created` obs events that
the SSE bridge already forwards to the frontend's Todos panel.

Why the list flows back through metadata (not an obs emit here): tools run inside
`asyncio.wait_for` in the loop and do not hold the request's ObsCollector — the
same reason `describe_tool` reports its loaded tool via metadata. The loop owns
emission (see `_emit_todo_write_events` in loop.py).
"""

from __future__ import annotations

import ast
import json

from core.models import Intent, RiskLevel, ToolResult
from tools import register_tool

_VALID_STATUS = ("pending", "in_progress", "completed", "blocked")


def _coerce_todos(raw: object) -> list[dict]:
    """Turn the parsed input into a normalized list of todo dicts.

    Accepts either a bare list or a ``{"todos": [...]}`` wrapper. Each item may
    use ``text`` / ``content`` / ``task`` for the label and an optional
    ``status``; ``completed`` is derived from status when absent. Ids are kept if
    supplied, else assigned positionally so updates from the model line up.
    """
    if isinstance(raw, dict):
        raw = raw.get("todos", raw.get("items", raw.get("tasks", [])))
    if not isinstance(raw, list):
        return []

    todos: list[dict] = []
    for i, item in enumerate(raw):
        if isinstance(item, str):
            item = {"text": item}
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or item.get("content") or item.get("task") or "").strip()
        if not text:
            continue
        status = str(item.get("status") or "").strip().lower()
        if status not in _VALID_STATUS:
            status = "completed" if item.get("completed") else "pending"
        completed = bool(item.get("completed")) or status == "completed"
        if completed:
            status = "completed"
        todos.append(
            {
                "id": str(item.get("id") or f"t{i + 1}"),
                "text": text,
                "completed": completed,
                "status": status,
            }
        )
    return todos


def _render(todos: list[dict]) -> str:
    if not todos:
        return "Todo list cleared."
    marker = {"completed": "[x]", "in_progress": "[~]", "blocked": "[!]", "pending": "[ ]"}
    lines = [f"{marker.get(t['status'], '[ ]')} {t['text']}" for t in todos]
    done = sum(1 for t in todos if t["completed"])
    return f"Todo list ({done}/{len(todos)} done):\n" + "\n".join(lines)


async def todo_write(message: str) -> ToolResult:
    """Replace the session's todo list with the supplied items."""
    text = (message or "").strip()
    parsed: object = None
    if text:
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            # Defense in depth: accept a Python-repr list/dict (single quotes)
            # in case a caller ever str()s the args instead of JSON-encoding.
            try:
                parsed = ast.literal_eval(text)
            except (ValueError, SyntaxError):
                parsed = None

    if parsed is None:
        return ToolResult(
            content=(
                "todo_write expects a JSON list of todos, e.g. "
                '{"todos": [{"text": "read the file", "status": "in_progress"}, '
                '{"text": "summarize it", "status": "pending"}]}'
            ),
            risk=RiskLevel.LOW,
            source="todo_write",
            success=False,
            error_type="validation_error",
            error_message="Could not parse a JSON todo list from the input.",
        )

    todos = _coerce_todos(parsed)
    return ToolResult(
        content=_render(todos),
        risk=RiskLevel.LOW,
        source="todo_write",
        success=True,
        # The loop reads this to emit todo_cleared + todo_created obs events.
        metadata={"todos": todos},
    )


register_tool(
    Intent.TODO_WRITE,
    todo_write,
    description=(
        "Write or update the live task checklist shown in the user's Todos panel. "
        "Pass the FULL list every time as a JSON array — "
        '{"todos": [{"text": "step one", "status": "in_progress"}, '
        '{"text": "step two", "status": "pending"}]} — statuses are '
        "'pending' | 'in_progress' | 'completed' | 'blocked'. Use it for any "
        "multi-step task: create the checklist up front, then call again to mark "
        "the current step in_progress and finished steps completed, so the user "
        "sees live progress. Fast and side-effect-free besides the panel."
    ),
    cost=0.0,
    latency_ms=5,
    parallelizable=True,  # pure normalization, no I/O
)
