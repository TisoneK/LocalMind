# Current Task

**Status:** IDLE — Session 425 closed. ADR-57 slice 1 shipped + LIVE-verified
(main `540792a`): Thinker consults stream their prose reasoning to the
ThinkingBlock (surfacing stops at the JSON marker — the S324 leak class is
prevented structurally), the post-tool consult builds on the turn's earlier
analysis (`Evidence.prior_analysis`), and the prompt is rewritten for
human-like, precise, decision-focused reasoning that never exposes agent
machinery (owner directives). LIVE bankofai/qwen3.8-flash before/after on the
same prompt: baseline consults surfaced 0 chars → after: 2189–2737 chars
streamed, machinery-word scan clean, no JSON leak, correct answers both sides.
34 thinker/loop tests (7 new); full-suite failure set = documented baseline.

**Feature:** none

## Notes for the next session

- **ADR-57 slice 2 (concurrent consults) is the frequency lever.** Consults
  are still value-gated (failure / ≥2 sources, once/turn) — the latency fix
  stands. Streaming made them visible; concurrency would let them fire after
  every tool without wall-clock cost. Map the data dependencies first
  (ADR-57 Open-Q1). Do NOT re-add every-tool serial consults (S420-era
  2-minute turns).
- **Watch the consult prose on live passes:** qwen3.8-flash occasionally
  restates the request ("The user is Tisone and wants me to...") — prompt-
  level, not structural.
- **Harness hygiene (S425 trap):** before trusting any live trace, grep the
  server log for "already in use" + a fresh "parent-kernel] ready" line — a
  stale server on 8765 measures the OLD code silently (cost one invalid
  after-run). Candidate fix: add the check to `scripts/live_test_cybercafe.py`
  boot_server.
- **context-collab.ps1:** use `--refs`, not `--re` (the alias breaks pwsh
  parameter binding).
- **bankofai outages happen gateway-wide** (all models incl. paid hung ~30
  min on 2026-09-06 03:45–04:15) — probe with a 5-token request before
  scheduling live traces.
- **Standing P0 queue:** Step 4 (tool-result FTS5+vec0 index + search), Step 5
  (Context Budget Manager), Steps 6-8; Step 3 live prompt-audit owed.
- **Frontend eslint drift (S422): 9 errors + 84 warnings vs --max-warnings 71
  — the exit gate FAILS as-is on main.** Needs the deferred peer pass.
- **B-2026-09-05-4:** the ~23-failure Windows backend baseline needs the peer
  pass (find_path KeyError family + permission-gate asserts look like one
  shared fixture cause). Deferred file-reading items B-2026-09-05-1..3 remain.
- **Experiential Labs was REVERTED per owner directive (B-2026-09-06-1,
  ADR-58 amended)** — do NOT re-add without reading that backlog entry;
  restore = `git revert 645b5c4` + the owed smoke test.
- **Windows gates quirk:** gates.conf/ci-check.sh assume the macOS venv layout
  (`bin/`) — on this box use `backend/.venv/Scripts/*`; run exit-gate CI as
  components.
- **Live-test providers:** bankofai free = hy3 / glm-5.3-flash / qwen3.8-flash;
  deepseek-v4-flash paid; gemini-2.5-flash eats the per-minute quota; zai 401;
  chutes/cerebras $0. bankofai free-tier rate-limits surface as a degraded
  final synthesis — re-run before judging; the tool evidence in the SSE is the
  reliable part.
- **Tooling:** commit messages via `git commit -F <file>`; python heredocs via
  the Bash tool must not contain backslash paths (use forward slashes). Live
  servers: plain Popen — never DETACHED_PROCESS with piped stdout on Windows
  (S423). Capture full pytest output to a file before filtering.
- **Peer state at this closeout:** S426's closeout commit `e477612` was still
  UNPUSHED in the main checkout when I integrated (their pull --rebase may hit
  a memory-tail conflict at sessions.md/SUMMARY.md — both appended at EOF).
