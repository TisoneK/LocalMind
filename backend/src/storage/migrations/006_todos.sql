-- Migration 006: Todos table — persistent task tracking for the UI TodoList panel.
-- The todo API was once a stub (returned []) and the orchestrator wrote todos
-- to a per-turn scratch dir the UI never saw. This table is the bridge:
-- the engine writes todos here, the API reads them, the UI displays them.

CREATE TABLE IF NOT EXISTS todos (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    content     TEXT NOT NULL,
    completed   INTEGER DEFAULT 0,  -- 0 = pending, 1 = done
    status      TEXT DEFAULT 'pending',  -- pending, in_progress, done, failed
    priority    TEXT DEFAULT 'medium',  -- high, medium, low
    "order"     INTEGER DEFAULT 0,  -- display order within the session
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_todos_session ON todos(session_id);
CREATE INDEX IF NOT EXISTS idx_todos_session_order ON todos(session_id, "order");
