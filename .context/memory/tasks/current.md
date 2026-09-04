# Current Task

**Status:** IDLE — Session 417 closed. Two user-reported transcript issues
fixed and pushed (`c9c18c0`, `df0f9b1`):
1. **Search relevance/safety (B-2026-09-04-3):** `web_search` no longer
   surfaces off-topic fallback junk (dictionary defs / OnlyFans) — a held set
   below half distinctive-term coverage is discarded (`_fallback_is_on_topic`).
2. **Thinking-timer double-count (B-2026-09-04-4):** frontend `thinkMs` now
   accumulates active thinking only and pauses during tools, so it no longer
   overlaps the per-tool durations.

Both flaws logged FIXED; 30 web_search + 36 frontend tests; ruff + tsc clean;
live web_search sanity on both transcript queries (NYT/CBS, no junk).

**Feature:** `p0-context-engineering` (preview) — Step 1 complete; Steps 2-8 open

## Notes for the next session

- **Standing priority: P0 Context Engineering Step 2** — byte-stabilize the
  system prefix (addendum plan). Audit `build_agent_system_prompt` for
  intent-varying sections; split a durable baseline from the intent tail.
- **Search follow-ups (deferred, not bugs fixed here):** (a) the model fires
  web_search BEFORE the RSS fetch for "trending news"-type queries — a
  tool-routing/selection question; (b) the Brave fallback path is not
  relevance-gated (pre-existing) — if a Brave key is set, its results bypass
  the coverage floor.
- **Live-test providers (2026-09-04):** bankofai free models = hy3,
  glm-5.3-flash, qwen3.8-flash (`--adapter bankofai --model X`);
  deepseek-v4-flash is paid (429/balance). gemini-2.5-flash works but one
  agent turn eats the per-minute quota. zai 401; chutes/cerebras out of credit.
- **Tooling:** commit messages via `git commit -F <file>` — heredoc command
  substitution breaks through the terminal-tool shell wrapper. macOS box (no
  `timeout` CLI; web_search has its own 12s/provider caps).
- **Standing:** ~36 pre-existing Windows backend failures + 32-34 ruff baseline
  still need the deferred peer pass; ADR-57 slice 3 (concurrent Thinker) queued
  behind P0.
