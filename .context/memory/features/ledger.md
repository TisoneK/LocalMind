# Feature Ledger (append-only — permanent, one line per feature)

One line per feature ever — slug, started, outcome, finished. The
append-only guarantee protects the ledger; the feature directory is
working state, like `tasks/current.md`. A feature directory may be
archived or deleted **only after** its ledger line records the outcome
(merged `<sha>` / abandoned + reason) and the finish date.

<!-- TEMPLATE — copy below the last entry:
- **<slug>** — started YYYY-MM-DD · <merged <sha> | abandoned: <reason> | active> · finished YYYY-MM-DD | —
-->

- **agent-loop-closed-loop** — started 2026-07-26 · active · finished —
- **adr-8-agent-centric-routing** — started 2026-07-27 · active · finished —
- **adr-8-agent-centric-routing** — started 2026-07-27 · merged 672d0c8 (Phase 4) + 5deaece/6a76bd6/a91baa4 (Phases 1-3) · finished 2026-07-27 (all 4 phases shipped in Session 34; real-model smoke tests pass on Zen/deepseek-v4-flash-free; 497 tests pass; see manifest.md for the full per-phase breakdown)
- **verification-first-hardening** — started 2026-08-12 · active · P0 implemented (Sessions 155-157: d55c0e6/63dd038/e7d7df1 — TaskState + verify.py + real is_done + success_criteria schemas + final-answer gate + explicit replan; 1358 tests green) · live smoke provider-blocked (Zen 429, see manifest.md) · P1-P3 pending
- **adr-19-task-aware-context** — started 2026-08-12 · design proposed (Session 159 — task-aware Context Planner: policy_for(task_type) → MUST KEEP/SHOULD RETRIEVE/CAN SUMMARIZE/CAN DISCARD; selective compactor v2 + task-aware summarizer v2 with decision-line preservation; builds on ADR-17/18; four open decisions pending user lock) · no code yet
