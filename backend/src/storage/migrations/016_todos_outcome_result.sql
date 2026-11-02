-- Migration 016: the todo carries its own verification contract.
-- A todo is a meaningful piece of work (not a tool call), so it needs two more
-- columns: `expected_outcome` — what evidence establishes this todo as done,
-- stated by the Planner when the list is drawn up — and `result` — what
-- actually satisfied it (or why it stayed blocked/failed), recorded when the
-- todo closes. Both are optional; a todo without an outcome keeps the old
-- tool-success contract. Existing rows keep NULL in both.

ALTER TABLE todos ADD COLUMN expected_outcome TEXT;
ALTER TABLE todos ADD COLUMN result TEXT;
