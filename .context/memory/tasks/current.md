# Current Task

- **Session:** 179 (2026-08-13, in progress)
- **Feature:** adr-18-verification-first-hardening (continuing)
- **Task:** Sessions 4-8 of the user's "agentic workflow" target — F4-F8
  from the Session 176 audit roadmap. Plus the real-model smoke
  verification deferred from Sessions 177-178.
- **Live smoke verification (2026-08-13):**
  - ZEN_API key works against opencode.ai/zen/v1 (the `zen` provider
    endpoint). Free models verified reachable:
    `nemotron-3.5-lightning-free`, `laguna-s-2.1-free`,
    `ling-3.0-tiny-free`. (`deepseek-v4-flash-free` and
    `mimo-v2.5-free` are rate-limited as of 2026-08-13.)
  - Real chat smoke ("Reply with the single word: OK") → PASSED.
    Full pipeline: dispatcher→intent_classified→token→turn_complete→done.
    Provider: nemotron-3.5-lightning-free via Zen.
  - Real agentic smoke ("List the files in /tmp") → PASSED.
    Dispatcher signal-detected shell intent (no LLM call), ADR-8 Phase 4
    selected coding agent, tool call `shell ls /tmp` executed
    successfully (12ms), tool result rendered.
  - Sessions 177-178 changes (GoalInterpreter + orchestrator.replan
    wiring) are live in production paths.
- **Next:** Session 179 — F4 Mandatory Verifier post-execution stage.
  Even when no success_criteria exist, the loop must run at least one
  observable check (file exists, exit code, no errors) before accepting
  "done". Closes the gap that "model says wrote X" ends the turn with
  no verification.
