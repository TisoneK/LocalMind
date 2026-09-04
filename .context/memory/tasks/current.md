# Current Task

**Status:** IDLE — P0 Context Architecture Research delivered (Session 414,
no code changes). The research is in
`.context/memory/reviews/2026-09-04-context-architecture-research.md`.
Awaiting user direction on the proposed architecture + Implementation Plan.

**Feature:** `p0-context-engineering` (preview) — research milestone complete

## Notes for the next session

- **The research is the deliverable.** The user's pasted file said: "I would
  NOT let the coding agents implement anything yet. First produce the
  research." That research is done. The Implementation Plan (Part 5 of the
  report) proposes 7 steps across ~10-14 sessions, starting with Step 1
  (surface cache data to UI — 1 session, smallest blast radius).
- **Key live finding (verified this session):** bankofai/qwen3.8-flash DOES
  pass through prompt caching. Live test: call 1 = 0 cached / 1256 prompt;
  call 2 = 1024 cached / 1256 prompt (81.5% hit). The cache IS working. The
  user's "Context 59%" is the UNDISCOUNTED number — the frontend uses
  `prompt_tokens_approx` (chars/4 estimate of FULL prompt) instead of the
  provider-reported `cached_tokens`. The backend already captures
  `cached_tokens` (openai_compat.py:718) and logs the hit rate (loop.py:3536);
  the gap is purely frontend display.
- **Step 1 (highest leverage):** wire `cached_tokens` from `provider_usage` →
  SSE → frontend `PerformanceMetrics`. Show per-call fresh/cached/write/output
  split + cumulative across N calls + equivalent inference work (after 90%
  cache discount). 1 session, no agent-loop change, immediately changes the
  user's mental model of the problem.
- **S410-S412 status:** validated as compatible groundwork (compactor tune +
  tool scoping + stale-ref fixes), NOT the architectural change. Keep them.
- **The architectural change starts at Step 5 (Context Budget Manager).**
  Steps 1-4 are enabling work (UI display, byte-stable prefix, memory
  retrieval gate, checkpoint compaction). Step 6 (Instruction Epoch) + Step 7
  (Internal Agent Pattern) are refinements.
- **Environment quirks (logged across S410-S414):** (1) sandbox wipes between
  sessions — re-clone + re-venv + re-settings each session; (2) bg processes
  die immediately — run sync; (3) Bash tool resets cwd — use `git -C` or
  absolute paths; (4) iteration-count variance — tool selection is the
  reliable signal; (5) subagents may lose Bash/Write mid-session — they
  complete research before failure and include worklog inline.
- **GitHub Dependabot:** 0 vulns locally after S413 (npm audit fix).
- **Standing:** ~41 unattributed full-suite failures + 32-error ruff baseline
  still need a peer pass (deferred — P0 architecture takes priority).
