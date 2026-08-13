# Current Task

- **Session:** 186 (2026-08-13, complete)
- **Feature:** adr-19-task-aware-context (post-close re-key hardening)
- **Task:** Re-key ADR-19 level-aware memory retrieval on the task_type the
  agent settles on during planning, instead of the dispatcher's hint
  (Session 185 post-merge finding).
- **Done (186):**
  - `resolve_task_type(hint, intent=...)` now drives ALL ADR-19 consumers
    (`_settled_task_type` in the engine, settled in the loop's planning
    phase); 'chat' hint on a non-CHAT routing is corrected to the intent
    fallback; `recall_decisions` keyed per settled task type.
  - Full backend **1635 green**, ruff clean, code-reviewed.
- **Next:** Dispatcher accuracy improvement for free-tier models (the 3/8
  prompts misclassified as CHAT in the 184 smoke). Separate session.
- **Also pending:** ADR-8 agent-centric routing Phases 2-4 (build_context
  wiring, agent-initiated delegation, task-type classifier).
