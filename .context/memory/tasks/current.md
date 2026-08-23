# Current Task

**Status:** IDLE — Session 351 shipped environment awareness for todos (todo-state injection + pipeline fixes, `B-2026-08-23-2` done).

## Session 351 outcome — the agent now knows its own todos

- The user's finding: a "mark the task as complete" follow-up failed because the agent "looked for todos in chat" — todos were persisted in the DB and shown in the UI but NEVER injected into the model context.
- **FIX:** `agent_runtime` loads the session's persisted todos once and passes them to BOTH the parent loop (`todo_state=`) and the conversational fast-path (`todos=`). The loop renders a `# Current todos` block (`[x]`/`[~]`/`[ ]`/`[!]` + `N/M completed` + todo_write instruction) into the turn context; the fast-path renders the same checklist into its prompt. Two adjacent pipeline bugs found live: (1) the Session 296 lifecycle drain forwarded `todo_created` only as generic `obs_event` — bypassing DB persist + dedicated SSE, so plan todos persisted with empty text (`_bridge_todo_event` now shared by both drains); (2) `_synth_begin` created an empty leftover `syn-*` row for the `todo_write` tool call itself — now skipped.
- **LIVE before/after (bankofai, isolated 8765):** before — 3 goal items but 1 empty todo row; after — turn 1 seeds `plan-0/1/2` with real text (7 todo events), turn 2 "mark the task as complete" → *"All tasks are marked complete. ✅ 3/3 todos"* with t1/t2/t3 persisted done. No empty rows.
- **Tests:** 9 new (`test_todo_state_injection.py` + `test_todo_bridge_lifecycle_drain.py`). Backend **2336 passed / 2 skipped / 0 failures**; ruff zero new violations.

## Next

- **B-2026-08-23-3 (High):** does the exported chat contain full session information or just chat? — check what the export includes (assistant turns, tool runs, files, todos) and decide what's missing.
- **B-2026-08-23-4 (Medium):** the system should know if shell is active/off BEFORE running the shell tool (fall back to python scripts etc.) + a UI guide for toggling shell in settings.
- **B-2026-08-23-6 (Medium):** after creating a file, render it in the UI (docx, pdf, excel, ...).

**Feature:** none (single-session todo/environment-awareness fixes)
**Session:** 351 (logged in `.context/memory/agents/sessions.md`)
