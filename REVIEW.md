# LocalMind — Agent Review

> **Review started:** 2026-07-09
> **Reviewer:** Super Z (AI agent)
> **Base commit:** d458f68 (`feat(context): inject full system info into every prompt...`)
> **Scope:** Discovery phase + baseline health check. Fix phase to follow user confirmation.
> **Push policy:** Direct to `main`, conventional commits with scope.

---

## Agent Discovery Phase

### Tech Stack
- **Framework:** FastAPI (backend), React 19 + Vite 6 (frontend), Electron 33 (desktop wrapper)
- **Language:** Python 3.10+ (backend), TypeScript 5 (frontend), JavaScript (electron)
- **Database + ORM/Driver:** SQLite + sqlite-vec (vector store). No ORM — raw `sqlite3` module.
- **Authentication:** None. Local-only app (runs on `localhost:8000`). No auth lib.
- **Media/Storage:** Local filesystem (`~/LocalMind/uploads`). No cloud storage SDK.
- **Styling:** Tailwind CSS 4 + shadcn/ui (Radix UI primitives in `frontend/src/components/ui/`)
- **State management:** Zustand (`frontend/package.json`) + TanStack Query v5
- **Package manager:** npm (root `package-lock.json`, workspaces for `frontend` + `electron`). Python backend uses `pyproject.toml` with hatchling build backend.
- **Deployment target:** Electron desktop app. Dev runs 3 processes: FastAPI `:8000`, Vite `:3000`, Electron.

### Project Structure
- **App entry / shell:** `frontend/src/main.tsx` (React), `backend/server.py` (FastAPI), `electron/main.js`
- **API / backend routes:** `backend/src/api/routes/` — 13 route files (actions, chat, config, filesystem, health, memory, metrics, models, observability, ollama, sessions, terminal, todos)
- **Frontend components:** `frontend/src/components/` — `chat/`, `layout/`, `panels/`, `shared/`, `ui/` (shadcn primitives — do not edit directly)
- **Shared libraries:** `frontend/src/lib/`, `backend/src/core/`
- **Database schema/migrations:** No migrations folder (despite ARCHITECTURE.md claiming `storage/migrations/`). Schema auto-created in `storage/db.py`.
- **UI primitives:** `frontend/src/components/ui/` — 57 shadcn/ui components (Radix-based). Do not edit directly.

