"""Actions endpoint - tool call history for left panel ActionHistory."""
from __future__ import annotations
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from storage.db import SessionStore
from core.config import settings

router = APIRouter()
_store = SessionStore(settings.localmind_db_path)


class ActionItem(BaseModel):
    id: str
    session_id: str
    tool_name: str
    status: str  # "running", "completed", "failed"
    input: Optional[str] = None
    output: Optional[str] = None
    duration: Optional[float] = None
    timestamp: float


class CreateActionRequest(BaseModel):
    session_id: str
    tool_name: str
    status: str = "running"
    input: Optional[str] = None


class UpdateActionRequest(BaseModel):
    status: Optional[str] = None
    output: Optional[str] = None
    duration: Optional[float] = None


@router.get("/actions", response_model=List[ActionItem])
async def get_actions(session_id: Optional[str] = Query(None)):
    """Get tool call history, optionally filtered by session_id."""
    # For now, return empty list - this would be implemented with proper storage
    # In a full implementation, this would query from an actions table
    return []


@router.post("/actions", response_model=ActionItem)
async def create_action(request: CreateActionRequest):
    """Record a new tool action."""
    # Placeholder implementation
    import time
    import uuid
    
    action = ActionItem(
        id=str(uuid.uuid4()),
        session_id=request.session_id,
        tool_name=request.tool_name,
        status=request.status,
        input=request.input,
        timestamp=time.time()
    )
    
    # In full implementation, this would save to database
    return action


@router.patch("/actions/{action_id}", response_model=ActionItem)
async def update_action(action_id: str, request: UpdateActionRequest):
    """Update action status, output, or duration."""
    # Placeholder implementation
    # In full implementation, this would update in database
    raise HTTPException(status_code=501, detail="Not implemented yet")
