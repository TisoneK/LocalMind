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

## Z.ai cloud sandbox (last verified 2026-07-15)

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
