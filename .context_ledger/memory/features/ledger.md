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

- **adr-19-task-aware-context** — started 2026-08-12 · **COMPLETE** — all phases shipped: P0 (Sessions 160-163) + P1 hierarchy/level-aware retrieval (177, 5f4f8a8) + P2 decision ledger (178, c348633) + P3 LLM value scoring opt-in (179, e2caafb) · full suite 1550 green · live smoke Zen-429 blocked (flaw log)

- **realtime-alive-ui** — started 2026-08-14 · active · finished — (multi-session frontend overhaul: make actions/todos/terminal/tools/agents/chat/thinking feel alive & async, matching uploaded `ui_improvement/` screenshots; S210 live Actions timeline)

- **realtime-alive-ui** — started 2026-08-14 · **implementation COMPLETE** — 7 sessions S210-216 shipped to main (push-to-main policy, no single merge sha): S210 chat Actions timeline `3ba4945`, S211 thinking stream `779eda3`, S212 todos checklist `cd02072`, S213 panel action trace `7392c73`, S214 agents workspace `b2bd48e`, S215 terminal cursor `21f88db`, S216 shared motion primitive `fb86e25` (ADR-30). Every user-named surface is alive & async; motion vocabulary unified + reduced-motion by construction. 173 frontend tests / tsc / lint(0 err) / build green. Only follow-up: live-app visual verification vs `ui_improvement/*.png` (provider-credential blocked). · finished 2026-08-14 (implementation)

- **theming-multi-palette** — started 2026-08-14 · active · finished — (3 palettes Graphite/Iris/Warm × light+dark, user-selectable in Settings; reverses Session-103 dark-only; S217 token architecture + 6 palettes)

- **theming-multi-palette** — started 2026-08-14 · **COMPLETE** — S217 token architecture + 6 palettes `40930e0` (ADR-31) + S218 switcher/Settings picker `810323b` + S219 light-mode correctness `6979fe3`. 3 themes (Graphite/Iris/Warm) × light/dark, Settings-selectable + persisted + no-flash. 178 frontend tests / build green. Palettes v1 — tunable in globals.css anchors; human visual pass is the only follow-up. · finished 2026-08-14

- **fail-fast-provider-errors** — started 2026-08-14 · active · S220 adapter-level fix `1762509` (ADR-32); loop-level short-circuit backlogged B-2026-08-14-5 · finished —
- **fail-fast-provider-errors** — started 2026-08-14 · merged `1762509` + `6014254` · finished 2026-08-14 (ADR-32 complete; adapter + parent-loop fail-fast and canonical error propagation; see feature manifest)
- **system-search-tool** — started 2026-08-25 · active · finished — (Local Search Intelligence Phase 1: unified system_search tool for the Parent — files/recent/largest/duplicates/apps/open_with operations with normalized, bounded, security-gated results)
- **p0-context-engineering** — started 2026-09-03 · active · S410-412 reductions (`ec5521c`/`1bbe2e6`/`a1e7c68`) + S414/S415 research (`4cce4f6`/`c0de368`); addendum-confirmed 8-step plan, S416 executing Step 1 (cache data → UI) —
