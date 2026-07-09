"""
Session Store — SQLite-backed conversation history.

Schema:
    sessions(id TEXT PK, created_at REAL)
    messages(id INTEGER PK, session_id TEXT FK, role TEXT, content TEXT,
             tool_name TEXT, timestamp REAL)

No ORM — plain sqlite3 for zero extra dependencies and maximum transparency.
Migrations live in storage/migrations/ for forward compatibility.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from core.models import Message, Role

logger = logging.getLogger(__name__)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT    PRIMARY KEY,
    created_at  REAL    NOT NULL DEFAULT (unixepoch('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role        TEXT    NOT NULL CHECK(role IN ('user','assistant','system','tool')),
    content     TEXT    NOT NULL,
    tool_name   TEXT,
    timestamp   REAL    NOT NULL DEFAULT (strftime('%J', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_messages_session
ON messages(session_id, timestamp);

-- A4: Dynamic reliability tracking for tool scorer
CREATE TABLE IF NOT EXISTS tool_stats (
    tool_name       TEXT    PRIMARY KEY,
    success_count   INTEGER NOT NULL DEFAULT 0,
    failure_count   INTEGER NOT NULL DEFAULT 0,
    total_latency_ms INTEGER NOT NULL DEFAULT 0
);

-- Migration tracking
CREATE TABLE IF NOT EXISTS migration_history (
    name TEXT PRIMARY KEY
);
"""

# ── Connection pool ─────────────────────────────────────────────────────────
# v0.11 PERFORMANCE: Reuse SQLite connections instead of opening/closing
# on every operation. This saves 5-15ms per append and 10-30ms per get_history.
from queue import Empty, Queue


class _ConnectionPool:
    """Lightweight connection pool for SQLite — reuses connections."""

    def __init__(self, db_path: str, max_connections: int = 4):
        self._db_path = db_path
        self._max_connections = max_connections
        self._pool: Queue[sqlite3.Connection] = Queue(max_connections)
        self._lock = threading.Lock()

    def _create_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def get_conn(self) -> sqlite3.Connection:
        """Get a connection from the pool, creating if needed."""
        try:
            return self._pool.get_nowait()
        except Empty:
            with self._lock:
                if self._pool.qsize() < self._max_connections:
                    return self._create_connection()
                # Pool exhausted, wait for a returned connection
                return self._pool.get(timeout=5.0)

    def return_conn(self, conn: sqlite3.Connection) -> None:
        """Return connection to the pool."""
        try:
            self._pool.put_nowait(conn)
        except Exception:
            conn.close()  # Pool full, close it

# Module-level pool registry
_db_pools: dict[str, _ConnectionPool] = {}
_pools_lock = threading.Lock()

def _get_pool(db_path: str) -> _ConnectionPool:
    with _pools_lock:
        if db_path not in _db_pools:
            _db_pools[db_path] = _ConnectionPool(db_path)
        return _db_pools[db_path]


# ── Singleton store registry ────────────────────────────────────────────────
# FIX: Multiple modules (sessions.py, chat.py, engine.py) each created their
# own SessionStore(), which ran migrations independently and created duplicate
# SQLite connections. The singleton ensures one store per db_path, with
# migrations running exactly once.
_store_registry: dict[str, "SessionStore"] = {}
_registry_lock = threading.Lock()


def get_shared_store(db_path: str = "./localmind.db") -> "SessionStore":
    """Return a singleton SessionStore for the given db_path.

    This is the preferred way to obtain a SessionStore. It guarantees:
    - Migrations run exactly once per db_path per process
    - All modules share the same SQLite connection pool
    - No duplicate "Applying migration" log spam
    """
    with _registry_lock:
        if db_path not in _store_registry:
            _store_registry[db_path] = SessionStore(db_path)
        return _store_registry[db_path]


