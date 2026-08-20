-- Migration 009: Rolling ParentSession summary + readiness state (ADR-52 phase 2 / B-2026-08-20-1).
-- One row per chat session. The rolling summary compacts older turns so the
-- parent prompt stays bounded on long conversations; the recent_tail holds
-- the exact last N user/assistant pairs (verified evidence + user wording
-- preserved). turn_count is the durable counter that survives backend restart.

CREATE TABLE IF NOT EXISTS parent_sessions (
    session_id      TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    rolling_summary TEXT,
    recent_tail     TEXT,
    turn_count      INTEGER DEFAULT 0,
    updated_at      REAL
);

CREATE INDEX IF NOT EXISTS idx_parent_sessions_updated
ON parent_sessions(updated_at);
