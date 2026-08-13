# Current Task

- **Session:** 183 (2026-08-13, in progress)
- **Feature:** adr-18-verification-first-hardening (continuing)
- **Task:** Session 183 — F6-F9 cleanup + final real-model smoke.
- **Done (182):** Investigated F5 (open up WorkspaceOrchestrator);
  SKIPPED with documented rationale. The audit's F5 was a
  misclassification — the orchestrator's exclusion of AGENT_INTENTS
  is a deliberate architectural decision (Sessions 31-32) to prevent
  fabrication on small models. The structured-planning benefits the
  audit thought F5 would provide are now in the agent loop path
  (Sessions 177, 179, 180) where AGENT_INTENTS actually run.
- **Next:** Session 183 — F6-F9 cleanup:
  - F6: 4 dead is_done stubs (browser/analyst/debugger/reviewer) →
    promote to criteria_gate (one-line change each, same pattern as
    coding/verifier from Session 173-174).
  - F7: 4 dead orchestrator_replan_* obs events — RE-ENABLED in
    Session 178 (no longer dead).
  - F8: dead _plan non-streaming variant at loop.py:4354 — delete.
  - F9: undocumented memory merge at _pipeline.py:1974-1990 — add
    docstring.
  - Plus: final real-model end-to-end smoke test against
    nemotron-3.5-lightning-free.
