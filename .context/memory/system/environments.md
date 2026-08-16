# Environments (update in place)

Machines and sandboxes agents have run on, and what it takes to work on
this project from each. One block per environment; update the matching
block (and its "last verified" date) every time you run on it again.

## Rules

1. **Match before you add.** At session start, check whether the machine
   you're on already has a block (use its "Identify by" line). Update the
   match; add a new block only for a genuinely new environment.
2. **Record what you verified, not what you assume.** A command belongs
   under "Verified commands" only after it ran successfully on this
   environment, this project.
3. **Agents never delete blocks.** An environment the project no longer
   uses may be pruned by the user; if you can't verify a block, leave it
   alone — its last-verified date already says how stale it is.
4. **Machine facts only.** Secret values go in `secrets/`; user
   preferences in `user/`; project-wide decisions in `plans/`.

---
---
## Tison's local Windows machine (last verified 2026-07-11)

- **Identify by:** hostname matches `Tison`; OS is Windows; user home is `C:\Users\tison`; Dev root is `C:\Users\tison\Dev`
- **OS:** Windows 11 (PowerShell)
- **Runtimes:** Node.js v24.13.0, Python 3.14.2, npm 11.12.1
- **Package manager:** npm (root `package-lock.json` with workspaces); pip (system Python, not venv — on Windows, PEP 668 is advisory only)
- **Verified commands:**
  - `node --version` → v24.13.0 (2026-07-11)
  - `python --version` → Python 3.14.2 (2026-07-11)
  - `npm --version` → 11.12.1 (2026-07-11)
- **Quirks:**
  - Windows paths use backslashes; PowerShell handles both `/` and `\`
  - No `make` — use npm scripts or PowerShell equivalents
  - Python is system-wide (no venv isolation required on Windows, but still recommended for backend work)
  - This is a local development machine — persistent storage, full filesystem access

## Z.ai cloud sandbox (last verified 2026-08-02)

- **Identify by:** workspace path `/home/z/my-project/`; env vars `FC_FUNCTION_NAME` / `SIGMA_APP_NAME` present; `CLAWHUB_WORKDIR=/home/z/my-project`
- **OS:** Linux 6.5 (Ubuntu-based, containerized — `KATA_CONTAINER=true`)
- **Runtimes:** Python 3.12.13, Node 22.x (via bun), bun
- **Package manager:** npm (root `package-lock.json` with workspaces for `frontend` + `electron`); pip with venv for backend
- **Verified commands:**
  - Backend deps: `cd backend && python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"`
  - Backend lint: `cd backend && source .venv/bin/activate && ruff check .` (112 E501 errors, 0 real bugs — Session 7)
  - Backend tests: `cd backend && source .venv/bin/activate && pytest ../tests` (197 pass, 33-36s — Session 7)
  - Backend mypy: `cd backend && source .venv/bin/activate && mypy src` (1 error — numpy stub version mismatch, pre-existing tooling issue, not LocalMind code — Session 7)
  - Frontend deps: `npm install` (at repo root)
  - Frontend typecheck: `cd frontend && npx tsc -b` (0 errors — Session 7)
  - Frontend lint: `cd frontend && npx eslint .` (0 errors, 48 warnings — React 19 `set-state-in-effect` noise — Session 7)
  - Frontend build: `cd frontend && npx vite build` (566KB bundle, 5s)
- **Quirks:**
  - System Python is locked down (`externally-managed-environment`) — must create a venv before `pip install`
  - No persistent storage between sessions — `/home/z/my-project/` is wiped on session end; only `/home/z/my-project/download/` persists for user downloads
  - `ruff` and `pytest` are not on PATH globally — must activate the backend venv first
  - The file upload pipeline redacts secrets — `[REDACTED:github_token]` replaces real tokens in uploaded files. PAT must be pasted in chat.
  - Git remote URL is stripped of token after clone; must re-add token for push, then strip again (see protocol Step 12)
  - `npm install` emits `allow-scripts` warnings for `electron@33.4.11` (postinstall: `node install.js`) and `esbuild@0.25.12` (postinstall: `node install.js`). These are dev build-time scripts, safe to defer — the frontend typecheck/lint/build all work without approving them. (Session 7)
  - **File-mode drift after sandbox wipe:** when the sandbox wipes and re-clones a repo, all files come back with mode `100755` (executable) instead of `100644`. This makes `git status` show every file as modified and blocks `git pull` with "Please commit your changes or stash them before you merge." Fix: `git config core.fileMode false && git checkout -- .` then pull. This is a sandbox filesystem artifact, not real changes. (Session 8)
  - **Verified commands (Session 65, 2026-08-02 — research-only, no venv/baseline re-run):**
    - `git clone "https://x-access-token:${GITHUB_PAT}@github.com/TisoneK/LocalMind.git"` → succeeded; PAT stripped from `.git/config` via `git remote set-url origin https://github.com/TisoneK/LocalMind.git` immediately after
    - `git config user.name "Tisone Kironget" && git config user.email "tisonkironget@gmail.com"` → set local git identity (sandbox default is `Z User <z@container>`, must be overridden)
    - `git pull --ff-only` → "Already up to date." (on `main`)
    - `sh .context/core/bin/context-sync verify` → "core OK: every file matches MANIFEST.sha256 (0.5.0)"
    - `sh .context/core/bin/context-sync status` → "core: 0.5.0, locked: 0.5.0, source: none reachable — skipping, this is fine"
    - `git clone https://github.com/CodebuffAI/open-codebuff.git` → succeeded (public, anonymous HTTPS, no auth needed)

