# Current Task

**Status:** IDLE — Session 370 shipped the per-fact edit action in the Memory tab.

## Session 370 outcome — edit stored facts

- **User request:** add a per-fact edit action so users can correct stored facts.
- **Backend:** `VectorStore.update_content` re-embeds the corrected text (WAL-safe BEGIN IMMEDIATE), migrates to the new content-derived id, preserves original metadata (source, timestamp); `PATCH /api/memory/{fact_id}` returns the new id, 404 on missing.
- **Frontend:** pencil Edit button on each fact card → textarea with Save/Cancel (spinner, inline error); `editFact` re-fetches the list since the id changes; threaded via `onMemoryEdit`.
- **Verification:** 2 VectorStore + 2 route + 3 MemoryTab tests; 2433 backend / 319 frontend; ruff/tsc/eslint clean. Live (isolated 8765): store → PATCH → list shows correction with new id, source/timestamp preserved; missing-fact PATCH → 404.
- **Next:** B-2026-08-23-15 (auto-switch between Terminal/Agents/Memory tabs) or B-2026-08-23-16 (deeper Files browser) — both open in backlog.
