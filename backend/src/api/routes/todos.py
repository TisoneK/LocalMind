"""Todos endpoint - task management for left panel TodoList.

Session 27: previously a stub (returned [], didn't persist). Now backed
by a real todos table (migration 006). The engine writes todos here when
it starts a multi-step task; the UI reads them via GET /todos?session_id=X.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from core.config import settings

router = APIRouter()


def _get_db_path() -> str:
    """Get the DB path dynamically — reads from settings each time so
    monkeypatching LOCALMIND_DB_PATH in tests works."""

    return settings.localmind_db_path


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_get_db_path())
    conn.row_factory = sqlite3.Row
    return conn


class TodoItem(BaseModel):
    id: str
    session_id: str
    content: str
    completed: bool = False
    status: str = "pending"  # pending, in_progress, done, failed
    priority: str = "medium"
    order: int = 0
    timestamp: float
    title: Optional[str] = None  # B-2026-08-23-11: short user-facing label


class CreateTodoRequest(BaseModel):
    session_id: str
    content: str
    priority: str = "medium"
    status: str = "pending"
    title: Optional[str] = None  # B-2026-08-23-11


class UpdateTodoRequest(BaseModel):
    content: Optional[str] = None
    completed: Optional[bool] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    title: Optional[str] = None  # B-2026-08-23-11


class CreateTodoBatchRequest(BaseModel):
    """Batch-create todos for a session — used by the engine when it
    lays down a plan (e.g., "Search → Filter → Synthesize → Present")."""
    session_id: str
    todos: list[str]  # list of task descriptions
    clear_existing: bool = True  # clear prior todos for this session first


@router.get("/todos", response_model=List[TodoItem])
async def get_todos(session_id: Optional[str] = Query(None)):
    """Get todo list, optionally filtered by session_id."""
    try:
        conn = _get_conn()
        if session_id:
            rows = conn.execute(
                'SELECT * FROM todos WHERE session_id = ? ORDER BY "order", created_at',
                (session_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                'SELECT * FROM todos ORDER BY "order", created_at'
            ).fetchall()
        conn.close()
        return [
            TodoItem(
                id=r["id"],
                session_id=r["session_id"],
                content=r["content"],
                completed=bool(r["completed"]),
                status=r["status"],
                priority=r["priority"],
                order=r["order"],
                timestamp=r["created_at"],
                title=r["title"] if "title" in r.keys() else None,
            )
            for r in rows
        ]
    except sqlite3.OperationalError as e:
        if "no such table" in str(e):
            return []  # migration hasn't run yet
        raise


@router.post("/todos", response_model=TodoItem)
async def create_todo(request: CreateTodoRequest):
    """Create a new todo item."""
    todo_id = str(uuid.uuid4())
    now = time.time()
    conn = _get_conn()
    # Get next order for this session
    max_order = conn.execute(
        'SELECT COALESCE(MAX("order"), -1) + 1 as next_order FROM todos WHERE session_id = ?',
        (request.session_id,),
    ).fetchone()["next_order"]
    conn.execute(
        '''INSERT INTO todos (id, session_id, content, completed, status, priority,
           "order", created_at, updated_at, title)
           VALUES (?, ?, ?, 0, ?, ?, ?, ?, ?, ?)''',
        (todo_id, request.session_id, request.content, request.status,
         request.priority, max_order, now, now, request.title),
    )
    conn.commit()
    conn.close()
    return TodoItem(
        id=todo_id,
        session_id=request.session_id,
        content=request.content,
        completed=False,
        status=request.status,
        priority=request.priority,
        order=max_order,
        timestamp=now,
        title=request.title,
    )


@router.post("/todos/batch", response_model=List[TodoItem])
async def create_todos_batch(request: CreateTodoBatchRequest):
    """Batch-create todos for a session. Used by the engine when it
    lays down a plan. Optionally clears existing todos first."""
    conn = _get_conn()
    now = time.time()
    if request.clear_existing:
        conn.execute("DELETE FROM todos WHERE session_id = ?", (request.session_id,))

    created = []
    for i, content in enumerate(request.todos):
        todo_id = str(uuid.uuid4())
        conn.execute(
            '''INSERT INTO todos (id, session_id, content, completed, status, priority, "order", created_at, updated_at)
               VALUES (?, ?, ?, 0, 'pending', 'medium', ?, ?, ?)''',
            (todo_id, request.session_id, content, i, now, now),
        )
        created.append(
            TodoItem(
                id=todo_id,
                session_id=request.session_id,
                content=content,
                completed=False,
                status="pending",
                priority="medium",
                order=i,
                timestamp=now,
                title=None,
            )
        )
    conn.commit()
    conn.close()
    return created


@router.patch("/todos/{todo_id}", response_model=TodoItem)
async def update_todo(todo_id: str, request: UpdateTodoRequest):
    """Update a todo item (mark complete, change status, etc.)."""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Todo not found")

    updates = {}
    if request.content is not None:
        updates["content"] = request.content
    if request.title is not None:
        updates["title"] = request.title
    if request.completed is not None:
        updates["completed"] = 1 if request.completed else 0
        updates["status"] = "done" if request.completed else "pending"
    if request.status is not None:
        updates["status"] = request.status
        if request.status == "done":
            updates["completed"] = 1
        elif request.status == "pending":
            updates["completed"] = 0
    updates["updated_at"] = time.time()

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [todo_id]
    conn.execute(f"UPDATE todos SET {set_clause} WHERE id = ?", values)
    conn.commit()

    row = conn.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
    conn.close()
    return TodoItem(
        id=row["id"],
        session_id=row["session_id"],
        content=row["content"],
        completed=bool(row["completed"]),
        status=row["status"],
        priority=row["priority"],
        order=row["order"],
        timestamp=row["created_at"],
        title=row["title"] if "title" in row.keys() else None,
    )


@router.delete("/todos/session/{session_id}")
async def clear_session_todos(session_id: str):
    """Clear all todos for a session (used on New Chat / session cleanup).

    NOTE: This route MUST come before /todos/{todo_id} — otherwise
    FastAPI matches 'session' as a todo_id.
    """
    conn = _get_conn()
    count = conn.execute("DELETE FROM todos WHERE session_id = ?", (session_id,)).rowcount
    conn.commit()
    conn.close()
    return {"deleted": count, "session_id": session_id}


@router.delete("/todos/{todo_id}")
async def delete_todo(todo_id: str):
    """Delete a todo item."""
    conn = _get_conn()
    conn.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
    conn.commit()
    conn.close()
    return {"deleted": todo_id}