## Local macOS development machine (last verified 2026-08-15)

- **Identify by:** workspace path `/Users/bao/Code`; macOS host; local project checkout at `/Users/bao/Code/LocalMind`
- **OS:** macOS 15.7.7
- **Runtimes:** Node.js v24.17.0, Python 3.9.6, Python 3.12.13 via uv, npm 11.13.0
- **Package manager:** npm (root `package-lock.json` with workspaces); uv for the backend project-local Python environment
- **Verified commands:**
  - `sh .context/core/bin/context-sync verify` → core 0.5.0 integrity OK
  - `sh .context/core/bin/context-sync status` → up to date
  - `npm ci` → 962 packages added, 965 packages audited
  - `uv venv backend/.venv --python /Users/bao/.local/bin/python3.12`
  - `uv pip install --python backend/.venv/bin/python -e 'backend[dev]'`
  - `backend/.venv/bin/python -m pytest -q` → 497 passed
  - `cd backend && .venv/bin/python -m pytest ../tests/agents/ ../tests/tools/test_browser_agent.py ../tests/tools/test_diagnostics.py ../tests/tools/test_git_tool.py ../tests/tools/test_process_tool.py -q` → 411 passed, 1 existing deprecation warning (2026-07-31)
  - `cd backend && .venv/bin/ruff check src/tools/browser_agent.py src/agents/browser/agent.py src/agents/browser/context_builder.py ../tests/tools/test_browser_agent.py` → clean (2026-07-31)
  - `npm run build --workspace=localmind-frontend` → passed
  - `npm run lint --workspace=localmind-frontend` → 0 errors, 49 warnings
  - `cd backend && .venv/bin/python -m pytest -q` → 760 passed, 1 baseline failure in `test_engine_emit_todo_plan` (2026-07-31)
  - `cd frontend && npm run build` → passed; `npm run lint` → 0 errors, 53 warnings (2026-07-31)
  - `cd backend && .venv/bin/ruff check .` → 132 E501 findings plus 3 non-E501 findings (2026-07-31)
  - `cd backend && .venv/bin/python -m pytest ../tests/core/test_capabilities.py ../tests/agents/test_phase4_task_type_selection.py ../tests/core/test_workspace_state.py -q` → 64 passed (2026-07-31)
  - changed-file compile and Ruff for `core/capabilities.py` + `tests/core/test_capabilities.py` → passed (2026-07-31)
  - `cd backend && .venv/bin/python -m pytest ../tests/core/test_observation.py ../tests/core/test_workspace_state.py -q` → 34 passed; changed-file compile/Ruff/diff checks passed (2026-07-31)
  - `cd frontend && npm run build` → passed; `npm run lint` → 0 errors / 53 warnings (2026-07-31)
  - `cd backend && .venv/bin/python -m pytest ../tests/core/test_observation.py ../tests/core/test_observation_runtime.py ../tests/core/test_workspace_state.py ../tests/e2e/test_obs_drain_bug.py -q` → 39 passed; compile and diff checks passed; changed-file Ruff had only six pre-existing E501 findings (2026-07-31)
  - `cd backend && .venv/bin/python -m pytest -q` → 779 passed, 1 existing todo-plan assertion failure (2026-07-31)
  - `cd backend && .venv/bin/python -m pytest ../tests/api/test_observability.py ../tests/core/test_observation.py ../tests/core/test_observation_runtime.py -q` → 19 passed; compile and diff checks passed; changed read-path Ruff clean (2026-07-31)
  - `cd backend && .venv/bin/python -m pytest -q` → 786 passed, 1 existing todo-plan assertion failure (2026-07-31)
  - `cd frontend && npm run build` → passed; `npm run lint` → 0 errors / 53 warnings (2026-07-31)
  - `cd frontend && npm run test -- --run` → 9 passed; `npm run build` → passed; `npm run lint` → 0 errors / 53 warnings (2026-07-31)
  - `cd frontend && npm run build` → passed; `npm run lint` → 0 errors / 53 warnings; `npm test -- --run` → 12 passed across 3 files (2026-08-01)
  - `git diff --check` → clean; live backend SSE probe → HTTP 200 (2026-08-01)
  - `backend/.venv/bin/pytest -q tests/core/test_utils.py tests/tools/test_output_bounds.py tests/api/test_chat.py tests/tools/test_process_tool.py` → 66 passed (2026-08-03)
  - changed-file `compileall` and Ruff checks → passed; full backend `pytest -q` → 816 passed, 1 known todo-plan wording failure (2026-08-03)
  - `sh scripts/ci-check.sh` → all pass: Ruff clean; pytest 1748 passed; frontend TypeScript clean; ESLint 0 errors / 64 warnings (2026-08-14)
  - `backend/.venv/bin/python -m pytest tests/core/test_web_search_handler.py -q` → 1 passed (2026-08-14)
  - `backend/.venv/bin/python -m pytest tests/core/test_empty_agent_fix.py tests/agents/test_phase3_delegation.py tests/tools/test_delegate_streaming.py tests/tools/test_delegate_parallel.py tests/tools/test_delegate_inline.py -q` → 110 passed (2026-08-14)
  - `sh scripts/ci-check.sh` → all pass: Ruff clean; pytest 1753 passed; frontend TypeScript clean; ESLint 0 errors / 64 warnings (2026-08-14)
  - `cd frontend && npm test -- --run` → 141 passed across 16 files; `npx tsc -b` → passed; `npm run build` → passed; `npm run lint` → 0 errors / 64 warnings (2026-08-14, Session 203)
  - `backend/.venv/bin/python -m pytest -q` → 1755 passed, 2 skipped (2026-08-14, Session 208)
  - `cd frontend && npm test -- --run` → 141 passed; `npx tsc -b && npm run lint && npm run build` → passed; ESLint 0 errors / 64 warnings (2026-08-14, Session 208)
  - `sh scripts/ci-check.sh` → backend 1,773 passed / 2 skipped; Ruff clean; frontend TypeScript clean; ESLint 0 errors / 64 warnings (2026-08-14, Session 220)
  - `cd frontend && npm test -- --run` → 178 passed; `npx tsc -b` → passed; `npm run build` → passed (2026-08-14, Session 220)
  - `sh scripts/ci-check.sh` → backend 1,776 passed / 2 skipped; Ruff clean; frontend TypeScript clean; ESLint 0 errors / 64 warnings (2026-08-14, Session 221)
  - `cd frontend && npm test -- --run` → 178 passed; `npx tsc -b` → passed; `npm run build` → passed (2026-08-14, Session 221)
  - `sh scripts/ci-check.sh` → backend 1,784 passed / 2 skipped; Ruff clean; frontend TypeScript clean; ESLint 0 errors / 64 warnings (2026-08-14, Session 222)
  - `cd frontend && npm test -- --run` → 178 passed; `npx tsc -b && npm run build` → passed (2026-08-14, Session 222)
  - `cd backend && .venv/bin/pytest -q` → 1827 passed, 2 skipped, 5 pre-existing failures (4 macOS `test_shell.py` env + `test_prompt_budget` drift) (2026-08-15, Session 238)
  - Live trace harness: `cd backend && LOCALMIND_PORT=8765 LOCALMIND_SHELL_ENABLED=true nohup .venv/bin/python server.py > /tmp/lm.log 2>&1 &` then `curl -s -N --max-time 110 -F "message=<request>" http://127.0.0.1:8765/api/chat` — verified working against gemini-2.5-flash (2026-08-15, Session 238)
  - `backend/.venv/bin/python -m pytest tests/core/test_agent_loop_empty_response.py tests/adapters/test_openai_compat_429.py tests/core/test_error_normalizer.py -q` → 88 passed (2026-08-15, Session 241)
  - `backend/.venv/bin/python -m pytest -q` → 1752 passed, 2 skipped (2026-08-15, Session 241)
  - `npm run build` → frontend TypeScript/Vite build and Electron DMG packaging passed (2026-08-15, Session 241)
  - `backend/.venv/bin/ruff check backend/src/core/agent/loop.py tests/core/test_agent_loop_empty_response.py` → clean (2026-08-15, Session 241)
  - `git diff --check` → clean (2026-08-15, Session 241)
  - Live clean-HEAD smoke: `/api/health` reported `zen / deepseek-v4-flash-free`, `/api/settings` reported configured-key flags without exposing values, and a real `/api/chat` request received Zen HTTP 429 after adapter retries (2026-08-15, Session 242)
  - Live trace harness (Session 251): the SYNC shell REAPS backgrounded children when the command returns, so run server+curl+kill in ONE command: `LOCALMIND_PORT=8765 LOCALMIND_SHELL_ENABLED=true .venv/bin/python server.py > /tmp/lm.log 2>&1 & PID=$!; sleep 6; curl -s -N --max-time 190 -F "message=<req>" http://127.0.0.1:8765/api/chat > /tmp/out.txt; kill $PID`. SSE payloads are JSON-only (`data: {"obs_event": {"type": ..., "data": ...}}`, no `event:` lines) — parse with a NON-greedy regex `data: (\{.*?\})\s*\n`. Active settings at `~/LocalMind/settings.json` (adapter=zai, model=glm-4.5-flash, all 5 providers have keys SET — check presence via `api_keys` KEYS only, never values). For a provider override WITHOUT mutating the user's settings: temp `LOCALMIND_HOME` + copy of settings.json (chmod 600) + edit adapter/model in the copy, then delete the temp home IMMEDIATELY (a backgrounded `A && B & C` chain left one behind once — verify no `/tmp/lm251_home.*` leftovers). (2026-08-16, Session 251)
