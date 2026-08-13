# Current Task

- **Session:** 184 (2026-08-13, complete)
- **Feature:** adr-22-agent-first-routing
- **Task:** ADR-22 implementation + real-model smoke verification.
- **Done (184):**
  - ADR-22 written + 3 code changes + test updates.
  - 1573 backend tests pass; ruff clean.
  - Real-model smoke: 8 diverse prompts across all tool categories.
    - 5/8 entered the agent loop → ALL 5 had agent planning (ADR-22 works).
    - 3/8 were misclassified as CHAT by the dispatcher (free-tier model limitation — separate issue).
    - Signal fast-path (shell/git) still triggers BUT the agent now plans after it — the hint mechanism handles it correctly.
    - Acceptance gate passed on all 5 agent-loop prompts.
  - UI screenshots captured via Playwright Python (agent-browser can't reach localhost).
  - Inefficiencies logged: bash tool timeout + port TIME_WAIT.
- **Next:** Dispatcher accuracy improvement for free-tier models (the 3/8 misclassified prompts). Separate session.
- **Also pending (from merged ADR-19 branch):** ADR-8 agent-centric
  routing Phases 2-4 (build_context wiring, agent-initiated delegation,
  task-type classifier).
