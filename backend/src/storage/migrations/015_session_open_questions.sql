-- Migration 015: the session's open question — the clarifying question the
-- agent most recently asked and the user has not yet substantively answered.
-- One current record per session (latest wins; superseded, never archived):
-- it is an AID for interpreting short replies ("yes", "sure", "what?") against
-- the agent's own outstanding question, not a second source of truth — the
-- conversation transcript remains the durable record. Consumed when a short
-- reply resolves against it, superseded when a substantive message arrives,
-- replaced whenever a turn ends on a new question.

CREATE TABLE IF NOT EXISTS session_open_questions (
    session_id     TEXT NOT NULL UNIQUE,
    question       TEXT NOT NULL,
    asked_by_turn  TEXT,
    created_at     REAL NOT NULL,
    updated_at     REAL NOT NULL
);