- **Quirks:** The `python` command is unavailable and system `python3` is 3.9.6, below the backend's `>=3.10` requirement; use `backend/.venv/bin/python` (Python 3.12.13 via uv). Backend Ruff currently reports 132 E501 findings plus 3 non-E501 findings. `npm ci` reported 18 dependency vulnerabilities (17 high, 1 critical) and deprecated transitive packages. Local agent uses the user's existing git credentials and does not need a PAT for this public clone. The optional `agent-browser` CLI is not installed; BrowserAgent tests must mock `_run_browser_cmd` unless the CLI is installed for live smoke testing.
  - **Port 8000 is ALWAYS occupied** by the user's running LocalMind app instance — start trace servers on `LOCALMIND_PORT=8765` instead; never kill the user's instance.
  - **The ACTIVE provider is gemini-2.5-flash**, set via the app's Settings UI (its key is NOT in `backend/.env` — only `ZEN_API_KEY` is). The server startup log prints `adapter: <x> | model: <y>` — read it to learn the real active provider.
  - **`LOCALMIND_SHELL_ENABLED=false` in `backend/.env`** — trace servers must set `LOCALMIND_SHELL_ENABLED=true` or the shell tool reports "Shell tool is disabled".
  - **No `timeout` CLI on macOS** (GNU coreutils) — use `curl --max-time N`.
  - `test_prompt_budget.py::test_init_prompt_is_under_budget` was stale before Session 239; classify-only init now passes the 2,500-character budget. Keep the test as a guard for future prompt growth.
  - `sh scripts/ci-check.sh` → all pass: ruff clean; pytest 1293 passed (61.18s); tsc clean; eslint 0 errors / 61 warnings (2026-08-12, Session 152)

