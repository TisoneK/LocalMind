"""Session management endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.config import settings
from storage.db import get_shared_store

router = APIRouter()

# FIX: Use the shared singleton store instead of creating a new instance.
# Previously this created its own SessionStore() which ran migrations
# independently, causing duplicate migration logs on every import.
_store = get_shared_store(settings.localmind_db_path)


class SessionListItem(BaseModel):
    id: str
    created_at: float
    message_count: int
    last_active: float | None
    title: str | None


def resolve_title(session: dict) -> str:
    """Generate fallback title if session has no title."""
    if session.get("title"):
        return session["title"]

    # Try to get first message as fallback
    if session.get("first_message"):
        return session["first_message"][:40] + ("..." if len(session["first_message"]) > 40 else "")

    return "New Chat"


@router.get("/sessions")
async def list_sessions():
    """List all conversation sessions in frontend-compatible format."""
    sessions = _store.list_sessions()

    frontend_sessions = []
    for session in sessions:
        raw_ts = session.get("last_active") or session.get("created_at") or 0
        # FIX: Provide both epoch (for backwards compat) and a human-readable
        # formatted string so the frontend never shows raw epoch numbers.
        formatted_date = ""
        if raw_ts:
            try:
                # raw_ts is epoch seconds; convert to datetime
                dt = datetime.fromtimestamp(raw_ts)
                now = datetime.now()
                if dt.date() == now.date():
                    formatted_date = dt.strftime("%H:%M")
                else:
                    formatted_date = dt.strftime("%b %d")
            except (ValueError, OSError):
                formatted_date = ""

        frontend_sessions.append(
            {
                "id": session["id"],
                "title": resolve_title(session),
                "timestamp": raw_ts,
                "formattedDate": formatted_date,
                "messageCount": session.get("message_count", 0),
                "last_message": (session.get("last_message") or "")[:120],
            }
        )

    return {"sessions": frontend_sessions}


@router.get("/sessions/{session_id}/history")
async def get_history(session_id: str):
    """Get full message history for a session in frontend-compatible format."""
    # FIX: For new sessions, return an empty history list instead of 404.
    # The frontend calls this immediately after creating a session (before the
    # first chat message), when no DB row exists yet. A 404 here causes a
    # visible error in the console and breaks the session switch animation.
    messages = _store.get_history(session_id)

    # Only 404 if the session was explicitly created but somehow has no
    # title AND no messages — an edge case that shouldn't normally happen.
    if not messages:
        title = _store.get_session_title(session_id)
        # Brand-new session: no title, no messages — return empty, not 404
        if title is None:
            return {"history": []}

    history = []

    for idx, m in enumerate(messages):
        message = {
            "id": f"{session_id}-{m.timestamp}-{idx}",
            "role": m.role.value,
            "content": m.content,
            "timestamp": m.timestamp,
        }

        # Add tool calls if present
        if m.tool_name:
            message["toolCalls"] = [
                {
                    "id": f"tool-{m.timestamp}-{idx}",
                    "name": m.tool_name,
                    "status": "completed" if m.content else "running",
                }
            ]

        # Add file results if present
        if m.file_path:
            message["fileResults"] = [
                {
                    "id": f"file-{m.timestamp}-{idx}",
                    "path": m.file_path,
                    "name": m.file_name or m.file_path.split("/")[-1],
                    "size": m.file_size or 0,
                    "type": m.file_type or "unknown",
                }
            ]

        history.append(message)

    return {"history": history}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a session and all its messages."""
    deleted = _store.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"deleted": session_id}
