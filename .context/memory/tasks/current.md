# Current Task

**Status:** IDLE — Session 344 fixed the multi-turn honesty gaps (B-2026-08-22-1/-2 done).

## Session 344 outcome — pressured re-ask guard (deterministic multi-turn refusal)

- **Fix:** `pre_init_classifier.py` — new guard: current message matches re-ask pressure cues ("just guess", "check your memory", "I'm sure I told you/you know"…) AND no fresh interrogative AND history shows a prior refusal (or hallucination-class user turn) → deterministic `direct` refusal. `loop.py` passes the prior turns into `classify_pre_init(message, history=...)`. Backward compatible (history=None → inert).
- **Tests:** 7 unit + 1 loop-wiring test; full backend suite **2301 pass / 0 fail / 2 skip**; ruff zero new violations.
- **Live before/after (bankofai, isolated 8765):** CONV-11 T2 "just guess" 9.1s fabricated story → **0.2s "I already told you…" refusal**. CONV-12 T2 "check your memory" 87.9s/8-tool scan → **0.2s refusal, 0 tools**.
- **Next:** B-2026-08-22-3 remainder (CONV-05 T1 narration variance + CAT2 benchmark criteria artifact), B-2026-08-22-4 (verify/downgrade empty-text finding), and the 332-340 sessions.md bookkeeping gap.

**Feature:** none
