# Current Task

- **Session:** 152 (2026-08-12)
- **Feature:** verification-first-hardening
- **Task:** Kickoff + ADR-18 documentation for the verification-first runtime
  hardening program (the user's agentic-architecture thread: "it feels like
  generative AI rather than agentic AI"). Code-verified gap: every per-agent
  `is_done()` is a stub returning False (`agents/*/is_done.py`) — the loop
  ends on model assertion or the iteration cap; no `Goal`/`success_criteria`
  object exists in `backend/src`; VerifierAgent is an intent destination, not
  an acceptance gate; task state is scattered; no failure-memory write-back.
- **Done (152):** kickoff protocol Steps 0-3 (core 0.5.0 verified, remote
  clean, baseline green — `scripts/ci-check.sh` all pass: backend 1293, ruff
  clean, tsc clean, eslint 0 errors). ADR-18 appended to
  `plans/decisions.md`; backlog B-2026-08-12-1..5 appended; feature-scoped
  memory seeded at `features/verification-first-hardening/`.
- **Next:** Session 153 — implement B-2026-08-12-1 (P0 acceptance gate: typed
  success criteria + first-class TaskState + real is_done() + verify→replan).
  Plan a real-model smoke test FIRST (Zen was 429 on 2026-08-11; per the flaw
  log, do not ship loop-path code untested). Secondary pending: B-2026-08-12-4
  (Session 151 carry-over — re-run the live two-turn UI check once the Zen
  rate limit clears; servers were left running).
