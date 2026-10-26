-- Migration 013: one durable long-running goal per chat session.
-- A goal outlives a turn: the chat route keeps queueing continuation rounds
-- while the goal is active, armed, and under its round cap. The table holds
-- the CURRENT goal only (completed/cleared goals are replaced, not archived);
-- the conversation transcript remains the durable record of what each round
-- did.

CREATE TABLE IF NOT EXISTS session_goals (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL UNIQUE,
    objective       TEXT NOT NULL,
    phase           TEXT NOT NULL DEFAULT 'active'
                    CHECK(phase IN ('active', 'paused', 'blocked', 'complete')),
    revision        INTEGER NOT NULL DEFAULT 1,
    max_rounds      INTEGER NOT NULL DEFAULT 256,
    rounds_started  INTEGER NOT NULL DEFAULT 0,
    blocked_reason  TEXT,
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_session_goals_phase
ON session_goals(phase);
