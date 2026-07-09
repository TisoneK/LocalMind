# Changelog

All notable changes to LocalMind are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Model picker in the Settings panel now shows a live dropdown of available models for the selected provider, fetched from the provider's `/models` endpoint — no more typing model IDs by hand
- Added 4 new free-tier-friendly LLM providers: Cerebras (1M tokens/day free), SambaNova, Google Gemini, and Chutes AI — all selectable from the Settings panel
- New providers appear in the model selector, health endpoint, and startup logging alongside the existing 14 providers

### Changed
- Provider list in the Settings panel is now sorted alphabetically (A–Z) by display name, making any provider easy to find regardless of when it was added. Both the quick-pick button row (first 8) and the "More providers" dropdown follow the same A–Z order
- The Settings panel no longer hardcodes any model IDs — default models now come live from the backend (`GET /api/settings`), and the full model list comes live from each provider (`GET /api/models?provider=...`). When a provider deprecates a model, only the backend needs updating and the frontend follows automatically. Previously the frontend duplicated every provider's default model ID in a hardcoded array, which drifted from the backend and caused 404 errors when providers deprecated models

### Fixed
- Fixed Cerebras default model — `llama-3.3-70b` was deprecated by Cerebras and returned 404; switched to `gpt-oss-120b` (the current production model)
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
