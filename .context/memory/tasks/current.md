# Current Task

**Status:** IDLE — Session 361 shipped session workspaces (B-2026-08-23-17 done).

## Session 361 outcome — per-session artifact folders, deleted with the chat

- User picked up B-2026-08-23-17: sessions tied to workspaces; artifacts stored
  per session; deleting a chat deletes its artifacts; folders under the LocalMind
  home keyed by session id.
- **FIX:** new `core/session_workspace.py` — `<home>/sessions/<sanitized_id>/`
  lifecycle. Sanitization neutralizes path traversal / drive prefixes / null
  bytes (sha1 fallback); `delete_workspace` refuses anything outside the
  workspace root (never an arbitrary rmtree). Wiring: `db.ensure_session`
  creates the folder on first touch; chat.py uploads go to
  `<workspace>/uploads/` (replacing the shared ~/LocalMind/uploads dir);
  DELETE /api/sessions/{id} removes the folder after the DB row; sessions list
  exposes `workspacePath`; `_build_environment_context(session_id=...)` injects
  a "Session workspace:" line (compact + full) so the agent knows where to put
  artifacts — threaded AgentLoop.run → BaseAgent.run → agent_runtime.
- **Decision:** agent `_do_write` default destinations are NOT force-redirected
  (risky; would break "write to ~/Desktop" cases) — the workspace is the
  artifact home via context + uploads + deletion scope. Documented follow-up:
  point `_do_write`'s default scratch at the workspace.
- **LIVE (bankofai, isolated 8765):** chat turn → `sessions/ws-live-1/` created;
  upload → landed in `sessions/ws-live-1/uploads/note.txt`; sessions list shows
  workspacePath; DELETE → folder gone. Full lifecycle.
- **Tests:** 11 new unit (sanitize traversal/drive/null, lifecycle,
  delete-never-escapes-root) + 1 context; updated test_chat upload-failure to
  sabotage the per-session dir. **2382 backend passed / 2 skipped**,
  **291 frontend passed**, tsc clean, ruff clean (2 E501s pre-existing).
- **Next:** backlog remains open (e.g. -14 memory tab UI, -19 custom theme,
  -20 code block rewrite, -15 tab auto-switch).

**Feature:** B-2026-08-23-17 (session workspaces)
**Review:** n/a
