"""Durable same-session goals.

One current goal per chat session. The chat route's round driver reads it
after every turn; the model mutates it through the ``get_goal`` /
``update_goal`` tools. Goal state must survive a turn ending and a process
restart, so it lives in SQLite next to the session. The *activation* flag
(whether automatic continuation is armed) is deliberately process-local and
lives in ``core.goal_rounds`` — a restarted process never revives autonomous
work on its own.
"""

from __future__ import annotations

import functools
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from storage.db import get_shared_store

DEFAULT_MAX_GOAL_ROUNDS = 256
MAX_GOAL_ROUNDS = 256
GOAL_PHASES = ("active", "paused", "blocked", "complete")


class GoalConflictError(Exception):
    """The requested mutation is not legal for the goal's current phase."""


@dataclass(frozen=True)
class Goal:
    id: str
    session_id: str
    objective: str
    phase: str
    revision: int
    max_rounds: int
    rounds_started: int
    blocked_reason: str | None
    created_at: float
    updated_at: float


class GoalStore:
    """Short-lived connections: a goal mutation must never hold a connection
    across a model call."""

    def __init__(self, db_path: str):
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # The shared store owns migrations (013 creates session_goals).
        get_shared_store(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path), timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _from_row(row: sqlite3.Row | None) -> Goal | None:
        if row is None:
            return None
        return Goal(
            id=row["id"],
            session_id=row["session_id"],
            objective=row["objective"],
            phase=row["phase"],
            revision=int(row["revision"]),
            max_rounds=int(row["max_rounds"]),
            rounds_started=int(row["rounds_started"]),
            blocked_reason=row["blocked_reason"],
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    def get(self, session_id: str) -> Goal | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM session_goals WHERE session_id = ?", (session_id,)
            ).fetchone()
        return self._from_row(row)

    def create(
        self,
        goal_id: str,
        session_id: str,
        objective: str,
        max_rounds: int = DEFAULT_MAX_GOAL_ROUNDS,
    ) -> Goal:
        """Start a goal. An unfinished current goal must be resolved first."""
        objective = objective.strip()
        if not objective:
            raise GoalConflictError("A goal needs a non-empty objective.")
        max_rounds = _clamp_rounds(max_rounds)
        now = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute(
                "SELECT * FROM session_goals WHERE session_id = ?", (session_id,)
            ).fetchone()
            if current is not None and current["phase"] != "complete":
                conn.rollback()
                raise GoalConflictError(
                    "This session already has an unfinished goal. Edit, pause, "
                    "complete, or clear it before creating another."
                )
            if current is not None:
                conn.execute("DELETE FROM session_goals WHERE session_id = ?", (session_id,))
            conn.execute(
                """INSERT INTO session_goals
                   (id, session_id, objective, phase, revision, max_rounds,
                    rounds_started, created_at, updated_at)
                   VALUES (?, ?, ?, 'active', 1, ?, 0, ?, ?)""",
                (goal_id, session_id, objective, max_rounds, now, now),
            )
            row = conn.execute(
                "SELECT * FROM session_goals WHERE id = ?", (goal_id,)
            ).fetchone()
        return self._from_row(row)  # type: ignore[return-value]

    def edit(
        self,
        session_id: str,
        goal_id: str,
        revision: int,
        *,
        objective: str | None = None,
        max_rounds: int | None = None,
    ) -> Goal | None:
        updates: dict[str, Any] = {}
        if objective is not None and objective.strip():
            updates["objective"] = objective.strip()
        if max_rounds is not None:
            updates["max_rounds"] = _clamp_rounds(max_rounds)
        if not updates:
            return self.get(session_id)
        return self._cas(session_id, goal_id, revision, updates)

    def set_phase(
        self,
        session_id: str,
        goal_id: str,
        revision: int,
        phase: str,
        *,
        blocked_reason: str | None = None,
    ) -> Goal | None:
        if phase not in GOAL_PHASES:
            raise GoalConflictError(f"Unknown goal phase: {phase}")
        updates: dict[str, Any] = {
            "phase": phase,
            "blocked_reason": blocked_reason if phase == "blocked" else None,
        }
        return self._cas(session_id, goal_id, revision, updates)

    def resume(self, session_id: str, goal_id: str, revision: int) -> Goal | None:
        goal = self.get(session_id)
        if goal is None or goal.id != goal_id or goal.revision != revision:
            return None
        if goal.phase not in ("paused", "blocked", "active"):
            raise GoalConflictError("A completed goal cannot be resumed.")
        if goal.rounds_started >= goal.max_rounds:
            raise GoalConflictError(
                f"The round cap ({goal.max_rounds}) is exhausted. Edit the cap "
                "before resuming."
            )
        return self.set_phase(session_id, goal_id, revision, "active")

    def bump_round(self, session_id: str, goal_id: str, revision: int) -> Goal | None:
        """Atomically consume one admitted continuation round."""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """UPDATE session_goals
                   SET rounds_started = rounds_started + 1,
                       revision = revision + 1, updated_at = ?
                   WHERE id = ? AND session_id = ? AND revision = ?
                     AND phase = 'active' AND rounds_started < max_rounds""",
                (time.time(), goal_id, session_id, revision),
            )
            if conn.execute("SELECT changes()").fetchone()[0] == 0:
                conn.rollback()
                return None
            row = conn.execute(
                "SELECT * FROM session_goals WHERE id = ?", (goal_id,)
            ).fetchone()
        return self._from_row(row)

    def clear(self, session_id: str) -> bool:
        with self._connect() as conn:
            conn.execute("DELETE FROM session_goals WHERE session_id = ?", (session_id,))
            return conn.execute("SELECT changes()").fetchone()[0] > 0

    def _cas(
        self,
        session_id: str,
        goal_id: str,
        revision: int,
        updates: dict[str, Any],
    ) -> Goal | None:
        """Compare-and-set on (id, session, revision); stale refs return None."""
        updates = dict(updates)
        updates["revision"] = revision + 1
        updates["updated_at"] = time.time()
        assignments = ", ".join(f"{key} = ?" for key in updates)
        values = list(updates.values()) + [goal_id, session_id, revision]
        with self._connect() as conn:
            conn.execute(
                f"UPDATE session_goals SET {assignments} "
                "WHERE id = ? AND session_id = ? AND revision = ?",
                values,
            )
            if conn.execute("SELECT changes()").fetchone()[0] == 0:
                return None
            row = conn.execute(
                "SELECT * FROM session_goals WHERE id = ?", (goal_id,)
            ).fetchone()
        return self._from_row(row)


def _clamp_rounds(value: int) -> int:
    try:
        rounds = int(value)
    except (TypeError, ValueError):
        return DEFAULT_MAX_GOAL_ROUNDS
    return max(1, min(MAX_GOAL_ROUNDS, rounds))


@functools.lru_cache(maxsize=8)
def get_goal_store(db_path: str) -> GoalStore:
    """One GoalStore per database path per process."""
    return GoalStore(db_path)
