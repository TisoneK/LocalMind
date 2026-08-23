# Current Task

**Status:** IDLE — Session 367 shipped the Memory tab wiring (B-2026-08-23-14 done).

## Session 367 outcome — Memory tab connected + WAL busy race fixed

- **Task:** connect the Memory tab UI to the real memory backend — show facts, filter, delete, store affordance, live refresh. The tab already listed + deleted; the gaps were store (storeFact was dead code), filter, empty state, and live refresh (facts stored mid-session never appeared).
- **Frontend:** MemoryTab gained a store-fact textarea/button (POST /api/memory), a filter box (content/source), empty + filter-empty states, and a 4s polling refresh while visible; RightPanel/WorkspaceLayout thread storeFact + refreshMemory.
- **Backend bugs found live (real root causes):**
  1. **WAL snapshot-upgrade race** — `_persist`'s deferred BEGIN → dedup read → INSERTs fails INSTANTLY with SQLITE_BUSY if any other connection commits in between (busy_timeout doesn't apply to snapshot upgrades). The shared localmind.db made this intermittent 503s on POST /api/memory and silent drops of the agent's fact writes. Fixed with `BEGIN IMMEDIATE` (write lock up front; WAL still allows readers). Repro: 1/20 concurrent stores failed before, 0/20 after.
  2. **Timestamp always 0** — route read `created_at` but metadata carries `timestamp`; fixed.
  3. **Delete of missing fact returned True** — `forget_by_id` now returns False (DELETE 404 + truthful memory_op).
- **Verification:** 3 vector-race + 5 memory-API + 8 MemoryTab tests; 2426 backend / 310 frontend, ruff/tsc/eslint clean. Live (isolated 8765, bankofai): list-empty → POST → list shape → DELETE → DELETE missing → 404, all verified.
- **Env note:** user's Ollama only has mxbai-embed-large pulled but the default `ollama_embed_model` is nomic-embed-text — memory stores silently fail until the model is pulled or settings.json sets embed_model.
- **Next:** B-2026-08-23-15 (auto-switch between Terminal/Agents/Memory tabs) or B-2026-08-23-16 (deeper Files browser) — both open in backlog.
