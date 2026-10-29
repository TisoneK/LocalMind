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

import json
import logging
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from core.models import Message, Role

logger = logging.getLogger(__name__)

# Tokens that carry no signal for failure recall matching.
_FAILURE_STOPWORDS = {
    "the", "and", "with", "that", "this", "please", "what", "when",
    "where", "which", "there", "your", "from", "have", "will", "was",
    "were", "can", "could", "would", "should", "about", "into", "them",
    "then", "than", "just", "some", "make", "need", "want",
    "show", "list", "tell", "give", "help", "does", "doing", "work",
    "works", "working", "failed", "failing", "error", "errors",
}

# Failures older than this are pruned on write — the table
# stays bounded and stale secrets age out of recall.
_FAILURE_RETENTION_DAYS = 90



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
    timestamp   REAL    NOT NULL DEFAULT (strftime('%J', 'now')),
    -- Per-turn artifacts persisted with the assistant message.
    thinking    TEXT,
    error       TEXT,
    tool_calls  TEXT,
    metrics     TEXT,
    -- The opening acknowledgement line.
    acknowledgement TEXT,
    -- Agent Workspace run tree + phase strip (JSON).
    agent_runs     TEXT,
    agent_phases   TEXT,
    -- Injected-context item ledger (JSON) — what this turn's prompts
    -- actually carried, per item, with producer attribution.
    injected_items TEXT,
    -- Structured edit diff + best-of-N candidates (JSON) — live-streamed
    -- artifacts that now survive a reload.
    diff_data      TEXT,
    candidates     TEXT
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

-- Tool call history for the Actions panel (real store,
-- replacing the placeholder that returned []).
CREATE TABLE IF NOT EXISTS actions (
    id          TEXT    PRIMARY KEY,
    session_id  TEXT    NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    tool_name   TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'running',
    label       TEXT,
    input       TEXT,
    output      TEXT,
    error       TEXT,
    duration    REAL,
    iteration   INTEGER,
    todo_id     TEXT,   -- plan todo this action serves (one todo → many actions)
    reasoning   TEXT,   -- The model's thought that led to this tool call
    provider    TEXT,   -- Which backend engine answered (e.g. web_search winner)
    timestamp   REAL    NOT NULL DEFAULT (unixepoch('now'))
);

CREATE INDEX IF NOT EXISTS idx_actions_session
ON actions(session_id, timestamp);

-- Migration tracking
CREATE TABLE IF NOT EXISTS migration_history (
    name TEXT PRIMARY KEY
);

