# Current Task

**Status:** IDLE — Dependabot triage delivered (Session 413, commit `f8320ed`).
All 4 GitHub Dependabot alerts resolved (3 high + 1 moderate — @xmldom/xmldom,
browserslist, fast-uri with 4 advisories). npm audit reports 0 vulns locally;
GitHub alert may take time to refresh. Next: P0 step 4 (context budgeting)
or ruff baseline / full-suite failures peer pass.

**Feature:** `p0-context-engineering` (preview)

## Notes for the next session

- **P0 step 4 — session-level context budgeting** (structural): the six-layer
  model request (core system / current task / required capabilities /
  relevant history / relevant memory / task state) — the Context Budget
  Manager. Needs design work before implementation.
- **System-prompt diet (deferred bigger cuts):** merging CRITICAL RULES +
  COMPLETION ENFORCEMENT, trimming personas, cutting base.md's "Your values"
  recap. Need A/B testing across multiple task types.
- **Ruff baseline (32 errors):** S411 auto-fixed 2 I001 errors (34→32).
  The remaining 32 are in backend/src. Most are E501 (line too long) +
  E402 (module-level import not at top). A peer pass could auto-fix many
  with `ruff check --fix`.
- **~41 unattributed full-suite failures:** need a peer pass to cluster by
  root cause (S405-407 started this). 2 confirmed pre-existing in
  test_parent_completion_floor_e2e.py.
- **Live-test providers:** bankofai free = hy3, glm-5.3-flash, qwen3.8-flash.
  **S410-S412 verified qwen3.8-flash works.**
- **Cumulative P0 reduction (S410+S411+S412):** total session tokens
  48,790 → ~39,197 (19.7%), tools per call 3,332 → 2,386 (28.4%), peak
  history 4,228 → ~1,598-1,709 (60-62%). System prompt unchanged (~2,680
  tok/call) — diet deferred.
- **Environment quirks (logged):** (1) bankofai transient 400 on replan —
  re-run to confirm; (2) bg processes die — run sync; (3) Bash tool resets
  cwd — use `git -C` or absolute paths; (4) iteration-count variance —
  tool selection is the reliable signal; (5) `npx tsc` at root resolves to
  a stub — use `node_modules/.bin/tsc -b <tsconfig> --noEmit`.
- **GitHub Dependabot:** 0 vulns locally after S413; GitHub alert may be
  stale cache. Re-check on next push.