class SessionStore:
    def __init__(self, db_path: str = "./localmind.db"):
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # v0.11: Use connection pool for better performance
        self._pool = _get_pool(str(self._path))
        self._init_db()

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        """Get a connection from the pool, automatically return it on exit."""
        conn = self._pool.get_conn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.return_conn(conn)

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA)
            # Apply migrations
            self._apply_migrations(conn)
            logger.debug(f"SQLite store ready at {self._path}")

    def _apply_migrations(self, conn):
        """Apply any pending migrations from the migrations directory."""
        # Path imported at module level — no inner re-import

        migrations_dir = Path(__file__).parent / "migrations"
        migration_files = sorted(f for f in migrations_dir.glob("*.sql"))

        for migration_file in migration_files:
            migration_name = migration_file.name
            with open(migration_file, 'r') as f:
                migration_sql = f.read()
                # Check if migration already applied
                cursor = conn.execute("SELECT name FROM migration_history")
                migration_rows = cursor.fetchall()
                existing_migrations = {row[0] for row in migration_rows} if migration_rows else set()

                if migration_name not in existing_migrations:
                    logger.info(f"Applying migration: {migration_name}")
                    conn.executescript(migration_sql)
                    conn.execute("INSERT INTO migration_history (name) VALUES (?)", (migration_name,))
                    conn.commit()
                    logger.info(f"Migration {migration_name} applied successfully")

    def ensure_session(self, session_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sessions(id) VALUES(?)",
                (session_id,),
            )

    def append(self, session_id: str, message: Message) -> None:
        self.ensure_session(session_id)
        with self._conn() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO messages(session_id, role, content, tool_name, timestamp, file_name, file_path, file_size, file_type)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        message.role.value,
                        message.content,
                        message.tool_name,
                        message.timestamp or time.time(),
                        message.file_name,
                        message.file_path,
                        message.file_size,
                        message.file_type,
                    ),
                )
            except Exception as e:
                # v0.11: If migration 004 columns are missing, fall back to
                # the base schema (without file columns). This prevents total
                # history loss when the DB hasn't been migrated yet.
                if "no column named" in str(e).lower():
                    logger.warning(
                        f"[db] file columns missing — falling back to base schema. "
                        f"Run migration 004! Error: {e}"
                    )
                    conn.execute(
                        """
                        INSERT INTO messages(session_id, role, content, tool_name, timestamp)
                        VALUES(?, ?, ?, ?, ?)
                        """,
                        (
                            session_id,
                            message.role.value,
                            message.content,
                            message.tool_name,
                            message.timestamp or time.time(),
                        ),
                    )
                else:
                    raise

    def get_history(self, session_id: str, limit: int = 100) -> list[Message]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT role, content, tool_name, timestamp, file_name, file_path, file_size, file_type
                FROM messages
                WHERE session_id = ?
                ORDER BY timestamp ASC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()

        return [
            Message(
                role=Role(row["role"]),
                content=row["content"],
                tool_name=row["tool_name"],
                timestamp=row["timestamp"],
                file_name=row["file_name"] if "file_name" in row.keys() else None,
                file_path=row["file_path"] if "file_path" in row.keys() else None,
                file_size=row["file_size"] if "file_size" in row.keys() else None,
                file_type=row["file_type"] if "file_type" in row.keys() else None,
            )
            for row in rows
        ]

    def list_sessions(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT s.id, s.created_at, s.title,
                       COUNT(m.id) AS message_count,
                       MAX(m.timestamp) AS last_active,
                       (SELECT m_first.content FROM messages m_first
                         WHERE m_first.session_id = s.id AND m_first.role = 'user'
                         ORDER BY m_first.timestamp ASC LIMIT 1) AS first_message,
                       (SELECT m_last.content FROM messages m_last
                         WHERE m_last.session_id = s.id
                         ORDER BY m_last.timestamp DESC LIMIT 1) AS last_message
                FROM sessions s
                LEFT JOIN messages m ON m.session_id = s.id
                GROUP BY s.id
                ORDER BY last_active DESC
                """,
            ).fetchall()
        return [dict(row) for row in rows]

    def get_session_title(self, session_id: str) -> str | None:
        """Get current session title."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT title FROM sessions WHERE id = ?",
                (session_id,)
            ).fetchone()
            return row["title"] if row else None

    def update_session_title(self, session_id: str, title: str) -> None:
        """Update session title."""
        # FIX: ensure the session row exists before updating title.
        # Previously, if the session wasn't in the DB yet, UPDATE matched 0
        # rows and the title was silently lost.
        self.ensure_session(session_id)
        with self._conn() as conn:
            conn.execute(
                "UPDATE sessions SET title = ? WHERE id = ?",
                (title, session_id)
            )

    def delete_session(self, session_id: str) -> bool:
        with self._conn() as conn:
            result = conn.execute(
                "DELETE FROM sessions WHERE id = ?", (session_id,)
            )
        return result.rowcount > 0

    def clear_all(self) -> None:
        """Delete everything. Used in tests only."""
        with self._conn() as conn:
            conn.execute("DELETE FROM messages")
            conn.execute("DELETE FROM sessions")

    # ── A4: Tool reliability tracking ─────────────────────────────────────

    def record_tool_result(self, tool_name: str, success: bool, latency_ms: int = 0) -> None:
        """Record a tool success or failure to update dynamic reliability scores."""
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO tool_stats(tool_name, success_count, failure_count, total_latency_ms)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(tool_name) DO UPDATE SET
                    success_count    = success_count    + excluded.success_count,
                    failure_count    = failure_count    + excluded.failure_count,
                    total_latency_ms = total_latency_ms + excluded.total_latency_ms
                """,
                (
                    tool_name,
                    1 if success else 0,
                    0 if success else 1,
                    max(0, latency_ms),
                ),
            )

    def get_reliability(self) -> dict[str, float]:
        """Return reliability score (0–1) per tool based on recorded outcomes."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT tool_name, success_count, failure_count FROM tool_stats"
            ).fetchall()
        result = {}
        for row in rows:
            total = row["success_count"] + row["failure_count"]
            if total >= 5:  # only trust stats after enough samples
                result[row["tool_name"]] = row["success_count"] / total
        return result
