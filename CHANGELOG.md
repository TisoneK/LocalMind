# Changelog

All notable changes to LocalMind are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Added Z.ai as a new LLM provider — offers free access to GLM-5.2, GLM-5.1, GLM-5, GLM-5-Turbo, GLM-4.7 (limited-time free) and GLM-4.5-Flash (always free). Sign up at `z.ai/manage-apikey/billing` to get an API key, then select "Z.ai (GLM-5.2 free)" in Settings. The model dropdown shows all available GLM models live from Z.ai's `/models` endpoint
- Automatic retry on HTTP 429 (rate limit) responses — the adapter now retries up to 2 times (3 total attempts) with exponential backoff (2s, then 4s), respecting the provider's `Retry-After` header when present. This makes transient per-minute burst limits (common on Cerebras's free tier) invisible to the user in most cases. Only 429s are retried; permanent errors (400/401/402/403/404) fail immediately without wasting time
- Added 4 new free-tier-friendly LLM providers: Cerebras (1M tokens/day free), SambaNova, Google Gemini, and Chutes AI — all selectable from the Settings panel
- New providers appear in the model selector, health endpoint, and startup logging alongside the existing 14 providers

### Changed
- Redesigned the API Keys section in Settings — removed the confusing dual-list pattern (stored keys list + separate "Select provider" dropdown) and replaced it with a single unified list where each provider has an inline "Add Key" or "Update" button that expands the key form right there. No more scrolling through a dropdown to find a provider — just click the button on the provider you want
- Provider list in the Settings panel now shows ALL providers in a single scrollable grid — previously only the first 8 appeared as buttons and the rest were hidden behind a "More providers..." dropdown that was easy to miss. Now all 18 providers (plus Ollama) are visible at once in a 2-3 column grid that scrolls if needed
- Provider list in the Settings panel is now sorted alphabetically (A–Z) by display name, making any provider easy to find regardless of when it was added
- The Settings panel no longer hardcodes any model IDs — default models now come live from the backend (`GET /api/settings`), and the full model list comes live from each provider (`GET /api/models?provider=...`). When a provider deprecates a model, only the backend needs updating and the frontend follows automatically. Previously the frontend duplicated every provider's default model ID in a hardcoded array, which drifted from the backend and caused 404 errors when providers deprecated models

### Fixed
- Fixed Z.ai free model (glm-4.5-flash) not appearing in the model dropdown — Z.ai's `/models` endpoint returns only paid models, and the default model was only added to the list when no model was saved. Now the provider's default model is ALWAYS included in the dropdown, even when a different model is currently selected. Users can now switch back to the free `glm-4.5-flash` from the dropdown
- Fixed model dropdown showing misleading "Free" vs "Paid" categories — the old split was based on whether the model ID contained the word "free", but GLM's free models use "flash" not "free" (e.g. `glm-4.5-flash`). Removed the category split entirely; all models now appear in a single flat list
- Fixed Z.ai (GLM models) stuck on "Thinking... forever" — GLM models default to thinking/reasoning mode which streams 1000+ reasoning tokens before the actual answer, taking 20-30 seconds and breaking the dispatcher's 10-second timeout. The adapter now sends `thinking: {type: "disabled"}` for all Z.ai API calls, making GLM respond instantly (5 chunks vs 1320 chunks for a simple "Say PONG" prompt). The `reasoning_content` field is still read as a fallback in case thinking is ever re-enabled
- Fixed Z.ai (GLM models) returning empty responses — GLM models stream reasoning tokens in `delta.reasoning_content` (thinking mode) and the final answer in `delta.content`. The adapter only read `content`, so when a GLM model was in thinking mode, it streamed `reasoning_content` that the adapter ignored, producing a blank response. The adapter now reads both fields across all 4 streaming paths
- Fixed Gemini returning 400 errors after v0.5.6 — the `safety_settings` field is NOT supported by Gemini's OpenAI-compatible endpoint (it returns "Unknown name 'safety_settings': Cannot find field"). Removed the injection entirely; the finish_reason detection added in v0.5.6 remains as the safety net, surfacing a clear error when Gemini's filter triggers instead of a blank response
- Fixed Gemini returning empty responses on follow-up messages — Gemini's safety filters were silently blocking responses to normal queries (sports scores, news, etc.), producing a blank chat with no error. The adapter now detects `finish_reason=SAFETY`/`content_filter` to surface a clear error message instead of a blank response
- Fixed the synthesizer silently producing empty output when the LLM returned a near-empty response (less than 10 characters) — now falls back to smart extraction so the user always sees something useful, even if the LLM was filtered or produced garbage
- Fixed Chutes AI base URL — was pointing to the management API (`api.chutes.ai`); now correctly points to the inference endpoint (`llm.chutes.ai`). Also updated the default model to `deepseek-ai/DeepSeek-V3.2-TEE` since all current Chutes models are TEE-suffixed
- Fixed model selector not showing available models for Cerebras, Gemini, and Chutes — these providers expose OpenAI-compatible `/models` endpoints, so the selector now lists live models (matching the existing Zen behavior)
- Fixed provider errors (invalid API key, rate limit, network failure) appearing as garbled text in the chat instead of a clear error message — error responses now surface as a proper error notification
- Fixed `asyncio` not imported in `ollama.py` — streaming chat was crashing with `NameError`
- Fixed undefined `secondary_intent` in engine pipeline — secondary intent routing now works
- Fixed `ToolCallResult` undefined in `openai_compat.py` — added `TYPE_CHECKING` import
- Fixed file-upload error handler in `chat.py` — `exc` was out of scope due to PEP 3110
- Fixed `_chunk_text` infinite loop when `overlap >= chunk_size`
- Fixed broken test suite — stale imports in `test_file_reader.py` and `test_web_search.py`
- Fixed 15 pre-existing test failures — mock signature mismatch and path bugs
- Fixed 5 TypeScript errors in frontend — `tsc -b` now passes clean
- Fixed Windows-only `dev:backend` script — now cross-platform via `scripts/dev-backend.js`
- Fixed 7 bare-except errors in `installed_programs.py`
- Fixed Pydantic V1 `class Config` deprecation warnings (3 locations)

