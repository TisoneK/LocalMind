# Current Task

**Status:** IDLE — Session 428 closed. ADR-57 slice 2 shipped + LIVE-verified:
post-tool Thinker consults now fire after EVERY tool as background tasks
(one-in-flight, cap 5/turn, prose streamed, analysis injected at the next
model-call boundary); failures keep the BLOCKING consult. LIVE
bankofai/qwen3.8-flash same-prompt before/after: consults 2 → 4, streamed
consult reasoning 2223 → 7463 chars, latency 66.7s → 60.6s (overlap — no
added latency), answer held. 37 thinker/loop tests; core+e2e failure set =
verified pre-existing baseline (12). Also fixed a security flaw: config.py
logged plaintext api_keys at INFO on every boot (`cbbbabe`) — **key values
appeared in this session's chat transcript; ROTATION ADVISED for the
configured providers (bankofai, zen, cerebras, gemini, zai, deepseek,
omniroute).**

**Feature:** none

## Notes for the next session

- **SECURITY: rotate the provider keys listed above** — they were visible in
  a session transcript (and in every pre-fix server log). After rotation,
  update keys ONLY via the app's Settings UI.
- **Consult cadence is now a tuning surface:** `_THINKER_CONSULT_CAP` (5/turn)
  and `_THINKER_TOOL_SKIP` in loop.py; watch live behavior and tune.
- **ADR-57 slice 4 (unstarted):** run the Thinker's analysis on a
  faster/cheaper role while the main model acts (model-agnostic per the
  standing rule).
- **Test-fixture contract (from S428):** fake dispatches MUST accept
  `adapter=None, **kwargs`; instant async fakes starve background tasks —
  use `await asyncio.sleep(0)` at yield points and warm-turn delta timing.
- **Port discipline:** one port per concurrent agent; grep the server log
  for "already in use" before trusting any trace (S425/S426, twice-burned).
- **Standing P0 queue:** Step 4 (tool-result FTS5+vec0 index + search), Step 5
  (Context Budget Manager), Steps 6-8; Step 3 live prompt-audit owed.
- **Frontend eslint drift (S422): 9 errors + 84 warnings** still fails the
  exit gate on main; backend ~12-failure baseline peer pass (B-2026-09-05-4).
- **Experiential Labs reverted (B-2026-09-06-1)** — restore = `git revert
  645b5c4` + owed smoke test; read the backlog entry first.
- **Live-test providers:** bankofai free = hy3 / glm-5.3-flash / qwen3.8-flash;
  deepseek-v4-flash is PAID on this account; zai 401; chutes/cerebras $0.
  Probe with a 5-token request before scheduling live traces (gateway outages
  happen).
- **Windows:** use `backend/.venv/Scripts/*`; run exit-gate CI as components;
  python heredocs must not contain backslash paths; commit messages via
  `git commit -F <file>`; live servers via plain Popen.
- **context-collab.ps1:** use `--refs`, not `--re` (alias breaks pwsh binding).
