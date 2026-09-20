-- Migration 012: a todo's identity is (session_id, id), not id alone.
-- Plan and synthetic tasks use the same ids in every chat ("plan-0", "syn-0"). With `id` as the
-- whole primary key, the first chat to create "plan-0" owned that row forever: every later chat's
-- upsert found it by id and updated THAT chat's row instead of inserting its own. The later chat
-- showed its plan live from the event stream, then lost it when the end-of-turn refetch found
-- nothing saved for it. Rows are copied as they are; only the key changes.

CREATE TABLE todos_per_session (
    id          TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    content     TEXT NOT NULL,
    completed   INTEGER DEFAULT 0,
    status      TEXT DEFAULT 'pending',
    priority    TEXT DEFAULT 'medium',
    "order"     INTEGER DEFAULT 0,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,
    title       TEXT,
    PRIMARY KEY (session_id, id)
);

INSERT OR IGNORE INTO todos_per_session
    (id, session_id, content, completed, status, priority, "order", created_at, updated_at, title)
SELECT id, session_id, content, completed, status, priority, "order", created_at, updated_at, title
FROM todos;

DROP TABLE todos;
ALTER TABLE todos_per_session RENAME TO todos;

CREATE INDEX IF NOT EXISTS idx_todos_session ON todos(session_id);
CREATE INDEX IF NOT EXISTS idx_todos_session_order ON todos(session_id, "order");
