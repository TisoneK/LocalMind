-- Migration 011: session_writes — durable lightweight write stats.
-- One row per successful file write (session_id, path, tool,
-- bytes, lines, kind, timestamp). Capped at ~500 rows per session via
-- pruning on insert. Deleted with the session (explicit delete — SQLite FK
-- cascade requires PRAGMA foreign_keys = ON which is already set in the
-- connection pool, but belt-and-suspenders is safer).

CREATE TABLE IF NOT EXISTS session_writes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    path        TEXT NOT NULL,
    tool        TEXT NOT NULL DEFAULT 'file_write',
    bytes       INTEGER NOT NULL DEFAULT 0,
    lines       INTEGER NOT NULL DEFAULT 0,
    kind        TEXT NOT NULL DEFAULT 'created',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_session_writes_session ON session_writes(session_id);
