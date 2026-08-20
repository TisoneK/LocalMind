# Current Task

**Status:** IDLE — Sessions 309-310 (frontend parent-degraded indicator + parent recovery cap raise) shipped.

## Sessions 309-310 outcome
- **Session 309 (B-2026-08-20-4):** frontend parent-degraded indicator in CenterPanel status bar. Amber dot + tooltip when `parentReady === false`. 5 new render tests; 262 frontend tests pass; tsc clean; eslint 0 errors / 71 existing warnings.
- **Session 310:** raised `_MAX_EMPTY_REASONING_RECOVERIES` from 2 to 3 for parent turns (new `_MAX_EMPTY_REASONING_RECOVERIES_PARENT = 3`). The non-parent cap stays at 2. 3 new tests; 1035 broad regression pass; ruff clean.
- Neither was live-verified on the real model (z.ai free tier ~30s/iter exceeds tool-call budget) — both are unit-tested + conservative + no-regression.
- review-76 records both implementations.

## Next: recovery & speed (user's focus)
- **B-2026-08-17-10 (next session):** overlap init LLM call with memory retrieval — latency win. Memory is serial in front of the init call on turn 2+; the init doesn't use memory_facts. Hoist init ahead of the memory await.
- **B-2026-08-17-11 (risky):** fold classify + first action (3 calls → 2) — biggest per-turn latency win. Revive the dormant `initial_tool_result` path; pre-dispatch only high-confidence whitelist read-only actions. Needs live A/B on accuracy.
- **B-2026-08-20-9:** shell tool should hint plain-string form on JSON-wrapped input.
- **B-2026-08-20-3:** continue maturing the single Parent (ADR-53).
- **B-2026-08-20-5:** tune ParentSession compaction thresholds.

**Feature:** none (idle)
**ADR:** ADR-54 (ParentSession), ADR-53 (Parent-only), ADR-52 (warm kernel)
**Review:** `.context/memory/reviews/2026-08-20-review-76.md`
