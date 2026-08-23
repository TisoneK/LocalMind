"""Session management endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.config import settings
from core.error_normalizer import normalize_error
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


def _agent_written_paths(tool_calls) -> list[str]:
    """Recover file paths the agent wrote from the persisted tool timeline.

    B-2026-08-23-3: the live `done` SSE carries the last written path but the
    stored message only kept user-attached files. The tool-call timeline is
    the durable record — file_write tool_args are "path:\n\ncontent" and
    edit_file/propose_write_file tool_args are JSON with a "path" key. Dedupes
    while preserving order."""
    import json as _json

    paths: list[str] = []
    if not tool_calls:
        return paths
    for tc in tool_calls:
        if not isinstance(tc, dict):
            continue
        name = str(tc.get("name") or tc.get("tool") or "")
        if name not in ("file_write", "edit_file", "propose_write_file"):
            continue
        raw_args = tc.get("tool_args") or tc.get("input") or ""
        if not isinstance(raw_args, str) or not raw_args.strip():
            continue
        path = None
        if name == "file_write":
            # tool_args are "path:\n\ncontent" — drop the trailing colon.
            head = raw_args.split("\n\n", 1)[0].strip()
            if head:
                path = head.rstrip(":").strip()
        else:
            try:
                parsed = _json.loads(raw_args)
                if isinstance(parsed, dict) and parsed.get("path"):
                    path = str(parsed["path"]).strip()
            except Exception:
                path = None
        if path and path not in paths:
            paths.append(path)
    return paths


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

        # B-2026-08-23-17: expose the session's artifact folder so the UI
        # (Files tab, previews) can point at where this session's files live.
        try:
            from core.session_workspace import workspace_path

            workspace = str(workspace_path(session["id"]))
        except Exception:
            workspace = ""

        frontend_sessions.append(
            {
                "id": session["id"],
                "title": resolve_title(session),
                "timestamp": raw_ts,
                "formattedDate": formatted_date,
                "messageCount": session.get("message_count", 0),
                "last_message": (session.get("last_message") or "")[:120],
                "workspacePath": workspace,
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

        # Session 266: restore the per-turn artifacts the frontend showed live
        # (thinking block, error card, tool-step pills, per-turn metrics). They
        # are persisted with the assistant message and must survive a reload.
        if m.thinking:
            message["thinking"] = m.thinking
        # Session 290: the ADR-36 opening acknowledgement line.
        if getattr(m, "acknowledgement", None):
            message["acknowledgement"] = m.acknowledgement
        if m.error:
            # ADR-20: normalize ONCE at the presentation boundary — the stored
            # raw string becomes the canonical object the frontend renders.
            message["error"] = normalize_error(m.error)
        if m.tool_calls:
            message["toolCalls"] = m.tool_calls
        if m.metrics:
            metrics = m.metrics
            latency_ms = metrics.get("latency_ms") or 0
            completion = metrics.get("completion_tokens") or 0
            message["performance"] = {
                "latencyMs": latency_ms or None,
                "promptTokens": metrics.get("prompt_tokens") or None,
                "completionTokens": completion or None,
                "tokensPerSecond": (
                    round(completion / (latency_ms / 1000.0), 2)
                    if latency_ms > 0 and completion > 0
                    else None
                ),
            }
        # Session 267: restore the Agent Workspace run tree + phase strip
        # (frontend AgentRun[] / AgentPhase[] shapes — already camelCase).
        if m.agent_runs:
            message["agentRuns"] = m.agent_runs
        if m.agent_phases:
            message["agentPhases"] = m.agent_phases

        # Add tool calls if present
        if m.tool_name and not m.tool_calls:
            message["toolCalls"] = [
                {
                    "id": f"tool-{m.timestamp}-{idx}",
                    "name": m.tool_name,
                    "status": "completed" if m.content else "running",
                }
            ]

        # Add file results if present — both the user's attached files AND
        # (B-2026-08-23-3) the files the agent wrote during the turn. The
        # agent-written paths are recovered from the persisted tool-call
        # timeline: file_write tool_args are "path:\n\ncontent" and edit_file
        # tool_args are JSON with a "path" key. This keeps the export (and a
        # reload) able to show which files the session created.
        file_results = []
        if m.file_path:
            file_results.append(
                {
                    "id": f"file-{m.timestamp}-{idx}",
                    "path": m.file_path,
                    "name": m.file_name or m.file_path.split("/")[-1],
                    "size": m.file_size or 0,
                    "type": m.file_type or "unknown",
                }
            )
        written_paths = _agent_written_paths(m.tool_calls)
        for _wp in written_paths:
            file_results.append(
                {
                    "id": f"file-written-{m.timestamp}-{_wp.replace('/', '_')}",
                    "path": _wp,
                    "name": _wp.split("/")[-1],
                    "type": "written",
                }
            )
        if file_results:
            message["fileResults"] = file_results

        history.append(message)

    return {"history": history}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a session and all its messages.

    Session 26: also clean up engine state (intent history, pending
    writes, pending clarifications, cached code, observations) to
    prevent unbounded memory growth and state leaks across sessions.
    """
    deleted = _store.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")

    # B-2026-08-23-17: deleting a chat deletes its artifacts — the session's
    # workspace folder under <localmind_home>/sessions/<id> (uploads + agent
    # files) goes with the DB row. Non-fatal: the DB deletion already happened.
    try:
        from core.session_workspace import delete_workspace

        delete_workspace(session_id)
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning(
            "[sessions] workspace cleanup failed for %s: %s", session_id[:8], e
        )

    # Session 26: clean up engine per-session state dicts
    try:
        from api.routes.chat import _engine

        _engine.cleanup_session(session_id)
    except Exception as e:
        # Non-fatal — the session is already deleted from the store.
        # Log but don't fail the request.
        import logging

        logging.getLogger(__name__).warning(
            "[sessions] engine cleanup failed for %s: %s", session_id[:8], e
        )

    return {"deleted": session_id}
