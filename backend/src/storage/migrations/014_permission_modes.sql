-- Migration 014: session-pinned permission modes + the durable permission
-- audit / write-ahead tool-effect journal (§U item 5, rows H + J).
--
-- session_permissions: the file-effect mode pinned to one session. One row per
-- session, durable, so the pin survives a backend restart and never crosses
-- into another session. Absent = the shipped default (workspace_write); the
-- resolver maps missing → default, so no row is written until the user picks a
-- mode. Deleted with the session (explicit delete in delete_session).
--
-- permission_audit: the model-invisible record of every permission decision at
-- the tool-execution seam, doubling as the write-ahead journal for allowed
-- side-effecting calls. An allowed effecting call is written outcome='pending'
-- BEFORE its body can cause an effect, then resolved to 'done'/'failed' after.
-- A 'pending' row that survives a restart is an interrupted call — reconciled
-- to 'unknown' on store open, never silently re-executed. A denied call is
-- written outcome='done' (its body never ran). Nothing here is ever injected
-- into a prompt.

CREATE TABLE IF NOT EXISTS session_permissions (
    session_id  TEXT PRIMARY KEY,
    mode        TEXT NOT NULL,
    updated_at  REAL NOT NULL DEFAULT (unixepoch('now'))
);

CREATE TABLE IF NOT EXISTS permission_audit (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL,
    tool        TEXT    NOT NULL,                        -- intent value
    mode        TEXT,                                    -- mode in force ('' if unresolved)
    decision    TEXT    NOT NULL,                        -- 'allow' | 'deny'
    reason      TEXT    NOT NULL DEFAULT '',
    fail_closed INTEGER NOT NULL DEFAULT 0,
    outcome     TEXT    NOT NULL DEFAULT 'done',         -- 'pending'|'done'|'failed'|'unknown'
    created_at  REAL    NOT NULL DEFAULT (unixepoch('now')),
    resolved_at REAL
);

CREATE INDEX IF NOT EXISTS idx_permission_audit_session
ON permission_audit(session_id, created_at);
