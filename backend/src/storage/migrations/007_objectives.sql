-- Migration 007: User-started autonomous objectives.
-- Objectives outlive an individual HTTP/chat turn. Execution remains bounded
-- and user-controlled; side-effecting work can be blocked for approval.

CREATE TABLE IF NOT EXISTS objectives (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    prompt          TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'queued',
    priority        INTEGER NOT NULL DEFAULT 0,
    result          TEXT,
    error           TEXT,
    approval        TEXT,
    resume_message  TEXT,
    last_event      TEXT,
    attempts        INTEGER NOT NULL DEFAULT 0,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL,
    started_at      REAL,
    completed_at    REAL,
    lease_until     REAL
);

CREATE INDEX IF NOT EXISTS idx_objectives_status_priority
ON objectives(status, priority DESC, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_objectives_session
ON objectives(session_id, created_at DESC);
