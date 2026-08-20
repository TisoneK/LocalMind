# Current Task

**Status:** IDLE — Session 305 (B-2026-08-20-1) completed; ready for Session 306.

## Completed (Session 305)
- Implemented `ParentSession` (rolling summary + bounded recent tail) in `core/parent_session.py`.
- Added migration 009 (`parent_sessions` table) + `SessionStore.save_parent_session` / `get_parent_session`.
- Wired ParentSession into `agent_runtime`: loaded at turn start, summary injected as a system message before the recent tail, updated + persisted after turn completion.
- Added `parent_ready` / `parent_degraded` / `parent_recovered` readiness telemetry — queued by `_ensure_parent_kernel`, drained onto the first turn's ObsCollector, surfaced in `/api/health` and `/api/observability/{sid}`.
- 13 ParentSession unit tests + 6 readiness telemetry tests; 1023 broad regression tests pass.
- Live-verified on real z.ai/glm-4.5-flash via isolated 8765 harness: boot ready log, `/api/health` parent_ready=true, first-turn SSE parent_ready event, 3-turn conversation persists turn_count across backend restart.
- ADR-54 records the design; review-72 records the implementation + live evidence.

## Next Parent-only implementation slices
- **B-2026-08-20-2 (Session 306):** clean GLM native tool trace after provider recovery — live-verify `describe_tool` → real tool call → grounded completion on z.ai/glm-4.5-flash (rate-limit window should now be clear).
- **B-2026-08-20-3:** continue maturing the single Parent before reconsidering children (ADR-53).
- Frontend: render `parent_ready` / `parent_degraded_reason` in StatusBar (backlogged).
- Tune compaction thresholds (`RECENT_TAIL_MAX`, `SUMMARY_MAX_CHARS`) based on real long-conversation workload (backlogged, low-priority).

**Feature:** none (idle)
**ADR:** ADR-54 (ParentSession + readiness), ADR-53 (Parent-only), ADR-52 (warm kernel)
**Review:** `.context/memory/reviews/2026-08-20-review-72.md`
