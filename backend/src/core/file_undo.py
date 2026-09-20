"""Undo for a file the agent wrote.

When the agent writes a file, the text it replaced is saved here under an opaque id. The chat's
"Undo" button hands that id back and the previous content is restored. Undo only runs while the
file still holds exactly what the agent wrote: if you (or a later step) changed it since, undoing
would destroy that work, so it refuses and says why.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
from pathlib import Path

logger = logging.getLogger(__name__)

_MAX_BYTES = 2_000_000  # a huge file is not worth snapshotting for undo
_ID_ALPHABET = set("0123456789abcdef")


def _dir() -> Path:
    from core.config import settings

    d = Path(settings.localmind_home).expanduser() / "undo"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _record_path(undo_id: str) -> Path | None:
    if not undo_id or len(undo_id) != 24 or not set(undo_id) <= _ID_ALPHABET:
        return None  # ids are 24 hex chars; anything else could be a path trick
    return _dir() / f"{undo_id}.json"


def save_undo(path: str, before: str, after: str) -> str | None:
    """Remember what `path` held before the write. Returns the undo id, or None if not undoable."""
    if not path or before == after or len(before) > _MAX_BYTES or len(after) > _MAX_BYTES:
        return None
    try:
        undo_id = secrets.token_hex(12)
        rec = _record_path(undo_id)
        assert rec is not None
        # An empty "before" means the file did not exist (or was empty): undoing removes it.
        rec.write_text(
            json.dumps({"path": os.path.abspath(path), "before": before, "after": after}),
            encoding="utf-8",
        )
        return undo_id
    except Exception:
        logger.debug("[undo] could not save pre-image for %s", path, exc_info=True)
        return None


def apply_undo(undo_id: str) -> tuple[bool, str]:
    """Restore the saved content. Returns (ok, message)."""
    rec = _record_path(undo_id)
    if rec is None or not rec.exists():
        return False, "This change can no longer be undone."
    try:
        data = json.loads(rec.read_text(encoding="utf-8"))
        target = Path(data["path"])
        current = target.read_text(encoding="utf-8") if target.exists() else None
        if current is not None and current != data["after"]:
            return False, "The file has changed since, so undoing would overwrite newer work."
        if data["before"] == "":
            if target.exists():
                target.unlink()
        else:
            target.write_text(data["before"], encoding="utf-8")
        rec.unlink(missing_ok=True)
        return True, "Restored the previous version." if data["before"] else "Removed the file."
    except Exception as exc:
        logger.warning("[undo] failed: %s", exc)
        return False, "Could not undo this change."