### Documentation Files
- **README.md:** **EMPTY (0 bytes)** — see Critical #1
- **Architecture doc:** `docs/ARCHITECTURE.md` — exists but stale (see Medium #13)
- **Changelog:** **None** — see Medium #17
- **Devlog / technical log:** `docs/worklog-2025-01-empty-agent-fix.md` (single entry). Many analysis docs exist: `PERFORMANCE_BOTTLENECK_REPORT.md`, `PERFORMANCE_IMPLEMENTATION_PLAN.md`, `agent_system_optimization_analysis.md`, `shell_tool_fix_analysis.md`, `tools_architecture_proposal.md`, `tools_improvement_proposal.md`, `vector_store_optimization.md`, `web_search_analysis.md`
- **Prior review:** Multiple analysis docs in `docs/` (listed above) — extensive prior self-review
- **Env example:** **None** — see High #10. `.env` is gitignored. `backend/src/core/config.py` has defaults for all settings, but no `.env.example` for contributors.

### Conventions Discovered
- **Commit style:** Conventional Commits **with scope**: `feat(context):`, `fix(core):`, `fix(critical):`, `feat(tools):`, `fix(ui):`, etc. Single-line descriptions, informal tone ("the actual root cause", "never lose settings again"). No co-author trailers. No PRs — all 45 commits direct to `main`.
- **Versioning:** Root `package.json` = `0.5.0`, `frontend/package.json` = `0.5.0`, `backend/pyproject.toml` = `0.1.0-dev` — **inconsistent** (see High #8). Pre-1.0 semver. `localmind.md` says `v0.5-dev`.
- **Changelog rules:** No changelog file. No formal versioning policy.
- **Theming:** Dark mode supported via class strategy (`@custom-variant dark (&:is(.dark *))` in `globals.css`). Tailwind 4.
- **Testing:** pytest (backend), `tests/` at root with subdirs (`adapters/`, `api/`, `core/`, `storage/`, `tools/`). `pytest-asyncio` (auto mode), `pytest-cov`. **Test suite currently broken** (see Critical #4).
- **Linting/formatting:** ruff for Python (rules: E, F, I, N, W; line-length 100; target py310). mypy (non-strict, ignore_missing_imports). Frontend has `"lint": "eslint ."` script but **no eslint config file** (see High #7).

### Test Accounts
- N/A — local-only app, no authentication. No seed scripts for users.

### Git Workflow
- Single-contributor workflow. All work on `main`. No feature branches, no PRs.
- CONTRIBUTING.md says "Fork the repo and create a branch: `feat/my-tool-name`" but git log shows 100% direct-to-main — convention mismatch (see Medium #18).
- No remote branches other than `origin/main`. No Dependabot/renovate branches.

---

## Baseline Health Check

### Backend (Python)

| Check | Command | Result |
|---|---|---|
| Install | `pip install -e ".[dev]"` | ✅ Clean (72 packages) |
| Lint | `ruff check .` | ❌ **862 errors** (228 auto-fixable) |
| Tests | `pytest ../tests` | ❌ **2 collection errors** (stale imports) |
| Types | `mypy src` | ⚠️ 1 error in numpy stub (not project code) |

**Ruff error breakdown:**
| Rule | Count | Notes |
|---|---|---|
| E501 line-too-long | 526 | Formatting |
| I001 unsorted-imports | 93 | Auto-fixable |
| F401 unused-import | 63 | Auto-fixable, dead code |
| N806 non-lowercase-var-in-function | 48 | Naming |
| W293 blank-line-with-whitespace | 43 | Auto-fixable |
| F541 f-string-missing-placeholders | 17 | Auto-fixable |
| E701 multiple-statements-on-one-line | 15 | Style |
| E402 module-import-not-at-top | 12 | Style |
| F841 unused-variable | 12 | Auto-fixable |
| **F821 undefined-name** | **10** | **Real runtime bugs** |
| E722 bare-except | 7 | Bad error handling |
| W292 missing-newline-at-end-of-file | 6 | Auto-fixable |
| Other (N815, E741, N817, F811) | 10 | Various |

### Frontend (TypeScript/React)

| Check | Command | Result |
|---|---|---|
| Install | `npm install` | ✅ Clean (768 packages) |
| Typecheck | `tsc -b` | ❌ **5 errors** |
| Lint | `eslint .` | ❌ **Broken** (no config file) |
| Build | `vite build` | ✅ Succeeds, ⚠️ 1.1MB bundle warning |

**TypeScript errors:**
1. `src/components/ui/sonner.tsx:3` — Cannot find module `next-themes` (missing dep)
2. `src/main.tsx:6` — `HTMLElement | null` not assignable to `Container` (React 19 strictness)
3. `tailwind.config.ts:2` — Cannot find module `tailwindcss-animate` (missing dep; project uses `tw-animate-css` instead)
4. `vite.config.ts:24` — Property `code` does not exist on type `Error`
5. `vite.config.ts:40` — `rolldownOptions` not in Vite 6 type (Vite 7/rolldown feature)

---

## Findings

### Critical

#### C1: README.md is empty (0 bytes)
- **Description:** The project's README.md contains no content. The first thing any visitor, contributor, or documentation reader sees is a blank page.
- **Impact:** New users cannot install, run, or understand the project. Contributors have no onboarding path. The `backend/pyproject.toml` references `readme = "../README.md"` — PyPI packaging metadata will be empty. GitHub repo landing page shows no description.
- **Recommendation:** Write a README covering: project tagline, what it does, key features, prerequisites (Ollama, Python 3.10+, Node 18+), install steps (backend venv + npm install), run steps (`npm run dev:full`), architecture overview (link to `docs/ARCHITECTURE.md`), tool list, configuration (`.env` vars), contributing link, license. Use `localmind.md` and `docs/ARCHITECTURE.md` as source material.
- **Status:** Open
- **Related commit:** _(none yet)_

#### C2: `asyncio` not imported in `src/adapters/ollama.py` streaming code
- **Description:** Lines 405, 529, 551, 552 reference `asyncio.Queue`, `asyncio.create_task`, `asyncio.wait_for`, `asyncio.TimeoutError` but `asyncio` is not imported in the module (or the import was removed during a refactor). Ruff reports 5× F821.
- **Impact:** The streaming chat path — which is the primary chat mechanism — will raise `NameError: name 'asyncio' is not defined` the moment a user sends a message that triggers streaming. This is a runtime crash on the core code path.
- **Recommendation:** Add `import asyncio` at the top of `src/adapters/ollama.py` (or restore it if removed). Verify with `ruff check src/adapters/ollama.py --select F821`. Add a smoke test that exercises the streaming path.
- **Status:** Open
- **Related commit:** _(none yet)_

#### C3: `secondary_intent` undefined in `src/core/engine/_pipeline.py`
- **Description:** Lines 1931, 1932, 1946 reference `secondary_intent` in an `if`/`match` block, but the variable is never assigned anywhere in the function scope. Ruff reports 3× F821.
- **Impact:** The "secondary intent" handling block (lines 1930–1947) is dead code that will crash with `NameError` if execution ever reaches it. Either the variable assignment was deleted during a refactor, or the block was left in by mistake. Either way, secondary intent routing (e.g. file-write follow-up) silently never executes.
- **Recommendation:** Trace where `secondary_intent` was meant to come from (likely the intent router output). Either restore the assignment or remove the dead block. Check git history: `git log -p --all -S secondary_intent -- src/core/engine/`.
- **Status:** Open
- **Related commit:** _(none yet)_

#### C4: Test suite is broken — stale imports
- **Description:** `tests/tools/test_file_reader.py` imports `_extract_plain` from `tools.file_reader`, but that function no longer exists (the module exports `_parse_pdf`, `_parse_docx`, `_parse_csv_xlsx`, `_parse_image` instead). `tests/tools/test_web_search.py` imports `run` from `tools.web_search`, but the function was renamed to `web_search`. pytest cannot collect either file — the entire test suite is blocked.
- **Impact:** No tests can run. The CONTRIBUTING.md says "Run pytest — all tests must pass" but the suite cannot even be collected. Any future regression will go undetected. The source was refactored (renamed `run` → `web_search`, split `_extract_plain` into format-specific parsers) but the tests were never updated.
- **Recommendation:** Update `test_file_reader.py` to import the new parser functions (`_parse_pdf`, `_parse_docx`, etc.) and test them directly. Update `test_web_search.py` to import `web_search` instead of `run`. Run `pytest ../tests --collect-only` to confirm collection succeeds, then run the full suite.
- **Status:** Open
- **Related commit:** _(none yet)_

#### C5: No CI — broken tests and lint go undetected
- **Description:** There is no `.github/workflows/` directory. No automated checks run on push or PR. The baseline shows 862 lint errors, a broken test suite, and 10 runtime bugs — none of which were caught before they reached `main`.
- **Impact:** Every issue in this review (C1–C4, H1–H7, etc.) reached `main` because nothing checks the code on push. Contributors cannot trust that `main` is green. Future regressions will continue to accumulate silently.
- **Recommendation:** Add `.github/workflows/ci.yml` that runs on push/PR: backend (`ruff check .`, `pytest`, `mypy src`), frontend (`tsc -b`, `eslint .`, `vite build`). Start with non-blocking warnings, then make blocking once the baseline is clean. Add a status badge to README.
- **Status:** Open
- **Related commit:** _(none yet)_

### High

#### H1: 862 ruff errors — codebase doesn't pass its own linter
- **Description:** `ruff check .` reports 862 errors across 24 rule categories. 228 are auto-fixable with `ruff check . --fix`. CONTRIBUTING.md lists `ruff check .` as a code standard.
- **Impact:** The lint standard documented in CONTRIBUTING.md is unenforceable. New contributors will either ignore lint or spend hours fixing pre-existing errors. 63 unused imports (F401) are dead code that obscures real dependencies.
- **Recommendation:** Run `ruff check . --fix` first (handles 228 errors safely). Then address the remaining 634 manually, prioritizing F821 (done in C2/C3), F401, and F841. Consider adding `ruff check .` to a pre-commit hook.
- **Status:** Open
- **Related commit:** _(none yet)_

#### H2: Frontend eslint is completely broken — no config file
- **Description:** `frontend/package.json` has `"lint": "eslint ."` but there is no `eslint.config.js` (or `.eslintrc.*`) anywhere in the repo. ESLint 10 (installed) requires flat config. Running `npx eslint .` errors: "ESLint couldn't find an eslint.config.(js|mjs|cjs) file."
- **Impact:** The `npm run lint` script is non-functional. Frontend code has zero lint coverage. TypeScript errors (H5) and code-quality issues go undetected.
- **Recommendation:** Create `frontend/eslint.config.js` using the new flat config format. Base it on `@eslint/js` recommended + `typescript-eslint` + React plugins. Add it to CI (C5).
- **Status:** Open
- **Related commit:** _(none yet)_

#### H3: Version mismatch across packages
- **Description:** Root `package.json` = `0.5.0`, `frontend/package.json` = `0.5.0`, but `backend/pyproject.toml` = `0.1.0-dev`. `localmind.md` says `v0.5-dev`.
- **Impact:** Inconsistent versioning makes it unclear what version the project is on. Backend packaging metadata (PyPI classifiers) reports the wrong version. Release tagging and changelog (if added) will be ambiguous.
- **Recommendation:** Align all three to `0.5.0` (or `0.5.0-dev` if pre-release). Decide on a single source of truth (root `package.json` is the natural choice for a monorepo). Add a version-sync check to CI.
- **Status:** Open
- **Related commit:** _(none yet)_

#### H4: `dev:backend` script uses Windows-only path
- **Description:** Root `package.json` script: `"dev:backend": "cd backend && .venv\\Scripts\\python.exe server.py"`. The path `.venv\\Scripts\\python.exe` only exists on Windows. On macOS/Linux the venv Python is at `.venv/bin/python`.
- **Impact:** macOS/Linux contributors cannot start the backend via `npm run dev:backend` or `npm run dev:full`. The script silently fails or errors with "No such file or directory."
- **Recommendation:** Use a cross-platform invocation. Options: (a) `python -m server` with venv activated, (b) a small Node helper script that detects platform and picks the right path, (c) use `cross-env` (already a devDep) + a shell script. Simplest: `"dev:backend": "cd backend && .venv/bin/python server.py"` won't work on Windows either — use a Node script or `concurrently` with platform detection.
- **Status:** Open
- **Related commit:** _(none yet)_

#### H5: 5 TypeScript errors in frontend
- **Description:** `tsc -b` reports 5 errors: (1) `next-themes` module not found — `sonner.tsx` imports it but it's not in `package.json`; (2) `main.tsx` passes `getElementById` result (possibly null) to React 19's stricter `createRoot`; (3) `tailwind.config.ts` imports `tailwindcss-animate` but the project uses `tw-animate-css`; (4-5) `vite.config.ts` has a `code` property access on `Error` and a `rolldownOptions` key that doesn't exist in Vite 6.
- **Impact:** `tsc -b` (the typecheck half of `npm run build`) fails. Vite build still succeeds because esbuild is lenient, but type safety is broken. The `next-themes` and `tailwindcss-animate` imports suggest components were copied from a different scaffold (shadcn's Next.js template) without adjusting deps.
- **Recommendation:** (1) Either add `next-themes` to deps or remove the import from `sonner.tsx` (use a prop or context instead). (2) Add a null check in `main.tsx`: `const el = document.getElementById('root'); if (!el) throw new Error('root not found'); createRoot(el).render(...)`. (3) Remove the `tailwindcss-animate` import from `tailwind.config.ts` (the project already uses `tw-animate-css`). (4-5) Fix `vite.config.ts` error typing and remove/conditionalize `rolldownOptions`.
- **Status:** Open
- **Related commit:** _(none yet)_

#### H6: `ToolCallResult` undefined in `src/adapters/openai_compat.py`
- **Description:** Line 290 uses `"AsyncIterator[StreamChunk] | ToolCallResult"` as a return type annotation, but `ToolCallResult` is not imported or defined in the module. Ruff reports 1× F821.
- **Impact:** The annotation is string-quoted so it won't crash at runtime, but it's a type error. Anyone running `mypy` on this module will get an error. The return type is misleading — callers don't know what `ToolCallResult` is.
- **Recommendation:** Either import `ToolCallResult` from wherever it's defined, or replace with the actual type (likely a `ToolResult` or a `dataclass` defined elsewhere). Search: `rg "class ToolCallResult" backend/src/`.
- **Status:** Open
- **Related commit:** _(none yet)_

#### H7: `exc` referenced out of scope in `src/api/routes/chat.py`
- **Description:** Line 431 has `logger.error(f"[chat] file upload error: {exc}", exc_info=True)` (presumably inside an `except Exception as exc:` block). Line 433 then defines an async generator `_err()` that references `exc` in an f-string: `yield _sse({"error": f"File upload failed: {exc}", "done": True})`. Ruff reports 1× F821 — `exc` may not be in scope when `_err()` is called later.
- **Impact:** If `_err()` is called after the `except` block has exited, `exc` may be undefined, causing a `NameError` inside the error handler — the user gets no error message at all. This is a broken error-handling path.
- **Recommendation:** Capture `exc` into a local variable before defining `_err()`, or pass it as a parameter. Verify the scoping by reading the full function.
- **Status:** Open
- **Related commit:** _(none yet)_

### Medium

#### M1: ARCHITECTURE.md is stale
- **Description:** `docs/ARCHITECTURE.md` mentions ChromaDB (the project now uses sqlite-vec — see `localmind.md` and `backend/src/storage/vector.py`), references a `storage/migrations/` directory that doesn't exist, and lists only 5 tools when the actual `backend/src/tools/` has 13+ tool modules (browser_agent, code_exec, edit_file, file_reader, file_writer, installed_programs, memory_tool, shell, sysinfo, web_fetch, web_search, etc.). The directory structure diagram shows `ui/` but the actual frontend is at `frontend/`.
- **Impact:** New contributors and agents reading the architecture doc get a wrong mental model. The doc has drifted from the code.
- **Recommendation:** Update ARCHITECTURE.md: replace ChromaDB with sqlite-vec, remove migrations reference, update tool list to match `backend/src/tools/`, fix directory structure to match actual layout, update the adapter list (now includes `openai_compat.py`).
- **Status:** Open
- **Related commit:** _(none yet)_

#### M2: 7 bare-except (E722) errors in `installed_programs.py`
- **Description:** `src/tools/installed_programs.py` lines 45, 47, 50, 51 use bare `except:` which catches everything including `KeyboardInterrupt`, `SystemExit`, and `GeneratorExit`.
- **Impact:** A bare except can swallow critical signals — pressing Ctrl+C during program enumeration won't interrupt. Makes debugging harder since all errors are silently turned into empty strings.
- **Recommendation:** Replace `except:` with `except Exception:` at minimum. Better: catch specific exceptions (e.g. `OSError`, `WindowsError`).
- **Status:** Open
- **Related commit:** _(none yet)_

#### M3: 1.1MB frontend JS bundle — no code splitting
- **Description:** `vite build` produces a single 1,123 KB JS chunk (367 KB gzipped). Vite warns: "Some chunks are larger than 500 kB after minification."
- **Impact:** First page load fetches the entire app. On slow connections this is several seconds of blank screen. Electron loads from local disk so impact is lower there, but web/preview mode suffers.
- **Recommendation:** Add `build.rollupOptions.output.manualChunks` to split vendor libs (react, radix, recharts, react-markdown) into separate chunks. Use `React.lazy()` + `Suspense` for route-level code splitting of panels (FileExplorer, TerminalPanel, MemoryTab, etc.).
- **Status:** Open
- **Related commit:** _(none yet)_

#### M4: No changelog file
- **Description:** No `CHANGELOG.md` exists. The kickoff template emphasizes changelog/devlog conventions. `docs/worklog-2025-01-empty-agent-fix.md` is the only devlog-style entry.
- **Impact:** Users and contributors cannot see what changed between versions. Release notes don't exist. The 45-commit history is the only record, and commit messages are informal.
- **Recommendation:** Create `CHANGELOG.md` using Keep a Changelog format. Backfill entries from git log for v0.1–v0.5. Add a `[Unreleased]` section. Commit a changelog entry with every behavior-changing commit going forward.
- **Status:** Open
- **Related commit:** _(none yet)_

#### M5: CONTRIBUTING.md convention mismatch — says branch, commits are direct-to-main
- **Description:** CONTRIBUTING.md says "Fork the repo and create a branch: `feat/my-tool-name`" and "Open a PR." But all 45 commits are direct to `main` — no branches, no PRs.
- **Impact:** Contributors following the doc will create branches/PRs that don't match the actual workflow. The doc and practice diverge.
- **Recommendation:** Either (a) update CONTRIBUTING.md to reflect the direct-to-main workflow with conventional commits, or (b) adopt the branch+PR workflow the doc describes. Given single-contributor size, (a) is more honest.
- **Status:** Open
- **Related commit:** _(none yet)_

#### M6: 63 unused imports (F401) — dead code
- **Description:** 63 instances of imports that are never used in their module. All auto-fixable.
- **Impact:** Dead imports obscure real dependencies, slow import time slightly, and confuse readers about what a module relies on.
- **Recommendation:** Run `ruff check . --select F401 --fix`. Review the diff to confirm no imports are used via `__all__` re-exports or dynamic access.
- **Status:** Open
- **Related commit:** _(none yet)_

#### M7: Deprecation warnings — Pydantic V2 class-based config, Starlette httpx TestClient
- **Description:** `backend/src/core/models.py:447` uses Pydantic V1-style `class Config:` inside a `BaseModel` (deprecated since Pydantic 2.0, removed in 3.0). `fastapi/testclient.py` triggers a Starlette deprecation warning about httpx.
- **Impact:** Will break when Pydantic 3.0 ships. Currently only warnings, but they're noise in test output.
- **Recommendation:** Replace `class Config:` with `model_config = ConfigDict(...)`. For the Starlette warning, install `httpx2` or suppress the warning in pytest config.
- **Status:** Open
- **Related commit:** _(none yet)_

### Low

#### L1: 526 line-too-long errors (E501)
- **Description:** 526 lines exceed the 100-char limit.
- **Impact:** Readability. No runtime impact.
- **Recommendation:** Run `ruff format .` to auto-wrap. Or run `ruff check . --select E501 --fix` (less aggressive).
- **Status:** Open

#### L2: 93 unsorted-imports (I001)
- **Description:** Import blocks not in ruff's canonical order.
- **Impact:** Style consistency. Auto-fixable.
- **Recommendation:** `ruff check . --select I001 --fix`.
- **Status:** Open

#### L3: 43 blank-lines-with-whitespace (W293)
- **Description:** Blank lines contain trailing whitespace.
- **Impact:** Git noise, editor inconsistency. Auto-fixable.
- **Recommendation:** `ruff check . --select W293 --fix` or `ruff format .`.
- **Status:** Open

#### L4: 17 f-string-missing-placeholders (F541)
- **Description:** 17 f-strings with no `{...}` interpolation — just `f"literal string"`.
- **Impact:** Minor perf (unnecessary f-string evaluation), readability. Auto-fixable.
- **Recommendation:** `ruff check . --select F541 --fix`.
- **Status:** Open

#### L5: 12 unused-variable (F841) + 15 multiple-statements-on-one-line (E701)
- **Description:** 12 variables assigned but never used; 15 lines with `if x: y` on one line.
- **Impact:** Readability, dead code.
- **Recommendation:** Review and remove unused vars (`--select F841 --fix`). Break multi-statement lines for readability.
- **Status:** Open

---

## Next Steps

This review covers the **discovery phase only**, per the agreed scope. The baseline is unhealthy:

- **5 Critical** issues (empty README, 2 runtime crash bugs, broken tests, no CI)
- **7 High** issues (862 lint errors, broken eslint, version mismatch, Windows-only script, 5 tsc errors, 2 more F821 bugs)
- **7 Medium** issues (stale architecture doc, bare-excepts, bundle size, no changelog, convention mismatch, dead imports, deprecations)
- **5 Low** issues (formatting)

**Proposed fix order** (awaiting user confirmation):

1. **C2 + C3** — Fix the 2 runtime crash bugs (asyncio import, secondary_intent). Fast, high-value.
2. **C4** — Fix the broken test suite (update stale imports). Unblocks all future test runs.
3. **H7 + H6** — Fix the remaining 2 F821 bugs (exc scope, ToolCallResult).
4. **C1** — Write README.md. High-visibility, uses existing docs as source.
5. **H1 (partial)** — Run `ruff check . --fix` to clear 228 auto-fixable errors safely.
6. **H2 + H5** — Fix frontend: add eslint config, fix 5 tsc errors.
7. **H3 + H4** — Fix version mismatch + cross-platform dev:backend script.
8. **C5** — Add CI workflow (now that lint+tests pass).
9. **M1–M7** — Medium fixes (stale docs, bare-excepts, bundle splitting, changelog, etc.).
10. **L1–L5** — Low-priority formatting (mostly auto-fixable).

Each fix = one conventional commit, pushed to main, REVIEW.md updated with status + commit SHA.

---

_This review is a living document. Each fix updates the corresponding finding's Status and Related commit fields._
