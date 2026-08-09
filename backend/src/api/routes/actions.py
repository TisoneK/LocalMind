"""Actions endpoint - tool call history for left panel ActionHistory.

Session 118: replaced the placeholder stub (which returned [] and never
persisted) with the SQLite-backed actions table in SessionStore. The SSE
bridge in chat.py records live tool events into this store; the frontend
polls these endpoints for history across reloads.
"""

from __future__ import annotations

import time
from typing import List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from core.config import settings
from storage.db import SessionStore

router = APIRouter()
_store = SessionStore(settings.localmind_db_path)


class ActionItem(BaseModel):
    id: str
    session_id: str
    type: str  # tool name (frontend ActionItem.type)
    label: str
    detail: str  # short input preview for the collapsed row
    status: str  # "running", "done", "failed", "pending"
    timestamp: str  # "HH:MM" display string, matching live actions
    duration: Optional[float] = None
    input: Optional[str] = None  # verbatim command/args
    output: Optional[str] = None
    error: Optional[str] = None
    iteration: Optional[int] = None  # agent loop step number (for chaining)
    todo_id: Optional[str] = None  # plan todo this action serves (Session 120)


def _to_action_item(row: dict) -> ActionItem:
    ts = row.get("timestamp") or 0.0
    detail = row.get("input") or row.get("label") or ""
    if len(detail) > 80:
        detail = detail[:77] + "..."
    return ActionItem(
        id=row["id"],
        session_id=row["session_id"],
        type=row["tool_name"],
        label=row.get("label") or row["tool_name"],
        detail=detail,
        status=row["status"],
        timestamp=time.strftime("%H:%M", time.localtime(ts)),
        duration=row.get("duration"),
        input=row.get("input"),
        output=row.get("output"),
        error=row.get("error"),
        iteration=row.get("iteration"),
        todo_id=row.get("todo_id"),
    )


@router.get("/actions", response_model=List[ActionItem])
async def get_actions(session_id: Optional[str] = Query(None)):
    """Get tool call history, optionally filtered by session_id."""
    if not session_id:
        return []
    rows = _store.list_actions(session_id, limit=100)
    return [_to_action_item(r) for r in rows]


class CreateActionRequest(BaseModel):
    session_id: str
    tool_name: str
    status: str = "running"
    input: Optional[str] = None
    label: Optional[str] = None
    action_id: Optional[str] = None
    todo_id: Optional[str] = None


@router.post("/actions", response_model=ActionItem)
async def create_action(request: CreateActionRequest):
    """Record a new tool action (used by the SSE bridge for live actions)."""
    aid = _store.create_action(
        session_id=request.session_id,
        tool_name=request.tool_name,
        status=request.status,
        label=request.label or "",
        input=request.input or "",
        action_id=request.action_id or "",
        todo_id=request.todo_id,
    )
    return _to_action_item(
        {
            "id": aid,
            "session_id": request.session_id,
            "tool_name": request.tool_name,
            "status": request.status,
            "label": request.label or "",
            "input": request.input or "",
            "output": None,
            "error": None,
            "duration": None,
            "iteration": None,
            "todo_id": request.todo_id,
            "timestamp": time.time(),
        }
    )


class UpdateActionRequest(BaseModel):
    status: Optional[str] = None
    output: Optional[str] = None
    error: Optional[str] = None
    duration: Optional[float] = None


@router.patch("/actions/{action_id}", response_model=ActionItem)
async def update_action(action_id: str, request: UpdateActionRequest):
    """Update action status, output, or duration (used by the SSE bridge)."""
    _store.update_action(
        action_id=action_id,
        status=request.status,
        output=request.output,
        error=request.error,
        duration=request.duration,
    )
    # Return the updated row for API symmetry; the frontend reads via GET.
    return ActionItem(
        id=action_id,
        session_id="",
        type="",
        label="",
        detail="",
        status=request.status or "done",
        timestamp="",
    )
