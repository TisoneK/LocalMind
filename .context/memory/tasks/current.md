# Current Task

**Status:** IDLE — Session 352 shipped full-session chat export (`B-2026-08-23-3` done).

## Session 352 outcome — the export answers "just chat?" with: now the full session

- **Audit answer:** before this session, the export was *just chat* — role/content/timestamp + bare tool names (JSON: `{name, status}`). Thinking, tool args/outputs, files, todos, metrics, phases were all dropped; todos weren't even fetched.
- **User scope decision (asked via UI):** full session in both formats — Markdown = readable transcript, JSON = complete record.
- **FIX:** `exportChats.ts` renders todo checklists + per-message thinking/acknowledgement/tool steps (args/output/error/reasoning/provider/duration)/files/metrics/phases in Markdown; JSON bumps to `version: 2` with every persisted field + todos. `exportSessions` gained a `fetchTodos` fetcher (wired in `WorkspaceLayout` via `client.getTodos`). Backend gap found live: agent-written files only reached the live `done` SSE, never the stored message — `sessions.py` now derives `fileResults` from the persisted tool timeline (`_agent_written_paths`: file_write `path:\n\ncontent`, edit_file JSON `path`).
- **VERIFIED:** backend **2342 passed / 2 skipped**; frontend **269 passed**; `tsc -b` clean; ruff/eslint zero new. Live (bankofai 8765): history returns the derived written paths (`/tmp/export-write-a.txt`, `-b.txt`) + todos + full toolCalls.

## Next

- **B-2026-08-23-4 (Medium):** the system should know if shell is active/off BEFORE running the shell tool (fall back to python scripts etc.) + a UI guide for toggling shell in settings.
- **B-2026-08-23-5 (Medium):** the first action almost never switches the chat tab to the actions tab automatically until the second action kicks in.
- **B-2026-08-23-6 (Medium):** after creating a file, render it in the UI (docx, pdf, excel, ...).

**Feature:** none (single-session export audit + fix)
**Session:** 352 (logged in `.context/memory/agents/sessions.md`)
