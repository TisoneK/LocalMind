"""Per-session workspaces.

Each session owns a folder under the LocalMind home:

    <localmind_home>/sessions/<session_id>/

The folder holds the session's artifacts (uploads today, agent default writes in
follow-ups) and is deleted when the chat/session is deleted, so deleting a
conversation removes its files too — no orphaned artifacts. The DB links by
session_id (sessions.id), so the folder name mirrors the DB key.

Session ids are client-supplied (uuid4 or caller-chosen strings), so they are
SANITIZED before touching the filesystem: path separators, drive prefixes,
parent traversal and null bytes are stripped; a fallback hash keeps the folder
stable when the id is unusable.
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
from contextvars import ContextVar
from pathlib import Path

from core.config import settings

logger = logging.getLogger(__name__)

# ── Current-session context ─────────────────
# The engine sets this once per turn (agent_runtime.process); tools read it
# to default their artifact writes into the session's workspace folder
# instead of the shared ~/LocalMind scratch. Async-safe: contextvars
# propagate through awaits within the same asyncio task, and tool path
# resolution happens in async context (write_file/resolve_write_path).
_current_session_id: ContextVar[str | None] = ContextVar(
    "localmind_current_session_id",
    default=None,
)


def set_current_session(session_id: str | None):
    """Bind the current turn's session id for tool execution; returns a token."""
    return _current_session_id.set(session_id)


def reset_current_session(token) -> None:
    """Restore the previous binding (call in a finally block)."""
    _current_session_id.reset(token)


def current_session_id() -> str | None:
    """The session id of the turn currently executing tools, if any."""
    return _current_session_id.get()

_INVALID_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def workspace_root() -> Path:
    """The directory that holds every session's workspace folder."""
    return Path(settings.localmind_home).expanduser() / "sessions"


def sanitize_session_id(session_id: str | None) -> str:
    """Return a filesystem-safe folder name for a session id.

    Strips path separators / drive prefixes / traversal / null bytes. If the
    result is empty or still unsafe, falls back to a stable sha1 hash so the
    folder is deterministic for the same id without ever escaping the root.
    """
    if not session_id:
        return hashlib.sha1(b"localmind-empty-session").hexdigest()[:16]
    cleaned = _INVALID_CHARS.sub("_", session_id).strip("._ ")
    if not cleaned or cleaned in (".", ".."):
        cleaned = ""
    if not cleaned:
        cleaned = hashlib.sha1(session_id.encode("utf-8", errors="replace")).hexdigest()[:16]
    # Absolute-path markers inside a cleaned id (e.g. a Windows drive letter
    # after subbing the colon) are impossible after the regex above, but keep
    # the belt-and-suspenders check: the folder must never be an absolute path.
    if Path(cleaned).is_absolute():
        cleaned = hashlib.sha1(session_id.encode("utf-8", errors="replace")).hexdigest()[:16]
    return cleaned


def workspace_path(session_id: str | None) -> Path:
    """The session's workspace folder (not created by this call)."""
    return workspace_root() / sanitize_session_id(session_id)


def workspace_uploads_dir(session_id: str | None) -> Path:
    """Per-session uploads folder — replaces the shared ~/LocalMind/uploads dir."""
    return workspace_path(session_id) / "uploads"


def workspace_tmp_dir(session_id: str | None) -> Path:
    """Per-session .tmp folder for intermediate/scratch agent work.

    The agent uses this for throwaway artifacts: cached search results,
    temporary reminders, intermediate processing files. The folder is
    created automatically on first use and deleted with the session.
    """
    return workspace_path(session_id) / ".tmp"


def ensure_tmp_dir(session_id: str | None) -> Path:
    """Create the session's .tmp folder (idempotent) and return its path."""
    path = workspace_tmp_dir(session_id)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception:
        logger.warning("[workspace] failed to create .tmp dir %s", path, exc_info=True)
    return path


def ensure_workspace(session_id: str | None) -> Path:
    """Create the session's workspace folder (idempotent) and return its path."""
    path = workspace_path(session_id)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception:
        logger.warning("[workspace] failed to create %s", path, exc_info=True)
    return path


def delete_workspace(session_id: str | None) -> bool:
    """Delete the session's workspace folder and everything in it.

    Only removes paths that resolve INSIDE the workspace root — a defensive
    guard so a malformed session id can never turn this into an arbitrary
    rmtree. Returns True when the folder existed and was removed.
    """
    path = workspace_path(session_id)
    try:
        resolved = path.resolve()
        root = workspace_root().resolve()
        resolved.relative_to(root)
    except Exception:
        logger.warning("[workspace] refusing to delete outside workspace root: %s", path)
        return False
    if not resolved.exists():
        return False
    try:
        shutil.rmtree(resolved)
        logger.info("[workspace] deleted %s", resolved)
        return True
    except Exception:
        logger.warning("[workspace] failed to delete %s", resolved, exc_info=True)
        return False
