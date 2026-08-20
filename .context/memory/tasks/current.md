# Current Task

**Status:** IDLE — Session 311 (B-2026-08-17-10) shipped; turn-start latency optimized.

## Session 311 outcome
- Moved the ParentSession DB load into `_gather_nonessential()` (the concurrent task), wrapped in `asyncio.to_thread()`. Removed the duplicate serial load later in `_process_unlocked`.
- **Before:** turn-start latency = memory_await + parent_session_load + adapter_setup (serial).
- **After:** turn-start latency = max(memory, parent_session_load, adapter_setup) — concurrent.
- 2041 broad regression tests pass (1 pre-existing shell brace-expansion env failure, unrelated); ruff clean.
- The original B-2026-08-17-10 backlog item was about overlapping the "init LLM call" — but the Session 302 warm-kernel refactor already eliminated the per-turn init LLM call entirely. What remained was the ParentSession DB load (added Session 305), which this session overlaps. The backlog item is now fully resolved.
- review-77 records the implementation.

## Next: recovery & speed (user's focus)
- **B-2026-08-17-11 (risky, backlogged):** fold classify + first action (3 calls → 2) — biggest remaining per-turn latency win. Revive the dormant `initial_tool_result` path; pre-dispatch only high-confidence whitelist read-only actions. Needs live A/B on accuracy.
- **B-2026-08-17-12 (backlogged):** parent-path create→file_write steering — collapses ~4 LLM calls per create task.
- **B-2026-08-20-9:** shell tool should hint plain-string form on JSON-wrapped input.
- **B-2026-08-20-3:** continue maturing the single Parent (ADR-53).
- **B-2026-08-20-5:** tune ParentSession compaction thresholds.

**Feature:** none (idle)
**ADR:** ADR-54 (ParentSession), ADR-53 (Parent-only), ADR-52 (warm kernel)
**Review:** `.context/memory/reviews/2026-08-20-review-77.md`
