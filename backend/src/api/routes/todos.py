"""Todos endpoint - task management for left panel TodoList."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from core.config import settings
from storage.db import SessionStore

router = APIRouter()
_store = SessionStore(settings.localmind_db_path)


class TodoItem(BaseModel):
    id: str
    session_id: str
    content: str
    completed: bool = False
    priority: str = "medium"  # "high", "medium", "low"
    timestamp: float


class CreateTodoRequest(BaseModel):
    session_id: str
    content: str
    priority: str = "medium"


class UpdateTodoRequest(BaseModel):
    content: Optional[str] = None
    completed: Optional[bool] = None
    priority: Optional[str] = None


@router.get("/todos", response_model=List[TodoItem])
async def get_todos(session_id: Optional[str] = Query(None)):
    """Get todo list, optionally filtered by session_id."""
    # For now, return empty list - this would be implemented with proper storage
    # In a full implementation, this would query from a todos table
    return []


@router.post("/todos", response_model=TodoItem)
async def create_todo(request: CreateTodoRequest):
    """Create a new todo item."""
    # Placeholder implementation
    import time
    import uuid

    todo = TodoItem(
        id=str(uuid.uuid4()),
        session_id=request.session_id,
        content=request.content,
        priority=request.priority,
        timestamp=time.time()
    )

    # In full implementation, this would save to database
    return todo


@router.patch("/todos/{todo_id}", response_model=TodoItem)
async def update_todo(todo_id: str, request: UpdateTodoRequest):
    """Update todo item."""
    # Placeholder implementation
    # In full implementation, this would update in database
    raise HTTPException(status_code=501, detail="Not implemented yet")


@router.delete("/todos/{todo_id}")
async def delete_todo(todo_id: str):
    """Delete a todo item."""
    # Placeholder implementation
    # In full implementation, this would delete from database
    return {"deleted": todo_id}
