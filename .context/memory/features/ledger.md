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
- **adr-19-task-aware-context** — started 2026-08-12 · active · P0 implemented (Sessions 160-163: 17b3624/42053dd/89f5d77/53210be — context_policy + dispatcher task_type, compactor v2, summarizer v2 + decision preservation, loop/engine wiring; 1407 tests green) · live smoke provider-blocked (Zen 429, see manifest.md) · P1-P3 pending
- **adr-20-error-normalization** — started 2026-08-12 · active · Session 165 (design + backend normalizer) · finished —
- **adr-21-provider-agnostic-errors** — started 2026-08-12 · active · Session 169 (design + provider-envelope classifier) · finished —