## 2026-08-13 — Super Z / GLM-5.2 (Session 176 sandbox)

- **OS:** Linux 6.8 (Ubuntu), Python 3.12.13 (system), uv 0.x
- **Project root:** `/home/z/my-project/LocalMind`
- **Backend venv:** `backend/.venv` (Python 3.12.13 via uv)
- **Worklog:** `/home/z/my-project/worklog.md` (shared multi-agent log)
- **Verified commands:**
  - `git clone https://TisoneK:<PAT>@github.com/TisoneK/LocalMind.git` → OK (private repo; PAT stored at `secrets/github-pat` per the contract)
  - `sh .context/core/bin/context-sync verify` → core 0.5.0 integrity OK
  - `sh .context/core/bin/context-sync status` → up to date
  - `cd backend && uv venv .venv --python 3.12` → OK
  - `cd backend && sed 's|readme = "../README.md"|readme = "README.local.md"|' pyproject.toml > pyproject.install.toml && cp ../README.md ./README.local.md && mv pyproject.toml pyproject.orig.toml && mv pyproject.install.toml pyproject.toml && uv pip install --python .venv/bin/python -e '.[dev]' && mv pyproject.orig.toml pyproject.toml && rm -f README.local.md` → workaround for hatchling refusing `readme = "../README.md"` outside project dir. **Hatchling bug — uv `sync` doesn't work directly.** Use this pattern.
  - `cd backend && .venv/bin/ruff check .` → clean
  - `cd backend && .venv/bin/python -m pytest --co -q` → 1496 tests collected (matches Session 175's run)
  - Session 223 context-only audit (macOS 15 / Darwin 24.6.0): no product
    validation run by design; prior Session 222 backend/frontend baseline is
    retained above. `context-sync verify` and `context-sync status` were run
    before the audit.
- **Quirks:** The `python` command is 3.12.13 (good). Hatchling rejects
  `readme = "../README.md"` in `pyproject.toml` because the path is
  outside the backend project dir — workaround documented above. The
  venv survived between sessions on this sandbox (already existed).
