# Current Task

**Status:** IDLE — core 0.8.0 → 0.9.1 shipped (Session 422, `557b1fc` + bookkeeping).
Update run twice from the git-checkout source per the 0.8.x Windows
migration; verify green on this CRLF tree (closes B-2026-08-30-17);
`.context/.gitattributes` + root CLAUDE.md installed; kickoff.md
regenerated (collab note-channel + gate commands); AGENTS.md digest
refreshed. Bookkeeping logged (sessions/flaws/inefficiencies/ai-models/
environments/SUMMARY).

**Feature:** none

## Notes for the next session

- **Peer's uncommitted product work in tree (DO NOT TOUCH, owner confirmed):**
  `backend/src/tools/code_exec.py` + `tests/tools/test_code_exec_dispatch.py`
  (live peer session) and `backend/src/tools/file_reader.py` +
  `tests/tools/test_file_reader.py` (unclaimed continuation of `ca75624`).
  Stage explicit paths only; never `git add -A`/stash/rebase the shared tree.
- **Standing P0 queue:** Step 4 (tool-result FTS5+vec0 index + search — the
  Context Mode hybrid), Step 5 (Context Budget Manager), Steps 6-8. Step 2b
  and Step 3 shipped (S421/S419); Step 3 live prompt-audit still owed.
- **Live-test providers:** bankofai free = hy3 / glm-5.3-flash / qwen3.8-flash;
  deepseek-v4-flash paid; gemini-2.5-flash works but eats the per-minute
  quota; zai 401; chutes/cerebras $0.
- **Windows gates quirk (S422 inefficiencies):** gates.conf/ci-check.sh assume
  the macOS venv layout (`bin/`) — on this box use `backend/.venv/Scripts/*`;
  run exit-gate CI as components until the scripts are venv-layout aware.
- **Tooling:** commit messages via `git commit -F <file>`; python heredocs via
  the Bash tool must not contain backslash paths (use forward slashes).
- **Standing:** ~56 pre-existing backend failures (incl. multipart collection
  errors) + ruff baseline need the deferred peer pass; ADR-57 slice 3 queued.
