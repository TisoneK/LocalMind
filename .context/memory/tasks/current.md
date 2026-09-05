# Current Task

**Status:** IDLE — Session 424 closed. Experiential Labs provider added
(config-only, ADR-58 / commit `ec9b6b7`): PROVIDER_CONFIGS entry
(https://api.experientiallabs.ai/v1, EXPERIENTIAL_API_KEY, plain Bearer),
Settings field + env map, SettingsModal entry, models.py live-list tuple,
.env.example, MODEL_CONTEXT_WINDOWS["glm-5.3-flash"]=1310720
(catalog-documented), 3 new registry tests (11/11 pass; config_adapter
13/13; SettingsModal 11/11; tsc 0; ruff baseline 32 unchanged). Keyless
probe confirmed the user's research (500-slug public catalog at /api/models;
keyed /v1/* → 401 invalid_key; 429 insufficient_quota non-transient —
already covered by _PERMANENT_QUOTA_MARKERS).

**Feature:** none

## Notes for the next session

- **ADR-58 smoke test OWED (top of queue when a key exists):** the provider
  is implemented but NOT live-verified — no xpl_ key on this machine. Steps:
  (a) keyed `GET https://api.experientiallabs.ai/v1/models` → confirm slugs +
  metadata; (b) isolated-8765 `/api/chat` with LOCALMIND_ADAPTER=experiential
  (copy settings.json w/ key into the scratch home; never print values);
  (c) verify tool calls + streaming end-to-end; then mark ADR-58 tested.
  User was told: after adding the key, RESTART the backend (the pre-restart
  "Unknown provider" save error was the stale process, not a code bug).
- **Possible UX follow-up:** wire the keyless `/api/models` public catalog
  as a model-listing fallback so the selector isn't just the default before
  a key is entered — deferred, needs design (nested non-OpenAI shape).
- **Standing P0 queue (unchanged):** Step 4 (tool-result FTS5+vec0 index +
  search), Step 5 (Context Budget Manager), Steps 6-8; Step 3 live
  prompt-audit owed.
- **Deferred file-reading items (B-2026-09-05-1..3)** and the
  **~23-failure Windows backend baseline peer pass** (B-2026-09-05-4)
  remain; frontend **eslint drift (9 errors + 84 warnings)** still fails the
  exit gate on main — needs the deferred peer pass.
- **Live-test providers:** bankofai free = hy3 / glm-5.3-flash /
  qwen3.8-flash; deepseek-v4-flash paid; gemini-2.5-flash eats the
  per-minute quota; zai 401; chutes/cerebras $0. bankofai free-tier
  rate-limits surface as a degraded final synthesis — re-run before
  judging; the tool evidence in the SSE is the reliable part.
- **Tooling:** commit messages via `git commit -F <file>`; python heredocs
  via the Bash tool must not contain backslash paths (use forward slashes).
  Large HTTP bodies: save to a file FIRST, then parse (S424). Live-test
  servers: plain Popen — never DETACHED_PROCESS with piped stdout on
  Windows (S423). Capture full pytest output to a file before filtering —
  `tail` on a pipe loses the FAILED list.
