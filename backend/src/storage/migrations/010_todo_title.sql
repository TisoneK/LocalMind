-- Migration 010: todos.title — user-facing short label for the Todos panel.
-- The plan/goal rows keep their FULL content (paths,
-- commands) in `content` for the agent + acceptance gate, while `title`
-- holds a short verb-led label ("Create a.txt") the user actually wants
-- to see. Existing rows get a NULL title — the UI falls back to content.

ALTER TABLE todos ADD COLUMN title TEXT;