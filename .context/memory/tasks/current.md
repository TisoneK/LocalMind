# Current Task

**Status:** IDLE — Session 423 closed. File-reading milestone shipped and
live-verified (commits `ca75624`, `595e998`, `e6a3bb7`, `5e03955`,
`7cfe204`, changelog `ebaab9d`): (1) cloud-file recovery — OneDrive
Files-On-Demand placeholders (WinError 362) classified, provider
auto-started with bounded hydration wait, honest `cloud_file_unavailable`
result instead of raw `[Errno 22]`; (2) content-first parser dispatch
(magic bytes) with mismatch notes and honest unsupported results for
OLE2/.pub and ambiguous zips; (3) DOCX tables extracted + embedded-image
enumeration; (4) code_exec accepts Windows-path first lines; (5)
unsupported_format recovery class (found BY the live trace — 10 improvised
code_exec calls pre-fix, 0 post); (6) image OCR reachable by path
(exts + case-insensitive matching + pillow/pytesseract installed). 21 new
tests; failure-set diff vs `d727030` worktree baseline identical; live
bankofai/qwen3.8-flash on the real transcript prompts: cv_read PASS 24s,
.pub honest + resourceful recovery, real .jpg OCR extracted text.

**Feature:** none

## Notes for the next session

- **OneDrive was DOWN on this machine at session start** (the root cause of
  the transcript failure) — file_task's auto-start brought it back and the
  CV file is now hydrated. If cloud reads fail again, check
  `Get-Process OneDrive` first; details in environments.md Windows block.
- **Deferred file-reading items (B-2026-09-05-1..3):** PDF scanned-page OCR
  routing, embedded-image extraction, screenshot-fallback for OLE2 — the
  OCR foundation is in place; each is a self-contained next slice.
- **B-2026-09-05-4:** the 23-failure Windows backend baseline needs a peer
  pass — find_path (13, KeyError family) + permission-gate asserts look
  like one shared fixture cause, not 23 bugs. (S422 saw 41F on its tree —
  counts drift; compare SETS, not counts.)
- **Windows gates quirk (S422 inefficiencies):** gates.conf/ci-check.sh
  assume the macOS venv layout (`bin/`) — on this box use
  `backend/.venv/Scripts/*`; run exit-gate CI as components until the
  scripts are venv-layout aware.
- **Standing P0 queue:** Step 4 (tool-result FTS5+vec0 index + search —
  the Context Mode hybrid), Step 5 (Context Budget Manager), Steps 6-8.
  Step 2b and Step 3 shipped (S421/S419); Step 3 live prompt-audit owed.
- **Frontend eslint drift (S422): 9 errors + 84 warnings vs
  --max-warnings 71 — the exit gate FAILS as-is on main** (unused vars /
  rules-of-hooks debt in ResponseBlockRenderer, MemoryTab,
  PerformanceMetrics; pre-S423). Needs the deferred peer pass.
- **Live-test providers:** bankofai free = hy3 / glm-5.3-flash /
  qwen3.8-flash; deepseek-v4-flash paid; gemini-2.5-flash eats the
  per-minute quota; zai 401; chutes/cerebras $0. bankofai free-tier
  rate-limits surface as a degraded final synthesis — re-run before
  judging; the tool evidence in the SSE is the reliable part.
- **Tooling:** commit messages via `git commit -F <file>`; python heredocs
  via the Bash tool must not contain backslash paths (use forward
  slashes). Live-test servers: plain Popen — never DETACHED_PROCESS with
  piped stdout on Windows (S423). Capture full pytest output to a file
  before filtering — `tail` on a pipe loses the FAILED list.
