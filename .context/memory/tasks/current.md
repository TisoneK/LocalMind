# Current Task

**Status:** IDLE — Session 319 (add B.AI provider, ADR-55) shipped; config-only, unit-tested, live smoke BLOCKED on missing key.

## Session 319 outcome — B.AI provider added (ADR-55)

- **Target:** "new provider" — B.AI (docs.b.ai), per the user's research brief.
- **Shipped (config-only, like ADR-9/ZenMux):**
  1. `bai` `ProviderConfig` (`https://api.b.ai/v1`, `BAI_API_KEY`/`BAI_MODEL`,
     `bai_model`, default `DeepSeek-V4-Flash`) + `DeepSeek-V4-Flash: 128000`
     context window in `openai_compat.py`.
  2. `bai_model` settings field + `"bai": "BAI_API_KEY"` env map in `config.py`.
  3. `bai` in the SettingsModal provider picker + `.env.example`.
  4. **Consolidation fix:** `models.py` `_model_setting_attr` /
     `_build_model_setting_map` + `health.py` `model_setting_map` now DERIVE
     from `PROVIDER_CONFIGS` — this fixed a latent ZenMux drift (ADR-9's entry
     was silently missing from models.py's two hardcoded maps).
  5. New `tests/api/test_provider_registry.py` (4 tests) locking the no-drift
     invariant.
- **Verification:** backend 2069 passed / 1 pre-existing unrelated failure
  (`test_parent_recovery_cap.py` broken test-import, Session 310 — backlogged
  as B-2026-08-20-19); ruff clean; frontend tsc + SettingsModal tests green.
- **NOT live-verified — BLOCKED:** no B.AI API key on this machine. Per the
  Session 31/33 flaw log, ADR-55 is marked "IMPLEMENTED BUT UNTESTED". Smoke
  steps documented in ADR-55.

## Next

- **B-2026-08-20-10 (High):** MiniMax XML interception conflicts with prose-commitment detector.
- **B-2026-08-20-11 (Medium):** 429 on iter=1 (before any tool) → empty bubble.
- **B-2026-08-20-19 (Low):** fix broken test-import in `test_parent_recovery_cap.py`.
- **ADR-55 smoke test:** live-verify B.AI once a key is available.

**Feature:** none (single-session config addition)
**ADR:** ADR-55 (B.AI provider), ADR-54 (ParentSession), ADR-53 (Parent-only), ADR-52 (warm kernel)
**Review:** `.context/memory/reviews/2026-08-20-review-85.md`
