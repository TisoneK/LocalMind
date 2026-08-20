# Current Task

**Status:** IDLE — Session 321 (switch B.AI to api.bankofai.io + live-verify, ADR-55) shipped.

## Session 321 outcome — B.AI now live-verified on bankofai.io

- **Target:** "Drop b.ai and use bankofai.io" — B.AI in LocalMind still
  "not working".
- **Root causes (two):** (1) the canonical API domain moved from `api.b.ai`
  to `api.bankofai.io`; (2) the user's `settings.json` still held the stale
  Session 319 model `DeepSeek-V4-Flash`, which OVERRODE the Session 320
  lowercase default → `model_not_found`.
- **Fixed:** base URL → `https://api.bankofai.io/v1`; display name →
  `BankOfAI (promo free models — time-limited)`; removed the misdiagnosed
  browser-UA header (Cloudflare 403 only blocks stdlib urllib's
  `Python-urllib/*` UA, not httpx's `python-httpx/*`); corrected
  `settings.json` `model` → `deepseek-v4-flash`.
- **Verification (live):** `GET /v1/models` → 38 lowercase model IDs
  (`deepseek-v4-flash` present, `hy3` ABSENT); `deepseek-v4-flash` chat →
  200 "PONG"; `DeepSeek-V4-Flash` → 404 model_not_found. End-to-end through
  the real adapter (`OpenAICompatAdapter(provider="bai")`) → 38 models +
  "PONG". Full backend 2071 passed / 1 pre-existing failure
  (`test_parent_recovery_cap.py` broken `tests.` import); ruff clean; tsc clean.

## Next

- **B-2026-08-20-10 (High):** MiniMax XML interception conflicts with prose-commitment detector.
- **B-2026-08-20-11 (Medium):** 429 on iter=1 → empty bubble.
- **B-2026-08-20-19 (Low):** fix broken test-import in `test_parent_recovery_cap.py`.
- **Optional:** rename provider key `bai` → `bankofai` (needs key/env migration; deferred).

**Feature:** none (single-session config fix)
**ADR:** ADR-55 (B.AI provider, live-verified), ADR-54, ADR-53, ADR-52
**Review:** `.context/memory/reviews/2026-08-20-review-87.md`
