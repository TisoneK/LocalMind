"""Durable open questions — the outstanding clarifying question per session.

When a turn ends with the agent asking a question, that question is the
referent the user's NEXT short reply ("yes", "sure", "what about X?") is
answering. Without a record of it, the reply is re-classified from scratch:
a bare "yes" after a statement is answered as small talk, and "yes" after a
real question gets the same clarifying question asked again — the turn
interpeter never knows a question is outstanding.

The record is deliberately an AID, not a second source of truth:

- One current record per session (latest wins). A new question replaces the
  previous one; nothing is archived — the transcript is the durable record.
- It is consumed when a short reply resolves against it (the reply routes to
  the agent loop with the question rendered into context).
- It is superseded when a substantive (non-short) message arrives — the user
  answered in full or moved on, and the message itself carries the context.
- Pure social gestures ("lol", "nice", "hi") leave it untouched: the question
  they interrupted is still outstanding.

State must survive a turn ending and a process restart, so it lives in SQLite
next to the session (same discipline as ``storage.goals``): short-lived
connections, a mutation never holds a connection across a model call.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from storage.db import get_shared_store

# A record older than this is stale even if nothing superseded it — the
# question it carries can no longer be assumed to be what a short reply is
# answering. Generous by design: it only bounds ghost records after manual
# session edits, not normal flow (normal flow supersedes explicitly).
MAX_AGE_SECS = 6 * 60 * 60


@dataclass(frozen=True)
class OpenQuestion:
    session_id: str
    question: str
    asked_by_turn: str | None
    created_at: float
    updated_at: float


class OpenQuestionStore:
    """Short-lived connections — same store discipline as the goal store."""

    def __init__(self, db_path: str):
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # The shared store owns migrations (015 creates session_open_questions).
        get_shared_store(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path), timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _from_row(row: sqlite3.Row | None) -> OpenQuestion | None:
        if row is None:
            return None
        return OpenQuestion(
            session_id=row["session_id"],
            question=row["question"],
            asked_by_turn=row["asked_by_turn"],
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    def get(self, session_id: str) -> OpenQuestion | None:
        """The current open question, or None. A too-old record is cleared."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM session_open_questions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        record = self._from_row(row)
        if record is not None and (time.time() - record.updated_at) > MAX_AGE_SECS:
            self.clear(session_id)
            return None
        return record

    def record(
        self, session_id: str, question: str, asked_by_turn: str | None = None
    ) -> OpenQuestion:
        """Upsert: the session's latest outstanding question (latest wins)."""
        question = question.strip()
        if not question:
            raise ValueError("An open question needs non-empty text.")
        now = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM session_open_questions WHERE session_id = ?", (session_id,))
            conn.execute(
                """INSERT INTO session_open_questions
                   (session_id, question, asked_by_turn, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (session_id, question, asked_by_turn, now, now),
            )
            row = conn.execute(
                "SELECT * FROM session_open_questions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return self._from_row(row)  # type: ignore[return-value]

    def clear(self, session_id: str) -> bool:
        """Consume/supersede the record. True when a record was removed."""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM session_open_questions WHERE session_id = ?", (session_id,)
            )
            return cursor.rowcount > 0
