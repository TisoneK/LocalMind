-- Migration 008: Isolate objective transcripts and make worker claims fencing-safe.
ALTER TABLE objectives ADD COLUMN execution_session_id TEXT;
ALTER TABLE objectives ADD COLUMN lease_owner TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_objectives_execution_session
ON objectives(execution_session_id);
