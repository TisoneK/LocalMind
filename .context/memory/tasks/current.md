# Current Task

**Status:** IDLE — Session 322 (rename B.AI provider bai → bankofai, drop "bai") shipped.

## Session 322 outcome — provider key renamed; 404 root cause found

- **Target:** "Still referencing bai? Failing with 404 — I said drop bai."
- **Renamed:** `bai` → `bankofai` everywhere (ProviderConfig key/name,
  `config.py` `bankofai_model` + env map, `models.py` listable tuple,
  `SettingsModal.tsx` id, `.env.example`, `test_provider_registry.py`).
  Env vars `BAI_API_KEY`/`BAI_MODEL` → `BANKOFAI_API_KEY`/`BANKOFAI_MODEL`.
- **404 root cause:** the still-running OLD backend re-wrote
  `model: DeepSeek-V4-Flash` back into `settings.json` (overriding the
  Session 321 lowercase fix) and sent the case-mismatched ID → model_not_found.
  Migrated `settings.json` (`adapter` + `api_keys.bai` → `bankofai`) and
  re-fixed `model` → `deepseek-v4-flash`.
- **Verification (live):** `OpenAICompatAdapter(provider="bankofai")` →
  base `https://api.bankofai.io/v1`, model `deepseek-v4-flash`,
  `list_models()` = 38, `chat()` → "PONG". Full backend 2071 passed / 1
  pre-existing failure (`test_parent_recovery_cap.py`); ruff clean; tsc clean.
- **⚠ User action required:** restart the backend/app — the running process
  is old code and will keep clobbering the fix until restarted.

## Next

- **B-2026-08-20-10 (High):** MiniMax XML interception conflicts with prose-commitment detector.
- **B-2026-08-20-11 (Medium):** 429 on iter=1 → empty bubble.
- **B-2026-08-20-19 (Low):** fix broken test-import in `test_parent_recovery_cap.py`.

**Feature:** none (single-session config rename)
**ADR:** ADR-55 (B.AI → BankOfAI provider, renamed + live-verified), ADR-54, ADR-53, ADR-52
**Review:** `.context/memory/reviews/2026-08-20-review-88.md`
