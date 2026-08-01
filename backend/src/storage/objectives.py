"""SQLite persistence for user-started autonomous objectives."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from storage.db import SessionStore


@dataclass(frozen=True)
class Objective:
    id: str
    session_id: str
    prompt: str
    status: str
    priority: int
    result: str | None
    error: str | None
    approval: str | None
    resume_message: str | None
    last_event: str | None
    attempts: int
    cancel_requested: bool
    created_at: float
    updated_at: float
    started_at: float | None
    completed_at: float | None
    execution_session_id: str | None
    lease_owner: str | None


class ObjectiveStore:
    """Small transactional store for objective state.

    The existing SessionStore owns migrations and the SQLite connection pool.
    This store deliberately uses short-lived connections for objective claims so
    a worker can atomically transition queued work without holding a connection
    across an LLM call.
    """

    def __init__(self, db_path: str):
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Ensure the shared migration runner has applied migration 007.
        SessionStore(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path), timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _from_row(row: sqlite3.Row | None) -> Objective | None:
        if row is None:
            return None
        return Objective(
            id=row["id"],
            session_id=row["session_id"],
            prompt=row["prompt"],
            status=row["status"],
            priority=int(row["priority"]),
            result=row["result"],
            error=row["error"],
            approval=row["approval"],
            resume_message=row["resume_message"],
            last_event=row["last_event"],
            attempts=int(row["attempts"]),
            cancel_requested=bool(row["cancel_requested"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            execution_session_id=row["execution_session_id"],
            lease_owner=row["lease_owner"],
        )

    def create(
        self,
        objective_id: str,
        session_id: str,
        prompt: str,
        priority: int = 0,
        execution_session_id: str | None = None,
    ) -> Objective:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO objectives
                   (id, session_id, prompt, status, priority, created_at, updated_at,
                    execution_session_id)
                   VALUES (?, ?, ?, 'queued', ?, ?, ?, ?)""",
                (
                    objective_id,
                    session_id,
                    prompt,
                    priority,
                    now,
                    now,
                    execution_session_id or f"objective-{objective_id}",
                ),
            )
            row = conn.execute("SELECT * FROM objectives WHERE id = ?", (objective_id,)).fetchone()
        return self._from_row(row)  # type: ignore[return-value]

    def get(self, objective_id: str) -> Objective | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM objectives WHERE id = ?", (objective_id,)).fetchone()
        return self._from_row(row)

    def list(self, session_id: str | None = None) -> list[Objective]:
        with self._connect() as conn:
            if session_id:
                rows = conn.execute(
                    "SELECT * FROM objectives WHERE session_id = ? ORDER BY created_at DESC",
                    (session_id,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM objectives ORDER BY created_at DESC").fetchall()
        return [self._from_row(row) for row in rows if row is not None]

    def claim_next(self, lease_seconds: float = 300.0, lease_owner: str = "default") -> Objective | None:
        """Atomically claim the next queued objective, recovering expired work."""
        now = time.time()
        lease_until = now + lease_seconds
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT * FROM objectives
                   WHERE (status = 'queued' AND cancel_requested = 0)
                      OR (status = 'running' AND lease_until IS NOT NULL AND lease_until < ?)
                   ORDER BY priority DESC, created_at ASC
                   LIMIT 1""",
                (now,),
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            conn.execute(
                """UPDATE objectives
                   SET status = 'running', attempts = attempts + 1,
                       updated_at = ?, started_at = COALESCE(started_at, ?),
                       lease_until = ?, lease_owner = ?, error = NULL,
                       cancel_requested = 0
                   WHERE id = ?""",
                (now, now, lease_until, lease_owner, row["id"]),
            )
            claimed = conn.execute("SELECT * FROM objectives WHERE id = ?", (row["id"],)).fetchone()
        return self._from_row(claimed)

    def update(self, objective_id: str, **fields: Any) -> Objective | None:
        allowed = {
            "status",
            "result",
            "error",
            "approval",
            "resume_message",
            "last_event",
            "cancel_requested",
            "completed_at",
            "lease_until",
            "execution_session_id",
            "lease_owner",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return self.get(objective_id)
        updates["updated_at"] = time.time()
        assignments = ", ".join(f"{key} = ?" for key in updates)
        values = list(updates.values()) + [objective_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE objectives SET {assignments} WHERE id = ?", values)
            row = conn.execute("SELECT * FROM objectives WHERE id = ?", (objective_id,)).fetchone()
        return self._from_row(row)

    def update_owned(self, objective_id: str, lease_owner: str, **fields: Any) -> Objective | None:
        """Update only while this worker still owns a running claim."""
        allowed = {
            "status",
            "result",
            "error",
            "approval",
            "resume_message",
            "last_event",
            "cancel_requested",
            "completed_at",
            "lease_until",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return self.get(objective_id)
        updates["updated_at"] = time.time()
        assignments = ", ".join(f"{key} = ?" for key in updates)
        values = list(updates.values()) + [objective_id, lease_owner]
        with self._connect() as conn:
            conn.execute(
                f"UPDATE objectives SET {assignments} "
                "WHERE id = ? AND status = 'running' AND lease_owner = ?",
                values,
            )
            row = conn.execute("SELECT * FROM objectives WHERE id = ?", (objective_id,)).fetchone()
        return self._from_row(row)

    def request_cancel(self, objective_id: str) -> Objective | None:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """UPDATE objectives
                   SET status = 'canceled', cancel_requested = 1,
                       lease_until = NULL, updated_at = ?
                   WHERE id = ? AND status NOT IN ('completed', 'failed', 'canceled')""",
                (now, objective_id),
            )
            row = conn.execute("SELECT * FROM objectives WHERE id = ?", (objective_id,)).fetchone()
        return self._from_row(row)

    def pause(self, objective_id: str) -> Objective | None:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """UPDATE objectives
                   SET status = 'paused', lease_until = NULL, updated_at = ?
                   WHERE id = ? AND status IN ('queued', 'running', 'blocked')""",
                (now, objective_id),
            )
            row = conn.execute("SELECT * FROM objectives WHERE id = ?", (objective_id,)).fetchone()
        return self._from_row(row)

    def resume(self, objective_id: str, message: str | None = None) -> Objective | None:
        return self.update(
            objective_id,
            status="queued",
            approval=None,
            resume_message=message,
            error=None,
            cancel_requested=0,
            lease_until=None,
        )