### Added
- Comprehensive `README.md` (was empty — 0 bytes)
- `eslint.config.js` flat config for frontend — `npm run lint` works again
- `scripts/dev-backend.js` — cross-platform backend launcher
- GitHub Actions CI workflow (`.github/workflows/ci.yml`)
- `REVIEW.md` — agent review with 24 findings catalogued by severity

### Changed
- Aligned backend version from `0.1.0-dev` to `0.5.0` (was mismatched with frontend/electron)
- Updated `ARCHITECTURE.md` to reflect v4.0 ThinkingDispatcher codebase
- Updated `CONTRIBUTING.md` to document the actual direct-to-main workflow
- Ran `ruff --fix` — cleared 228 auto-fixable lint errors (862 → 613)

### Security
- Replaced bare `except:` with specific exception types in `installed_programs.py`

---

## [0.5.0] — 2025-01

### Added
- **Browser agent tool** — real web interaction via headless Chromium (navigate, click, fill forms, scroll, screenshot, execute JS)
- **Workflow system** — stream plan as thinking tokens + create todos from steps + mark todos complete as tools execute (full plan→execute→track cycle)
- **Full file metadata** — modified, created, extension, symlink detection
- **Context injection** — full system info (hostname, user, CPU, tools, memory count) injected into every prompt
- **Deliberative thinking** — result verification + Observe field mapping
- **Date/time injection** — current date/time injected into every prompt

### Fixed
- Atomic `settings.json` writes — never lose settings again
- Stop Ollama code paths from running when adapter is Zen
- Thinking timer showing 0s + added milliseconds for short thinking
- Enforced concise structured responses — no more walls of text
- Model now interprets intent instead of mechanically echoing user's message
- Epoch timestamps in chat + Observe tab all dashes + intent never sent
- 3 runtime errors from user's startup log
- LLM title prompt giving verbatim examples + sidebar never refreshed
- Second message hangs forever — queue await + isStreaming stuck
- Explicit done chunk on all return paths — UI was dormant because stream never signaled completion
- `NameError: 'tools' not defined` in agent loop call — second message crash
- Agent loop path missing done chunk — Observe tab showed — for all metrics
- Diagnostic logging for adapter issues + `/api/models/debug` endpoint

---

## [0.4.0] — 2025-01

### Added
- **Real-time thinking tokens** — stream actual LLM reasoning tokens, removed placeholders
- **File explorer** — default path, dispatcher progress, dedup, observe sync

### Changed
- Removed "conversation mode" tool ban + fixed default CWD to `~`
- Started backend before frontend to eliminate ECONNREFUSED spam

### Fixed
- 6 critical bugs making the UI look broken
- All remaining audit issues (C5-C6, H1-H9, M1-M8, L3-L10)
- npm audit vulnerabilities in frontend

---

## [0.3.0] — 2025-01

### Added
- **Settings modal** in frontend

### Changed
- **Engine refactor** — split `engine.py` into `engine/` package (helpers, memory, persistence, reflection submodules)
- UI model display syncs with backend active model
- Backend `settings.json` is source of truth, not frontend localStorage
- Removed all hardcoded model fallbacks from frontend

### Fixed
- Adapter now reads model from settings — the actual root cause of model sync issues
- Path bug + skip Ollama warmup for cloud adapters
- Frontend retries 503s automatically to eliminate startup console spam

---

## [0.2.0] — 2025-01

### Added
- **SSRF protection** in `web_fetch` tool
- **Settings file permissions** restriction and key revocation
- **Memory safety gate** tests

### Changed
- Removed 1,848 lines of dead classifier code

### Fixed
- Closed critical security vulnerabilities in backend
- Repaired corrupted safety regex and runtime bugs
- Fixed test collection errors
- Restored missing API client module and fixed runtime bugs in frontend

---

## [0.1.0] — 2025-01

### Added
- Initial release of LocalMind
- FastAPI backend with Ollama adapter
- File reader tool (PDF, DOCX, CSV, XLSX, code, images)
- Web search tool (DuckDuckGo)
- Memory tool (persistent semantic memory via sqlite-vec)
- Code executor tool (Python, sandboxed)
- File writer tool (permission-gated)
- React frontend with chat interface
- Electron desktop wrapper
- CLI (Typer)
- pytest test suite

[Unreleased]: https://github.com/TisoneK/LocalMind/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/TisoneK/LocalMind/releases/tag/v0.5.0
[0.4.0]: https://github.com/TisoneK/LocalMind/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/TisoneK/LocalMind/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/TisoneK/LocalMind/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/TisoneK/LocalMind/releases/tag/v0.1.0
