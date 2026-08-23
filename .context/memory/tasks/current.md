# Current Task

**Status:** IDLE — Session 364 audited and cleaned the real-home root.

## Session 364 outcome — real-home root audit (no code change)

- **User report:** files in `~/LocalMind` root, expected `~/LocalMind/<session-id>/`; also asked about "edited file copied to replace the original".
- **Evidence:** all 4 root files predate the workspace feature (shipped 03:36 today); `find -newermt` on the root → zero files. Current writes are session-scoped (verified live Sessions 362/363).
- **Edit copy-back** is intended: user-specified real paths get the edited file copied over the original; bare filenames stay in the session workspace.
- **Action (user chose):** deleted the 4 stale root files (hello.py, create_news.py, generate_news.py, dinner_recipe.txt). Root now holds only localmind.db* + settings.json.

## Next

- **B-2026-08-23-14 (Medium):** Connect the Memory tab UI to the memory backend.
- **B-2026-08-23-16 (Medium):** Develop the Files tab.
- **B-2026-08-23-18 (Medium):** File preview dialog multi-mode (Preview / Edit / Diff).

**Feature:** none (audit + cleanup)
**ADR:** none
**Review:** pending
