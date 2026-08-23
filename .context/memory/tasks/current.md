# Current Task

**Status:** IDLE — Session 363 shipped the extended workspace write redirect.

## Session 363 outcome — explicit bare-filename writes redirect to the session workspace

- **Task:** extend B-2026-08-23-17 — explicit bare-filename writes (not just the internal scratch) default into the session workspace; user-named directories still escape.
- **Gap (probed with a bound session):** plain `""` / `"notes.txt"` already landed in the workspace, but the model's legacy habits escaped: `./notes.txt` (dot noise) and `LocalMind/notes.txt` / `~/LocalMind/notes.txt` (old description advertised "Saves to ~/LocalMind/ by default").
- **Fix (file_writer.py):** `./`-only relative paths → `_default_scratch`; a `LocalMind` component anywhere routes to the workspace when a session is active (string-based `_is_legacy_scratch_path` — expanduser reads real HOME). User-named dirs (`sub/`, `Documents/`, `~/Desktop/`, absolute) unchanged. Tool description updated.
- **Verified:** 11 new parametrized tests; 2404 backend / 2 skipped, ruff clean; live (bankofai, isolated 8765) — alpha.txt + beta.txt both in `sessions/ws-extend-1/`, zero escaped root files.

## Next

- **B-2026-08-23-14 (Medium):** Connect the Memory tab UI to the memory backend.
- **B-2026-08-23-16 (Medium):** Develop the Files tab.
- **B-2026-08-23-18 (Medium):** File preview dialog multi-mode (Preview / Edit / Diff).

**Feature:** none (single-session fix)
**ADR:** none
**Review:** pending
