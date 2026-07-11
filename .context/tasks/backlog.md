# Backlog (append-only)

Open items for future sessions. Append at the bottom; never delete or
reorder. When an item is done, check it off and note the session/commit —
don't remove the line.

---
- [ ] **[Medium] Anthropic streaming fix needs live verification** (added 2026-07-11 by Super Z) — The Anthropic streaming format fix (`_chat_anthropic` now parses `content_block_delta`/`message_stop`/`message_delta` events) was based on Anthropic's SSE spec documentation, not runtime testing — no Anthropic API key was available. Next session with an Anthropic key: switch to the Anthropic adapter, send a streaming chat message, and verify tokens appear. File: `backend/src/adapters/openai_compat.py:1166-1231`.

---
- [ ] **[Medium] Theming strategy decision needed** (added 2026-07-11 by Super Z) — `globals.css` defines light (`:root`) and dark (`.dark`) theme variables, but LocalMind is dark-only by design (`.dark` applied to `<html>` in commit `9bfe8c8`). shadcn `dark:` variants now render correctly. Open question: commit to dark-only (remove light variables, remove `dark:` variants from shadcn components) OR implement a proper light/dark toggle (replace hardcoded hex in custom components like `SettingsModal.tsx` with CSS variables). The user needs to decide the direction. Related: `frontend/src/globals.css`, `frontend/src/components/shared/SettingsModal.tsx`.

---
- [x] **[Medium] Provider config consolidation (DRY)** (added 2026-07-11 by Super Z, done 2026-07-11 Session 6 — commit e2c0258) — Provider configuration is defined in THREE places that must stay in sync: `backend/src/adapters/openai_compat.py:PROVIDER_CONFIGS` (ProviderConfig dataclass), `backend/src/api/routes/config.py:PROVIDER_INFO` (dict with key_env/model_env), and `backend/src/core/model_router.py:provider_model_map` (dict). Adding a provider requires updating all three. Consolidate into a single source of truth in `PROVIDER_CONFIGS`, import elsewhere. Moderate risk — touches 3 modules and the 19-provider matrix. Needs thorough integration testing.

---
- [ ] **[High] Dependabot alerts — 43 vulnerabilities** (added 2026-07-11 by Super Z) — GitHub reports 43 security vulnerabilities on the default branch (14 high, 21 moderate, 8 low). Primarily in the NPM/Electron build toolchain (electron, electron-builder, tar, node-tar). Need `electron` major bump (v33→v34+) and `electron-builder` v25+. Build-time vulnerabilities (affect installer creation, not runtime) but should be addressed. Check: https://github.com/TisoneK/LocalMind/security/dependabot

---
- [ ] **[Low] CI is currently disabled** (added 2026-07-11 by Super Z) — CI workflow was added (commit `ci: add GitHub Actions workflow`) then removed (`c991559 chore: remove CI workflow — private repo has no Actions minutes`). No automated checks on push. Options: (a) enable GitHub Actions on a public mirror, (b) add a pre-commit hook (`ruff check .`, `pytest`, `tsc -b`, `eslint .`), (c) upgrade to a paid GitHub plan. Prior review finding C5.

---
- [ ] **[Low] L1 — 111 E501 line-length errors remain** (added 2026-07-11 by Super Z, carried from Session 1) — `ruff check .` reports 111 E501 errors (lines >120 chars). All are genuinely long strings/prompts that resist auto-wrapping. Down from 526 (Session 1) → 111 (Session 2). A `ruff format .` pass would clear most, but review the diff carefully — it can reformat in ways that hurt readability. No runtime impact.

---
- [ ] **[Nice-to-have] SettingsModal still uses hardcoded hex colors** (added 2026-07-11 by Super Z) — `SettingsModal.tsx` uses hardcoded hex (`#8ab08a`, `#d4e8d4`, `#39d353`, `#1a2a1a`, `#0d140d`, `#0a0f0a`, `#e05555`, `#e8a420`) instead of CSS variables (`bg-background`, `text-foreground`, etc.). Works because the app is dark-only, but blocks future theming. Depends on the theming strategy decision above.

---
- [ ] **[Long-term] Decompose monolith files** (added 2026-07-11 by Super Z) — `backend/src/core/engine/_pipeline.py` (2269 lines) and `backend/src/core/agent/loop.py` (2926 lines) are approaching unmaintainable size. Candidates for further decomposition into smaller modules. Low priority — well-documented and working, but future feature work will be harder.

---
- [ ] **[Long-term] Sandbox code execution** (added 2026-07-11 by Super Z) — `code_exec.py` runs Python with the user's full permissions — documented as "trusted-user only, not sandboxed." For defense-in-depth, consider Docker, nsjail, or RestrictedPython. Low priority for a local-first app, but worth noting if the app is ever exposed to untrusted input.

---
- [ ] **[Long-term] Add frontend tests** (added 2026-07-11 by Super Z) — No frontend tests exist. Vitest + React Testing Library would cover critical components (SettingsModal, ChatInput, WorkspaceLayout). Backend has 197 tests; frontend has 0.
