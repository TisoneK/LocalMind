# Current Task

**Status:** IDLE — Sessions 425 + 426 closed (concurrent, coordinated via the
event trail). **S425 (main `540792a`):** ADR-57 slice 1 shipped + LIVE-verified
— Thinker consults stream their prose reasoning to the ThinkingBlock
(surfacing stops at the JSON marker — the S324 leak class is prevented
structurally), the post-tool consult builds on the turn's earlier analysis
(`Evidence.prior_analysis`), and the prompt is rewritten for human-like,
precise, decision-focused reasoning that never exposes agent machinery (owner
directives). LIVE bankofai/qwen3.8-flash before/after: consults surfaced 0
chars → 2189–2737 chars, machinery scan clean, no JSON leak, answers held.
34 thinker/loop tests (7 new). **S426:** fast-path gate fix (`a2a3a48`, "Hi"
75.0s → 0.3s zero provider calls, S206 boundary restored) + parent-only tool
catalog cut (`f4f567e`, ADR-53; ADR-40 tool-selection bar held live). Full
suite failure set = documented baseline families both sides.

**Feature:** none

## Notes for the next session

- **ADR-57 slice 2 (concurrent consults) is the frequency lever.** Consults
  are still value-gated (failure / ≥2 sources, once/turn) — the latency fix
  stands. Streaming made them visible; concurrency would let them fire after
  every tool without wall-clock cost. Map the data dependencies first
  (ADR-57 Open-Q1). Do NOT re-add every-tool serial consults (S420-era
  2-minute turns).
- **S426 follow-ups (the latency roadmap, prioritized):** fix #3 =
  cache-prefix stability (39% cached — per-iteration prompt assembly +
  tool-schema prefix in loop.py — S425's loop.py claim is now RELEASED,
  safe to touch); metrics honesty (panel shows last-call prompt + undercounts
  llm_calls — surface `total_prompt_tokens`); init+Thinker skip for obviously-
  simple turns (architectural, ADR-53-compliant).
- **Watch the consult prose on live passes:** qwen3.8-flash occasionally
  restates the request ("The user is Tisone and wants me to...") — prompt-
  level, not structural.
- **Port discipline (S425 + S426, twice-burned):** one port per concurrent
  agent (8765, 8766, …) — shared-8765 kill_port collisions cost S426 ~25 min
  and cost S425 one INVALID after-run (a stale server answers health checks
  and the client silently measures OLD code). Before trusting any trace:
  verify the port was free, and grep the server log for "already in use" + a
  fresh "parent-kernel] ready" line. Candidate fix: add the check to
  `scripts/live_test_cybercafe.py` boot_server.
- **context-collab.ps1:** use `--refs`, not `--re` (the alias breaks pwsh
  parameter binding).
- **Measurement lesson (S426):** the parent's real per-turn static surface is
  the native-bootstrap branch (~1.4K prompt + intent-scoped defs), NOT the
  5.4K/5.3K figures from the initial chat assessment. Verify which render a
  measurement script hits before quoting sizes.
- **Live-test providers (S426 update):** bankofai free = hy3 / glm-5.3-flash /
  qwen3.8-flash; **deepseek-v4-flash is NOT free on this account** (400
  "credit insufficient balance=0" — live-testing.md's "fast AND free" is
  stale here); gemini-2.5-flash eats per-minute quota; zai 401; chutes/
  cerebras $0. bankofai also had a provider-side outage (their routing
  postgres "too many clients", ~03:45–04:15 on 2026-09-06 — all models incl.
  paid hung a 5-token probe) — wait minutes, re-run; probe minimally before
  scheduling live traces.
- **Experiential Labs was REVERTED per owner directive (B-2026-09-06-1,
  ADR-58 amended)** — do NOT re-add without reading that backlog entry;
  restore = `git revert 645b5c4` + the owed smoke test.
- **Standing P0 queue:** Step 4 (tool-result FTS5+vec0 index + search), Step 5
  (Context Budget Manager), Steps 6-8; Step 3 live prompt-audit owed.
- **Frontend eslint drift (S422): 9 errors + 84 warnings vs --max-warnings 71
  — the exit gate FAILS as-is on main.** Needs the deferred peer pass.
- **B-2026-09-05-4:** the ~23-failure Windows backend baseline needs the peer
  pass (find_path KeyError family + permission-gate asserts look like one
  shared fixture cause). Deferred file-reading items B-2026-09-05-1..3 remain.
- **Windows gates quirk:** gates.conf/ci-check.sh assume the macOS venv layout
  (`bin/`) — on this box use `backend/.venv/Scripts/*`; run exit-gate CI as
  components.
- **Tooling:** commit messages via `git commit -F <file>`; python heredocs via
  the Bash tool must not contain backslash paths (use forward slashes). Large
  HTTP bodies: save to a file FIRST, then parse (S424). Live servers: plain
  Popen — never DETACHED_PROCESS with piped stdout on Windows (S423). Capture
  full pytest output to a file before filtering — `tail` on a pipe loses the
  FAILED list. **Stash-based baseline capture: `git stash list` must be EMPTY
  before the after-run (S426 mislabeled a trace set this way — prefer a
  read-only worktree).**