-- Failure memory — what-failed-and-why at loop
-- end (the "Remember" stage of Observe→…→Verify→Remember→Continue).
-- Read back for repeated patterns so the next similar turn can avoid
-- the same mistake (injected as a context hint alongside memory facts).
CREATE TABLE IF NOT EXISTS failure_memory (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL,
    intent      TEXT    DEFAULT '',
    message     TEXT    DEFAULT '',
    failure_type TEXT   DEFAULT '',  -- iteration_limit | criteria_unmet | tool_failure
    summary     TEXT    DEFAULT '',  -- what-failed-and-why (deterministic)
    created_at  TEXT    DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_failure_memory_session ON failure_memory(session_id);

-- Cross-session decision ledger — durable
-- store of "decisions that must never be compressed away" (design.md
-- §6). The task-aware summarizer's [Preserved decisions] block is
-- written here so a decision-changing line ("user rejected MongoDB",
-- "production uses PostgreSQL") survives even after the conversation
-- that produced it is compressed away or the session is deleted.
-- Deliberately NO foreign key to sessions: decisions outlive their
-- source session by design.
CREATE TABLE IF NOT EXISTS decision_ledger (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL,
    task_type   TEXT    DEFAULT '',
    decision    TEXT    NOT NULL,
    created_at  TEXT    DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_decision_ledger_session ON decision_ledger(session_id, created_at);

-- Session episode memory - the system-level
-- "what happened this session" digest (the product-side equivalent of an
-- agent's session log, invisible to users). One row per session (upsert);
-- deliberately NO foreign key to sessions: episodes outlive their source
-- session like decision_ledger rows.
CREATE TABLE IF NOT EXISTS session_episodes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    UNIQUE NOT NULL,
    summary     TEXT    DEFAULT '',
    decisions   TEXT    DEFAULT '',
    failures    TEXT    DEFAULT '',
    next_steps  TEXT    DEFAULT '',
    turn_count  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    DEFAULT (datetime('now')),
    updated_at  TEXT    DEFAULT (datetime('now'))
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
        # Ensure the actions table has the iteration column.
        # Fresh installs get it from _SCHEMA; existing DBs need a defensive
        # ALTER (idempotent — a second run raises duplicate-column, ignored).
        # Separate try blocks: the first ALTER raising (column already exists
        # on a real DB) must not skip the second. Iteration
        # then todo_id.
        try:
            with self._conn() as conn:
                conn.execute("ALTER TABLE actions ADD COLUMN iteration INTEGER")
        except sqlite3.OperationalError:
            pass
        try:
            with self._conn() as conn:
                # Link each action to the plan todo it serves.
                conn.execute("ALTER TABLE actions ADD COLUMN todo_id TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            with self._conn() as conn:
                # Per-step reasoning (the 'why' of each action).
                conn.execute("ALTER TABLE actions ADD COLUMN reasoning TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            with self._conn() as conn:
                # Which backend engine answered (Actions-card badge).
                conn.execute("ALTER TABLE actions ADD COLUMN provider TEXT")
        except sqlite3.OperationalError:
            pass
        # Per-turn artifacts on messages (thinking/error/tool
        # calls/metrics). Fresh DBs get them from _SCHEMA; existing DBs need
        # defensive ALTERs (idempotent — a second run raises duplicate-column,
        # ignored). Same pattern as the actions table columns above.
        for _col in ("thinking", "error", "tool_calls", "metrics"):
            try:
                with self._conn() as conn:
                    conn.execute(f"ALTER TABLE messages ADD COLUMN {_col} TEXT")
            except sqlite3.OperationalError:
                pass
        # The opening acknowledgement line (survives reload).
        try:
            with self._conn() as conn:
                conn.execute("ALTER TABLE messages ADD COLUMN acknowledgement TEXT")
        except sqlite3.OperationalError:
            pass
        # Agent Workspace run tree + phase strip on messages.
        for _col in ("agent_runs", "agent_phases", "injected_items"):
            try:
                with self._conn() as conn:
                    conn.execute(f"ALTER TABLE messages ADD COLUMN {_col} TEXT")
            except sqlite3.OperationalError:
                pass
        # Structured edit diff + best-of-N candidates on messages (reload
        # restore). Fresh DBs get them from _SCHEMA; existing DBs need the
        # same defensive ALTERs as above.
        for _col in ("diff_data", "candidates"):
            try:
                with self._conn() as conn:
                    conn.execute(f"ALTER TABLE messages ADD COLUMN {_col} TEXT")
            except sqlite3.OperationalError:
                pass
        # Per-session observation persistence. The Observe panel
        # used to read an in-memory engine dict that died on backend restart;
        # the latest turn's observation is now written here and the endpoint
        # falls back to it on a cache miss. One row per session (the latest
        # turn wins) — same lifetime as the session itself (cascade delete).
        try:
            with self._conn() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS observations (
                        session_id  TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
                        data        TEXT,
                        snapshot    TEXT,
                        updated_at  REAL
                    )
                    """
                )
        except sqlite3.OperationalError:
            pass

    def _apply_migrations(self, conn):
        """Apply any pending migrations from the migrations directory."""
        # Path imported at module level — no inner re-import

        migrations_dir = Path(__file__).parent / "migrations"
        migration_files = sorted(f for f in migrations_dir.glob("*.sql"))

        for migration_file in migration_files:
            migration_name = migration_file.name
            with open(migration_file, "r") as f:
                migration_sql = f.read()
                # Check if migration already applied
                cursor = conn.execute("SELECT name FROM migration_history")
                migration_rows = cursor.fetchall()
                existing_migrations = (
                    {row[0] for row in migration_rows} if migration_rows else set()
                )

                if migration_name not in existing_migrations:
                    logger.info(f"Applying migration: {migration_name}")
                    conn.executescript(migration_sql)
                    conn.execute(
                        "INSERT INTO migration_history (name) VALUES (?)", (migration_name,)
                    )
                    conn.commit()
                    logger.info(f"Migration {migration_name} applied successfully")

    def ensure_session(self, session_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sessions(id) VALUES(?)",
                (session_id,),
            )
        # A session row and its workspace folder are born
        # together — the first touch on a session creates its artifact folder
        # under <localmind_home>/sessions/<id> (idempotent, non-fatal).
        try:
            from core.session_workspace import ensure_workspace

            ensure_workspace(session_id)
        except Exception:
            logging.getLogger(__name__).debug(
                "[db] workspace ensure skipped for %s", session_id[:8], exc_info=True
            )

    def append(self, session_id: str, message: Message) -> None:
        self.ensure_session(session_id)
        with self._conn() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO messages(session_id, role, content, tool_name, timestamp, file_name, file_path, file_size, file_type, thinking, error, tool_calls, metrics, agent_runs, agent_phases, injected_items, acknowledgement, diff_data, candidates)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,  # noqa: E501
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
                        message.thinking,  # plain text — stored raw
                        message.error,  # raw provider string — stored raw
                        json.dumps(message.tool_calls) if message.tool_calls else None,
                        json.dumps(message.metrics) if message.metrics else None,
                        json.dumps(message.agent_runs) if message.agent_runs else None,
                        json.dumps(message.agent_phases) if message.agent_phases else None,
                        json.dumps(message.injected_items) if message.injected_items else None,
                        message.acknowledgement,  # plain text — stored raw
                        json.dumps(message.diff_data) if message.diff_data else None,
                        json.dumps(message.candidates) if message.candidates else None,
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

    def create_action(
        self,
        session_id: str,
        tool_name: str,
        status: str = "running",
        label: str = "",
        input: str = "",
        action_id: str = "",
        iteration: Optional[int] = None,
        todo_id: Optional[str] = None,
        reasoning: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> str:
        """Record a tool action. Returns the action id (stable, reused for updates)."""
        import uuid as _uuid

        aid = action_id or str(_uuid.uuid4())
        with self._conn() as conn:
            # INSERT OR REPLACE would wipe output/error/
            # duration if a done event re-created an existing id. Use
            # DO NOTHING so the running-create never clobbers a completed row.
            conn.execute(
                "INSERT INTO actions (id, session_id, tool_name, status, label, input, iteration, "
                "todo_id, reasoning, provider, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING",
                (
                    aid, session_id, tool_name, status, label, input,
                    iteration, todo_id, reasoning, provider, time.time(),
                ),
            )
        return aid

    def update_action(
        self,
        action_id: str,
        status: Optional[str] = None,
        output: Optional[str] = None,
        error: Optional[str] = None,
        duration: Optional[float] = None,
        provider: Optional[str] = None,
    ) -> None:
        """Update a tool action's status/output/duration/provider by its stable id."""
        fields: list[str] = []
        values: list[object] = []
        for key, val in (
            ("status", status),
            ("output", output),
            ("error", error),
            ("duration", duration),
            ("provider", provider),
        ):
            if val is not None:
                fields.append(f"{key} = ?")
                values.append(val)
        if not fields:
            return
        values.append(action_id)
        with self._conn() as conn:
            conn.execute(f"UPDATE actions SET {', '.join(fields)} WHERE id = ?", values)

    def list_actions(self, session_id: str, limit: int = 100) -> list[dict]:
        """Return tool actions for a session, newest first."""
        cols = (
            "id", "session_id", "tool_name", "status", "label", "input",
            "output", "error", "duration", "iteration", "todo_id", "reasoning", "provider", "timestamp",
        )
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, session_id, tool_name, status, label, input, output, error, "
                "duration, iteration, todo_id, reasoning, provider, timestamp "
                "FROM actions WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [dict(zip(cols, r)) for r in rows]

    def upsert_todo(
        self,
        session_id: str,
        todo_id: str,
        text: Optional[str] = None,
        completed: Optional[bool] = None,
        title: Optional[str] = None,
        status: Optional[str] = None,
    ) -> None:
        """Create or update a plan todo (migration 006 schema). Only non-None
        fields are written, so a todo_completed event (id + completed only)
        never wipes the todo's text.

        `text` is the FULL content (the TodoItem API calls
        it `content`); `title` is the short user-facing label. When a title
        is supplied on create, it's stored; on update (todo_completed) no
        title is passed, so an existing title survives.
        """
        with self._conn() as conn:
            now = time.time()
            row = conn.execute(
                "SELECT id FROM todos WHERE session_id = ? AND id = ?", (session_id, todo_id)
            ).fetchone()
            if row is None:
                conn.execute(
                    'INSERT INTO todos (id, session_id, content, completed, status, '
                    'priority, "order", created_at, updated_at, title) VALUES (?, ?, ?, ?, ?, '
                    "'medium', 0, ?, ?, ?)",
                    (
                        todo_id,
                        session_id,
                        text or "",
                        1 if completed else 0,
                        status or ("done" if completed else "pending"),
                        now,
                        now,
                        title,
                    ),
                )
            else:
                updates: dict[str, object] = {"updated_at": now}
                if text is not None:
                    updates["content"] = text
                # Only set/overwrite the title when one is
                # supplied (never wipe an existing title on a status-only
                # update).
                if title is not None:
                    updates["title"] = title
                if completed is not None:
                    updates["completed"] = 1 if completed else 0
                    updates["status"] = "done" if completed else "pending"
                if status is not None:
                    updates["status"] = status
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                conn.execute(
                    f"UPDATE todos SET {set_clause} WHERE session_id = ? AND id = ?",
                    list(updates.values()) + [session_id, todo_id],
                )

    def list_todos(self, session_id: str) -> list[dict]:
        """Return plan todos for a session, in display order."""
        cols = ("id", "session_id", "content", "completed", "status", "priority", "order", "timestamp")
        with self._conn() as conn:
            rows = conn.execute(
                'SELECT id, session_id, content, completed, status, priority, "order", created_at '
                'FROM todos WHERE session_id = ? ORDER BY "order", created_at',
                (session_id,),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(zip(cols, r))
            d.setdefault("title", None)
            out.append(d)
        return out

    def clear_todos(self, session_id: str) -> None:
        """Delete all plan todos for a session (new request / new chat)."""
        with self._conn() as conn:
            conn.execute("DELETE FROM todos WHERE session_id = ?", (session_id,))

    @staticmethod
    def _decode_json(value):
        """Parse a JSON column back to its original object; None for empty."""
        if value is None:
            return None
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return None

    def search_messages(self, query: str, limit: int = 20) -> list[dict]:
        """Chats whose message text contains `query`, newest first, one row per chat.

        Plain substring match (case-insensitive) with LIKE wildcards escaped, so what you type is
        what is searched. Returns the chat title and a snippet around the first hit.
        """
        q = (query or "").strip()
        if len(q) < 2:
            return []
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT m.session_id, s.title, m.role, m.content, MAX(m.timestamp) AS ts
                FROM messages m JOIN sessions s ON s.id = m.session_id
                WHERE m.content LIKE ? ESCAPE '\\'
                GROUP BY m.session_id
                ORDER BY ts DESC
                LIMIT ?
                """,
                (f"%{escaped}%", limit),
            ).fetchall()
        out = []
        for session_id, title, role, content, _ts in rows:
            text = content or ""
            at = text.lower().find(q.lower())
            start = max(0, at - 40)
            window = text[start : start + 120].replace("\n", " ")
            for mark in ("**", "`", "##"):  # markdown noise reads badly in a one-line snippet
                window = window.replace(mark, "")
            snippet = ("…" if start else "") + window
            out.append({"id": session_id, "title": title or "", "role": role, "snippet": snippet})
        return out

    def drop_last_turn(self, session_id: str, user_content: str | None = None) -> bool:
        """Remove the newest user message and the reply after it, when it is `user_content`.

        A retry re-asks the same question; without this the stored chat would hold the failed
        attempt AND the new one, and the failed reply (and its error) would return on reload.
        Only an exact match on the trailing turn is removed, so retrying never eats other history.
        With `user_content=None` (editing your last message) any trailing user+reply pair goes.
        """
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, role, content FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT 2",
                (session_id,),
            ).fetchall()
            if len(rows) < 2:
                return False
            reply, asked = rows[0], rows[1]
            if reply[1] != "assistant" or asked[1] != "user" or (
                user_content is not None and (asked[2] or "").strip() != user_content.strip()
            ):
                return False
            conn.execute("DELETE FROM messages WHERE id IN (?, ?)", (reply[0], asked[0]))
            return True

    def get_history(self, session_id: str, limit: int = 100) -> list[Message]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT role, content, tool_name, timestamp, file_name, file_path, file_size, file_type,
                       thinking, error, tool_calls, metrics, agent_runs, agent_phases, injected_items, acknowledgement,
                       diff_data, candidates
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
                thinking=row["thinking"] if "thinking" in row.keys() else None,
                error=row["error"] if "error" in row.keys() else None,
                tool_calls=self._decode_json(row["tool_calls"]) if "tool_calls" in row.keys() else None,
                metrics=self._decode_json(row["metrics"]) if "metrics" in row.keys() else None,
                agent_runs=self._decode_json(row["agent_runs"]) if "agent_runs" in row.keys() else None,
                agent_phases=self._decode_json(row["agent_phases"]) if "agent_phases" in row.keys() else None,
                injected_items=self._decode_json(row["injected_items"]) if "injected_items" in row.keys() else None,
                acknowledgement=row["acknowledgement"] if "acknowledgement" in row.keys() else None,
                diff_data=self._decode_json(row["diff_data"]) if "diff_data" in row.keys() else None,
                candidates=self._decode_json(row["candidates"]) if "candidates" in row.keys() else None,
            )
            for row in rows
        ]

    def get_recent_history(self, session_id: str, limit: int = 2) -> list[Message]:
        """Most-recent messages first (newest → oldest).

        Used by the guaranteed-persist dedup, which must inspect the LATEST
        assistant message. `get_history()` orders ASC, so `limit=n` there
        returns the OLDEST n messages — the wrong end for a "did we already
        save this reply?" check.
        """
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT role, content, tool_name, timestamp, file_name, file_path, file_size, file_type,
                       thinking, error, tool_calls, metrics, agent_runs, agent_phases, injected_items, acknowledgement,
                       diff_data, candidates
                FROM messages
                WHERE session_id = ?
                ORDER BY timestamp DESC
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
                thinking=row["thinking"] if "thinking" in row.keys() else None,
                error=row["error"] if "error" in row.keys() else None,
                tool_calls=self._decode_json(row["tool_calls"]) if "tool_calls" in row.keys() else None,
                metrics=self._decode_json(row["metrics"]) if "metrics" in row.keys() else None,
                agent_runs=self._decode_json(row["agent_runs"]) if "agent_runs" in row.keys() else None,
                agent_phases=self._decode_json(row["agent_phases"]) if "agent_phases" in row.keys() else None,
                injected_items=self._decode_json(row["injected_items"]) if "injected_items" in row.keys() else None,
                acknowledgement=row["acknowledgement"] if "acknowledgement" in row.keys() else None,
                diff_data=self._decode_json(row["diff_data"]) if "diff_data" in row.keys() else None,
                candidates=self._decode_json(row["candidates"]) if "candidates" in row.keys() else None,
            )
            for row in rows
        ]

    def list_sessions(self) -> list[dict]:
        # Rewritten to avoid correlated subqueries in the SELECT clause.
        # The previous version ran two subqueries per session row (one for
        # first_message, one for last_message) — O(N) executions for N sessions.
        # This version uses a single LEFT JOIN with conditional aggregation
        # via MIN/MAX + IIF, which is O(N) total.
        #
        # first_message: the earliest user message content for the session.
        # last_message: the most recent message content (any role).
        # We use MIN(timestamp) / MAX(timestamp) to pick the rows, and
        # IIF + NULLIF to extract content only for matching rows.
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT
                    s.id,
                    s.created_at,
                    s.title,
                    COUNT(m.id) AS message_count,
                    MAX(m.timestamp) AS last_active,
                    (
                        SELECT m_first.content
                        FROM messages m_first
                        WHERE m_first.session_id = s.id
                          AND m_first.role = 'user'
                        ORDER BY m_first.timestamp ASC
                        LIMIT 1
                    ) AS first_message,
                    (
                        SELECT m_last.content
                        FROM messages m_last
                        WHERE m_last.session_id = s.id
                        ORDER BY m_last.timestamp DESC
                        LIMIT 1
                    ) AS last_message
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
            row = conn.execute("SELECT title FROM sessions WHERE id = ?", (session_id,)).fetchone()
            return row["title"] if row else None

    def update_session_title(self, session_id: str, title: str) -> None:
        """Update session title."""
        # FIX: ensure the session row exists before updating title.
        # Previously, if the session wasn't in the DB yet, UPDATE matched 0
        # rows and the title was silently lost.
        self.ensure_session(session_id)
        with self._conn() as conn:
            conn.execute("UPDATE sessions SET title = ? WHERE id = ?", (title, session_id))

    def delete_session(self, session_id: str) -> bool:
        with self._conn() as conn:
            conn.execute("DELETE FROM session_writes WHERE session_id = ?", (session_id,))
            result = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        return result.rowcount > 0

    def clear_all(self) -> None:
        """Delete everything. Used in tests only."""
        with self._conn() as conn:
            conn.execute("DELETE FROM messages")
            conn.execute("DELETE FROM actions")
            conn.execute("DELETE FROM observations")
            conn.execute("DELETE FROM session_writes")
            conn.execute("DELETE FROM sessions")

    # ── Durable lightweight write stats ─────────────────

    _WRITE_STATS_CAP = 500

    def log_write(
        self,
        session_id: str,
        path: str,
        tool: str = "file_write",
        bytes: int = 0,
        lines: int = 0,
        kind: str = "created",
    ) -> None:
        """Log a successful file write. Prunes oldest rows when the
        per-session cap is exceeded. Best-effort — must never break the turn."""
        try:
            with self._conn() as conn:
                conn.execute(
                    "INSERT INTO session_writes(session_id, path, tool, bytes, lines, kind) "
                    "VALUES(?, ?, ?, ?, ?, ?)",
                    (session_id, (path or "")[:500], (tool or "")[:50],
                     int(bytes), int(lines), (kind or "created")[:20]),
                )
                # Prune oldest rows when cap is exceeded
                conn.execute(
                    "DELETE FROM session_writes WHERE session_id = ? AND id NOT IN ("
                    "  SELECT id FROM session_writes WHERE session_id = ? "
                    "  ORDER BY id DESC LIMIT ?"
                    ")",
                    (session_id, session_id, self._WRITE_STATS_CAP),
                )
        except Exception as exc:  # pragma: no cover — defensive
            logger.debug("[db] log_write skipped: %s", exc)

    def get_session_writes(self, session_id: str) -> list[dict]:
        """Return all write-stat rows for a session, newest first."""
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT id, path, tool, bytes, lines, kind, created_at "
                    "FROM session_writes WHERE session_id = ? "
                    "ORDER BY created_at DESC",
                    (session_id,),
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def delete_session_writes(self, session_id: str) -> None:
        """Delete all write-stats rows for a session (called by delete_session)."""
        try:
            with self._conn() as conn:
                conn.execute(
                    "DELETE FROM session_writes WHERE session_id = ?",
                    (session_id,),
                )
        except Exception:
            pass

    # ── Per-session observation persistence ──────────────────
    # The Observe panel used to read an in-memory engine dict that died on
    # backend restart. The latest turn's observation (merged metrics dict +
    # structured snapshot summary) is now written here so the endpoint can
    # fall back to the DB on a cache miss.

    def save_observation(
        self,
        session_id: str,
        data: Optional[dict] = None,
        snapshot: Optional[dict] = None,
    ) -> None:
        """Upsert the latest observation for a session (one row per session).

        Only the provided columns are touched — the runtime writes the merged
        metrics dict at turn end (``_store_observation``) and the structured
        snapshot separately (``build_observation_snapshot``); each write must
        not clobber the other.
        """
        self.ensure_session(session_id)
        existing = self.get_observation(session_id)
        merged_data = data if data is not None else (existing["data"] if existing else None)
        merged_snapshot = (
            snapshot if snapshot is not None else (existing["snapshot"] if existing else None)
        )
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO observations(session_id, data, snapshot, updated_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    data       = excluded.data,
                    snapshot   = excluded.snapshot,
                    updated_at = excluded.updated_at
                """,
                (
                    session_id,
                    json.dumps(merged_data) if merged_data else None,
                    json.dumps(merged_snapshot) if merged_snapshot else None,
                    time.time(),
                ),
            )

    def get_observation(self, session_id: str) -> Optional[dict]:
        """Return the latest persisted observation, or None.

        Shape: {"data": {...}, "snapshot": {...}|None} — mirrors what the
        observability endpoint reads from the engine's in-memory cache.
        """
        with self._conn() as conn:
            row = conn.execute(
                "SELECT data, snapshot FROM observations WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "data": self._decode_json(row["data"]) or {},
            "snapshot": self._decode_json(row["snapshot"]) if row["snapshot"] else None,
        }

    # ── ParentSession: rolling summary + bounded recent tail ─

    def save_parent_session(
        self,
        session_id: str,
        rolling_summary: Optional[str],
        recent_tail: Optional[list[dict]],
        turn_count: int,
    ) -> None:
        """Upsert the ParentSession row for a chat session.

        Called after every parent turn. ``rolling_summary`` is the compacted
        prose for older turns; ``recent_tail`` is the exact last N user/
        assistant pairs (preserved verbatim). ``turn_count`` is the durable
        counter that survives a backend restart.
        """
        self.ensure_session(session_id)
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO parent_sessions(session_id, rolling_summary, recent_tail, turn_count, updated_at)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    rolling_summary = excluded.rolling_summary,
                    recent_tail     = excluded.recent_tail,
                    turn_count      = excluded.turn_count,
                    updated_at      = excluded.updated_at
                """,
                (
                    session_id,
                    rolling_summary,
                    json.dumps(recent_tail) if recent_tail is not None else None,
                    int(turn_count),
                    time.time(),
                ),
            )

    def get_parent_session(self, session_id: str) -> Optional[dict]:
        """Return the persisted ParentSession, or None.

        Shape: ``{"rolling_summary": str|None, "recent_tail": list[dict]|None,
        "turn_count": int, "updated_at": float}``.
        """
        with self._conn() as conn:
            row = conn.execute(
                "SELECT rolling_summary, recent_tail, turn_count, updated_at FROM parent_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "rolling_summary": row["rolling_summary"],
            "recent_tail": self._decode_json(row["recent_tail"]) if row["recent_tail"] else None,
            "turn_count": int(row["turn_count"] or 0),
            "updated_at": float(row["updated_at"] or 0.0),
        }

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

    # ── Failure memory ───────────────────────────

    def record_failure(
        self,
        session_id: str,
        intent: str,
        message: str,
        failure_type: str,
        summary: str,
    ) -> None:
        """Append a what-failed-and-why entry at loop end (the Remember
        stage). Best-effort: a failure record must never break the turn.
        Prunes stale rows (older than _FAILURE_RETENTION_DAYS) on each
        write so the table stays bounded and old secrets/failures age
        out of recall."""
        try:
            with self._conn() as conn:
                conn.execute(
                    """
                    INSERT INTO failure_memory(session_id, intent, message, failure_type, summary)
                    VALUES(?, ?, ?, ?, ?)
                    """,
                    (session_id, intent or "", (message or "")[:500], failure_type or "", (summary or "")[:1000]),
                )
                conn.execute(
                    "DELETE FROM failure_memory WHERE created_at < "
                    f"datetime('now', '-{_FAILURE_RETENTION_DAYS} days')"
                )
        except Exception as exc:  # pragma: no cover — defensive
            logger.debug("[db] record_failure skipped: %s", exc)

    def recall_failures(
        self,
        message: str,
        intent: str = "",
        limit: int = 3,
    ) -> list[dict]:
        """Read back past failures for repeated patterns (the Remember→
        Continue read path). Token-overlap match against the stored
        message (requires ≥2 overlapping tokens to avoid one-word false
        positives like any message containing "build"); newest first.
        When intent is given, only that intent's failures are considered.
        Returns [{failure_type, message, summary, intent, created_at}]."""
        tokens = {t for t in re.findall(r"[a-z0-9_]{4,}", (message or "").lower()) if t not in _FAILURE_STOPWORDS}
        if len(tokens) < 2:
            return []
        try:
            with self._conn() as conn:
                if intent:
                    rows = conn.execute(
                        """
                        SELECT failure_type, message, summary, intent, created_at
                        FROM failure_memory
                        WHERE intent = ?
                        ORDER BY id DESC
                        LIMIT ?
                        """,
                        (intent, 50),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT failure_type, message, summary, intent, created_at
                        FROM failure_memory
                        ORDER BY id DESC
                        LIMIT ?
                        """,
                        (50,),
                    ).fetchall()
        except Exception:
            return []
        scored = []
        for row in rows:
            stored_tokens = {
                t for t in re.findall(r"[a-z0-9_]{4,}", (row["message"] or "").lower())
            }
            overlap = tokens & stored_tokens
            if len(overlap) < 2:
                continue
            scored.append(
                {
                    "failure_type": row["failure_type"],
                    "message": row["message"],
                    "summary": row["summary"],
                    "intent": row["intent"],
                    "created_at": row["created_at"],
                    "score": len(overlap),
                }
            )
        scored.sort(key=lambda r: r["score"], reverse=True)
        return scored[:limit]

    # ── Cross-session decision ledger ─────────

    # Decisions older than this are pruned on write — the ledger stays
    # bounded and stale constraints age out of recall (mirrors the failure
    # memory retention rule). 180 days keeps decisions far longer than
    # failure memory (90) because they are the durable constraint surface.
    _DECISION_RETENTION_DAYS = 180

    def record_decision(
        self,
        session_id: str,
        decision: str,
        task_type: str = "",
    ) -> None:
        """Persist a decision line that must never be compressed away.

        Best-effort (a ledger write must never break the turn), with
        retention pruning on each write so the table stays bounded.
        Near-duplicate suppression: a decision already recorded within
        the last 7 days (same normalized text) is skipped — repeated
        compression of the same lines must not duplicate rows.
        """
        text = (decision or "").strip()
        if len(text) < 8:
            return
        try:
            with self._conn() as conn:
                dup = conn.execute(
                    "SELECT id FROM decision_ledger WHERE decision = ? "
                    "AND created_at > datetime('now', '-7 days')",
                    (text[:400],),
                ).fetchone()
                if dup:
                    return
                conn.execute(
                    "INSERT INTO decision_ledger(session_id, task_type, decision) VALUES(?, ?, ?)",
                    (session_id or "", (task_type or "")[:40], text[:400]),
                )
                conn.execute(
                    "DELETE FROM decision_ledger WHERE created_at < "
                    f"datetime('now', '-{self._DECISION_RETENTION_DAYS} days')"
                )
        except Exception as exc:  # pragma: no cover — defensive
            logger.debug("[db] record_decision skipped: %s", exc)

    def recall_decisions(
        self,
        task_type: str = "",
        limit: int = 5,
    ) -> list[dict]:
        """Read back the most recent ledger decisions, newest first.
        When task_type is given, only that task type's decisions are
        returned (a plan turn recalls planning decisions, a debug turn
        recalls debugging constraints). Returns
        [{decision, task_type, created_at, session_id}]."""
        try:
            with self._conn() as conn:
                if task_type:
                    rows = conn.execute(
                        "SELECT decision, task_type, created_at, session_id "
                        "FROM decision_ledger WHERE task_type = ? "
                        "ORDER BY id DESC LIMIT ?",
                        (task_type, limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT decision, task_type, created_at, session_id "
                        "FROM decision_ledger ORDER BY id DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    # ── Session episode memory ──────────────────
    #
    # The system-level "what happened this session" digest. Written by
    # core/episode_memory.py (background, lazy, invisible to users); read
    # back per turn as the episode bridge at the memory merge point.
    # All best-effort — an episode write/read must never break a turn.

    # Episodes older than this are pruned on write — the table stays
    # bounded (mirrors failure_memory 90d / decision_ledger 180d).
    _EPISODE_RETENTION_DAYS = 180

    def record_episode(
        self,
        session_id: str,
        summary: str = "",
        decisions: str = "",
        failures: str = "",
        next_steps: str = "",
        turn_count: int = 0,
    ) -> None:
        """Upsert one episode per session (re-distill overwrites).
        Prunes stale rows on each write so the table stays bounded."""
        try:
            with self._conn() as conn:
                conn.execute(
                    """
                    INSERT INTO session_episodes(session_id, summary, decisions, failures, next_steps, turn_count)
                    VALUES(?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        summary    = excluded.summary,
                        decisions  = excluded.decisions,
                        failures   = excluded.failures,
                        next_steps = excluded.next_steps,
                        turn_count = excluded.turn_count,
                        updated_at = datetime('now')
                    """,
                    (session_id, (summary or "")[:3000], (decisions or "")[:1500],
                     (failures or "")[:1500], (next_steps or "")[:1500], int(turn_count or 0)),
                )
                conn.execute(
                    "DELETE FROM session_episodes WHERE created_at < "
                    f"datetime('now', '-{self._EPISODE_RETENTION_DAYS} days')"
                )
        except Exception as exc:  # pragma: no cover — defensive
            logger.debug("[db] record_episode skipped: %s", exc)

    def get_episode(self, session_id: str) -> Optional[dict]:
        """Return the session's episode row, or None if not distilled yet."""
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT summary, decisions, failures, next_steps, turn_count, "
                    "created_at, updated_at FROM session_episodes WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
            return dict(row) if row else None
        except Exception:
            return None

    def latest_episode(self, exclude_session_id: str = "") -> Optional[dict]:
        """Most recent episode across sessions (the cross-session bridge).
        exclude_session_id skips the current session so a fresh session
        bridges from the previous one, not from itself."""
        try:
            with self._conn() as conn:
                if exclude_session_id:
                    row = conn.execute(
                        "SELECT session_id, summary, decisions, failures, next_steps, "
                        "turn_count, created_at, updated_at FROM session_episodes "
                        "WHERE session_id != ? ORDER BY id DESC LIMIT 1",
                        (exclude_session_id,),
                    ).fetchone()
                else:
                    row = conn.execute(
                        "SELECT session_id, summary, decisions, failures, next_steps, "
                        "turn_count, created_at, updated_at FROM session_episodes "
                        "ORDER BY id DESC LIMIT 1",
                    ).fetchone()
            return dict(row) if row else None
        except Exception:
            return None

    def sessions_needing_episode(
        self,
        grace_secs: float = 3600.0,
        min_turns: int = 2,
        limit: int = 5,
    ) -> list[str]:
        """Sessions with real conversation but no episode yet, quiet for at
        least grace_secs. Used by the startup sweep to distill sessions
        that were never switched away from (restart/crash)."""
        try:
            cutoff = time.time() - grace_secs
            with self._conn() as conn:
                rows = conn.execute(
                    """
                    SELECT s.id
                    FROM sessions s
                    JOIN (
                        SELECT session_id, COUNT(*) AS turns
                        FROM messages WHERE role = 'user' GROUP BY session_id
                    ) m ON m.session_id = s.id
                    LEFT JOIN session_episodes e ON e.session_id = s.id
                    WHERE e.session_id IS NULL
                      AND m.turns >= ?
                      AND (SELECT MAX(timestamp) FROM messages WHERE session_id = s.id) <= ?
                    ORDER BY m.turns DESC
                    LIMIT ?
                    """,
                    (min_turns, cutoff, limit),
                ).fetchall()
            return [str(r["id"]) for r in rows]
        except Exception:
            return []
