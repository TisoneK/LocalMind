# Current Task

- **Session:** 159 (2026-08-12)
- **Feature:** adr-19-task-aware-context
- **Task:** Design ADR-19 — task-aware context management (user picked
  "Design ADR-19 now" after the context-window thread).
- **Done (159):** grounded the design in the actual code (context_builder
  budget math + single assembly point at _pipeline.py:1546/2696/2901;
  context_compactor keep-last-4 positional stub; summarizer 75%/oldest-50%
  single generic prompt; memory compose/warm_start_facts/consolidate;
  per-agent context builders; TaskState.phase as the task-type carrier;
  Session 150 context-window meter; ADR-17 floor tests) and wrote
  `features/adr-19-task-aware-context/design.md` — the **Context Planner**:
  `context_policy.py` (pure dataclasses, policy_for(task_type), default
  = legacy no-op), selective compactor v2 (MUST KEEP / CAN STUB / CAN
  DISCARD by content markers, protocol invariants preserved), task-aware
  summarizer v2 (per-task summary prompts + decision-line preservation so
  the PostgreSQL/MongoDB constraint case survives), builder + loop wiring
  (smallest change; budget math untouched), 6-step build order, no-
  regression list, explicit out-of-P0 (hierarchy, decision ledger, LLM
  value-scoring).
- **Next:** the user's four decisions (design.md §7) → design LOCK → then
  implement build order steps 1-4 (deterministic, no live model needed):
  context_policy.py → compactor v2 → summarizer v2 → wiring. Live smoke
  reuses scripts/smoke_gate.py when a provider recovers (Zen 429 as of
  Sessions 151/158). Secondary pending: B-2026-08-12-4 (Session 151
  carry-over — live two-turn UI check); ADR-18 P1-P3 (verifier-as-stage,
  failure memory, transitional wiring).
