# Current Task

**Status:** IDLE — Session 371 shipped the Memory recall search + fixed the memory-collapse bug.

## Session 371 outcome — recall search + a long-standing silent memory bug

- **User request:** add a recall/search box in the Memory tab showing the top-k most relevant facts for a query.
- **Feature:** `GET /api/memory/search?q=&top_k=` (semantic, frontend MemoryFact shape, relevance = 1 - distance); MemoryTab **Recall** box → top-5 with relevance bars (edit/delete work on results), Clear + no-results states; client `searchMemory`.
- **THE BIG ONE (found live):** storing 3 distinct facts left only 1 in the DB — vec0 returns **Euclidean L2 distance** but the dedup + recall code treated it as a dot product (`_cosine_to_score`), so the `< 0.15` dedup threshold clamped almost any pair to ~0 and merged distinct facts into one row. The agent's memory had effectively been ONE fact. Fix: `_l2_to_score(l2) = min(1, l2²/4)` at both call sites. Regression test fails on old code / passes on the fix.
- **Verification:** +1 store regression, +3 route, +3 MemoryTab tests; 2437 backend / 322 frontend; ruff/tsc/eslint clean. Live (isolated 8765): 3 facts survive, recall ranks dark-mode facts (≈0.81) above FastAPI (0.72).
- **Next:** B-2026-08-23-15 (auto-switch between Terminal/Agents/Memory tabs) or B-2026-08-23-16 (deeper Files browser) — both open in backlog.
