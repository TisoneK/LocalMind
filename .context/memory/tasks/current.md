# Current Task

**Status:** IDLE — Session 407 (backlog marking sweep) COMPLETE: verified all 90
unchecked backlog entries against git history, session logs, collab release
events, and code/test inspection; checked off 40 with dated evidence notes
(27 fixed+shipped, 7 superseded/parked by ADR-53, 2 superseded-by-newer,
2 demoted/closed-by-evidence, loop-discipline Steps 3-5). ~50 remain genuinely
open — grouped list in the `2026-09-02 — Backlog marking sweep` section of
`tasks/backlog.md`. Re-confirmed B-2026-08-30-17 (Windows autocrlf verify
false-positive) live; heuristic correction appended to `flaws/log.md`.
No product code touched. No live session in progress.

**Feature:** none

## Notes for the next session

- The backlog's unchecked set is now trustworthy: unchecked = no fix evidence
  found on 2026-09-02. Newest open items: B-2026-08-25-4/-7/-12/-13,
  B-2026-08-30-8/-12/-15 (verify), B-2026-08-29-1, B-2026-08-24-7/-17,
  B-2026-08-23-20/-24, B-2026-08-25-2/-3/-10, loop-discipline Step 5 remainder
  (context-quality pass).
- **Live-test:** authorized per-item when necessary; test backend on **port 8010**
  (never 8000 — the user's app). Read `.context/memory/system/live-testing.md`.
- Collaboration: last trail events are claude-opus-4.8 releases (web-truncation,
  follow-through, suite-nl2-id3, web-fetch-table) — all scopes released, none
  active as of 2026-09-02.
