# Current Task

**Status:** IDLE — Session 320 (fix B.AI model ID casing + context windows, ADR-55 correction) shipped; live smoke still blocked on key.

## Session 320 outcome — B.AI "not working" root cause fixed

- **Target:** "b.ai in LocalMind is wrong / not working".
- **Root cause (Session 319 bug, not a domain issue):** I used the DISPLAY
  names (`DeepSeek-V4-Flash`, `Hy3`) as API model IDs and guessed a context
  window. B.AI's model IDs are LOWERCASE (`deepseek-v4-flash`, `hy3`), and
  the windows are `deepseek-v4-flash` = 1,000,000 and `hy3` = 256,000
  (docs.b.ai/llmservice/models/<model>). Base URL `https://api.b.ai/v1` +
  Bearer auth were already correct; the `bankofai.io`↔`b.ai` split is the
  chat web app, not the API.
- **Fixed:** `default_model` → `deepseek-v4-flash`; context windows corrected
  (128000→1000000, added `hy3`=256000); test pins the lowercase IDs + windows.
- **Verification:** 203 targeted tests pass; ruff clean. NOT live-verified —
  no `bai` key in `settings.json` (active provider is still z.ai).

## Next

- **ADR-55 live smoke (blocked on key):** paste the key or enter it in
  Settings so `/v1/models` + a chat trace can confirm `deepseek-v4-flash`/`hy3`.
- **B-2026-08-20-10 (High):** MiniMax XML interception conflicts with prose-commitment detector.
- **B-2026-08-20-11 (Medium):** 429 on iter=1 → empty bubble.
- **B-2026-08-20-19 (Low):** fix broken test-import in `test_parent_recovery_cap.py`.

**Feature:** none (single-session config fix)
**ADR:** ADR-55 (B.AI provider, corrected), ADR-54, ADR-53, ADR-52
**Review:** `.context/memory/reviews/2026-08-20-review-86.md`
