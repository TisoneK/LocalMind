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
- **explorer-tool** — started 2026-09-10 · active (design shipped at `docs/explorer_tool_design.md`, awaiting owner approval; implementation is the next session) · finished —

- **explorer-tool** — started 2026-09-10 · **SHIPPED (not yet finished)** — S462 implementation `9d85df0f`..`d1b88465` + design status + changelog; 22 unit tests green; weak-model gate passed on zai/glm-4.5-flash (list/tree/stat picks + system_search/shell non-regression); grep_search re-verify + zen/bankofai retry carried as B-2026-09-10-7; ledger line completes when that verdict lands.

- **explorer-tool** — started 2026-09-10 · **COMPLETE** — S462 implementation `9d85df0f`..`d1b88465` (tool + intent + registry + lean CORE schema + scopes + routing + steering + 22 unit tests + live harness). S464 closed the carried gate on the protocol's PRIMARY provider (bankofai/qwen3.8-flash; harness model pin `aa08cd5`): list/tree/stat selection 3/3 PASS, `system_search` + `shell` non-regression PASS, and the open content-search question ANSWERED — `dir_explorer` does NOT bleed into content search (the model chose `shell` + a bounded `grep`), so the design's LONG_TAIL fallback is NOT required. The harness's `grep_search` expectation is unsatisfiable because that tool sits in no model-facing tier — a pre-existing wiring gap split out as B-2026-09-10-8, not a dir_explorer regression. Phantom `grep_search` pointer removed from the description the model sees (`ef1c7cd`); stale CORE tool-count pin fixed (`e61fd9f`). · finished 2026-09-10

- **context-usage-breakdown** — started 2026-09-15 · active · finished — (S004: split the last-call context occupancy into per-category shares — system prompt, tool schemas, turn context, history, tool results, current message — and surface them in the UI meter; observability only, no prompt-content changes)

- **context-usage-breakdown** — started 2026-09-15 · **COMPLETE** — S004 shipped `c7414ee1` (estimator + loop/chat wiring + 10 unit tests) .. `842d0e7d` (changelog): clickable occupancy meter opens per-category shares of the last model call, scaled to the provider-reported total; live-verified zai/glm-4.5-flash (sum == prompt_tokens exactly, tool schemas ≈44% of a weather turn). · finished 2026-09-15

- **memory-write-path** — started 2026-09-17 · active — S014 shipped the typed, verified write path: a durability gate in code (volatile values refused, stable facts tagged with freshness/confidence), one row per fact via a canonical key, every mutation confirmation built from a read-back, an id-bearing list, and deletion that resolves id / id-prefix / re-worded content / key. Live before/after on zai/glm-4.5-flash (IP+ISP stored → refused; a fact stated twice → one row). The boot-refresh consumer of the freshness tags stays parked with the geolocation bootstrap it belongs to.

- **user-context-deduction** — started 2026-09-19 · **COMPLETE** — S018 shipped B-2026-09-15-13 (ADR-65): `core/user_context.py` trust-tier fusion (Windows user geo setting > IANA zone > locale tag > keyboard layouts), boot deduce + persist through the ADR-63 keyed path ("My country" → `subject:location`, STABLE_FACT/boot), deduction asserted on all three answering surfaces (bootstrap block, per-turn env line, direct-chat funnel), 23 unit tests; live before/after on zai/glm-4.5-flash (hedge → "Kenya (KE)", 0 tools; region-implicit weather turn targeted accuweather.com/en/ke/nairobi/). Merged `ce89d042` (main at `ff24e713`). Delivers the boot-refresh consumer S014's memory-write-path line parked with the geolocation bootstrap. · finished 2026-09-19
- **stage-prompts** — started 2026-09-19 · active (BACKLOGGED until a second model is available; groundwork shipped, see manifest) · finished —

- **state-engine** — started 2026-09-21 · active — a state-driven agent engine built beside the classic parent (ADR-71): slice 1 (`core/state_engine/` — the engine owns immutable state, the model proposes moves and scores outcomes, simulation is real read-only probing, beam-of-one with backtracking, a hard budget with an honest stop) plus the backend-served State Explorer (`GET /state-explorer`, SSE `POST /api/state-engine/run`, build-free page) are on main and live-verified on deepseek-chat; the in-app React explorer and the Classic/State engine selector were in flight at the office-002 close. Slices and shipped detail: `features/state-engine/manifest.md`. · finished —
