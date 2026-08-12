# Current Task

- **Session:** 158 (2026-08-12)
- **Feature:** verification-first-hardening
- **Task:** P0 acceptance gate (B-2026-08-12-1) — implemented, tested, live-smoke attempted (provider-blocked).
- **Done (155-157):**
  - **155** (`d55c0e6`): `TaskState` (objective/constraints/success_criteria/phase/
    progress/evidence/budget; `to_prompt`/`to_dict`) + deterministic `verify.py`
    checker library (test/build, file, git, http, error-freedom domains +
    evidence-requirement fallback; `check_criterion`/`evaluate_criteria`/
    `gate_passed`/`format_gate_results`); `AgentTrace` gains
    `success_criteria`/`criteria_results`/`gate_passed`/`gate_summary`. 43 tests.
  - **156** (`63dd038`): `AgentLoop.run()` gains `success_criteria` + `is_done_fn`,
    seeds trace, creates+injects TaskState (criteria once, progress/budget
    refreshed per iteration), calls the gate at the iteration head — clean
    return (not hit-limit) on pass; dispatcher parses
    `execution_plan.success_criteria`; `create_plan` tool accepts
    `success_criteria`; `agents/coding/is_done.py` is a REAL gate (run-scoped
    evidence guard — never passes on pre-existing workspace state); engine
    threads criteria to both loop call sites. 12 tests.
  - **157** (`e7d7df1`): `_acceptance_gate_at_final_answer()` gates the model's
    done-claim in both final-answer branches — pass appends "✓ n/n" summary;
    unmet + iterations → explicit LLM replan (`chat()`, time-boxed
    PLAN_TIMEOUT_SECS, failure→re-attempt directive) + injected user block;
    unmet at cap → honest unmet report. `_user_message_text` skips gate blocks
    (multi-replan keeps original task). 6 tests. Reviewer-caught: replan
    timeout + Task degradation, both fixed.
  - **158**: full suite **1358 green**, ruff clean. Live smoke
    (`scripts/smoke_gate.py`) verified pipeline to the provider call
    (context build → dispatcher thinking → Zen 429 FreeUsageLimitError).
    **Live E2E provider-blocked** (Zen free-tier rate limit, same as
    2026-08-11) — retry when Zen recovers or install Ollama.
- **Next:** P1 — promote VerifierAgent from `Intent.VERIFY` routing to a
  per-run acceptance stage + real `is_verifier_done`; re-run
  `scripts/smoke_gate.py` once a live model is available. Secondary pending:
  B-2026-08-12-4 (Session 151 carry-over — live two-turn UI check).
