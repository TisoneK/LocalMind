# Current Task

**Status:** IDLE — Session 365 shipped the per-session Files sidebar view.

## Session 365 outcome — per-session Files view in the sidebar

- **Task:** each chat in the sidebar lists its workspace artifacts.
- **Backend:** `GET /api/sessions/{id}/files` — recursive flat listing of the session workspace (relPath/size/modified; folders included even when empty; refuses paths outside the workspace root).
- **Frontend:** "Files" chevron per session row in the Chat tab → fetches once (cached), renders compact indented list, click opens FilePreviewDialog. Empty state: "No files yet".
- **Verified:** 4 backend + 2 frontend tests; 2408 backend / 293 frontend, tsc/ruff/eslint clean; live (bankofai, isolated 8765) — agent-created report.txt appeared in the session files listing.

## Next

- **B-2026-08-23-14 (Medium):** Connect the Memory tab UI to the memory backend.
- **B-2026-08-23-16 (Medium):** Develop the Files tab.
- **B-2026-08-23-18 (Medium):** File preview dialog multi-mode (Preview / Edit / Diff).

**Feature:** none (single-session feature)
**ADR:** none
**Review:** pending
