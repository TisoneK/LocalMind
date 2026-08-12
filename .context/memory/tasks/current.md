# Current Task

- **Session:** 164 (2026-08-12)
- **Feature:** adr-19-task-aware-context
- **Task:** ADR-19 P0 — task-aware context management, implemented and live-smoke attempted (provider-blocked).
- **Done (159-164):**
  - **159**: design doc (Context Planner: policy_for(task_type) → MUST KEEP /
    CAN SUMMARIZE / CAN DISCARD) + four decisions locked by the user.
  - **160** (`17b3624`): `context_policy.py` — pure ContextPolicy dataclass,
    per-task KEEP tables (debug/plan/code/research/chat/verify), legacy
    no-op default, case-insensitive marker semantics, `resolve_task_type`
    priority, `parse_task_type_from_plan`; `OrchestrationPlan.task_type`;
    dispatcher execution_plan schema + malformed-plan guard.
  - **161** (`42053dd`): `simplify_tool_results(policy=...)` — newest
    keep_last ∪ up to max_keep old marker-matched results stay verbatim;
    CAN-DISCARD implemented but OFF for every policy_for() result;
    byte-identical legacy path for None/default.
  - **162** (`89f5d77`): `maybe_compress_history(policy=...)` — per-task
    summary prompts + decision-line preservation (kept lines verbatim in a
    [Preserved decisions] block, extracted from RAW content, bounded 8/200/
    1200); failure semantics unchanged.
  - **163** (`53210be`): wiring — `AgentLoop.run(task_type)` resolves the
    policy from the dispatcher-resolved value only (deviation documented
    in design.md §7) and feeds the compactor; engine threads it to both
    loop call sites + all three summarizer calls. Default no-op.
  - **164**: full suite **1407 green**, ruff clean. Live smoke
    (`scripts/smoke_gate.py` + task_type check) verified the pipeline to
    the provider call → Zen 429 FreeUsageLimitError. **Live E2E
    provider-blocked** (same as 2026-08-11/12) — retry when Zen recovers
    or install Ollama.
- **Next:** P1 — context hierarchy (turn → session → project → long-term)
  with retrieval-by-level; P2 — cross-session decision ledger; P3 — LLM
  value-scoring. Secondary pending: B-2026-08-12-4 (live two-turn UI
  check); ADR-18 P1-P3 (verifier-as-stage, failure memory, transitional
  wiring).
