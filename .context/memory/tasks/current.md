# Current Task

**Status:** IDLE — Session 383 closed **B-2026-08-23-11** (todo title/content split).

## Session 383 outcome

- **`358ea38`:** Todos now carry a short user-facing `title` alongside the full `content`:
  - **Derivation:** `_title_for_goal` ("Create a.txt" / "Create the folder path-test") + `_title_for_sub_goal` ("Check current state" / "Write the file" / "Verify the result") in goal_interpreter; `derive_goal_tree` sets `DerivedGoal.title`; the runtime emits `{goal, sub_goals, title, sub_goal_titles}`.
  - **Loop seeding**: `todo_created` emits `text=title` (UI label) + `content=full goal/route` (agent context + gate).
  - **Bridge**: `chat.py _bridge_todo_event` persists content + title (falls back when only text).
  - **DB**: migration `010_todo_title.sql` adds `todos.title`; `upsert_todo(title=...)` writes it on create, never wipes on status updates; `list_todos` includes it.
  - **API**: TodoItem/CreateTodoRequest/UpdateTodoRequest + GET/POST/PATCH thread `title` (`r["title"]` guarded via `in r.keys()`).
  - **Frontend**: `TodoItem.title?/content?` types; `normalizeTodoEvent` prefers title → text; `getTodos` maps title-first; `TodoList` renders `displayText(t)` (title||text) with a tooltip showing full content when different, `sent truncated` for long titles; sub-rows too.
- **Fallbacks**: legacy callers (text only) → content fills both; DB rows with NULL title → content shows.
- **Verification**: backend **2507 passed** / 2 skipped (23 goal-derive tests incl. 4 new title tests; todo API suite updated for the column); frontend **348 passed** + tsc clean; ruff clean (pre-existing E501s only).
- **Next:** continue the backlog one item at a time. Top candidates: **B-2026-08-23-33** (op permissions), **-34** (chat modes), **-35** (never-rude declines), **-37** (write-stats table), or quick UI wins (-26 ⋮ panel overflow, -9 action-pill tooltips). Pre-existing untracked trace residue at `backend/Dev/` + `backend/scratch/` left untouched.