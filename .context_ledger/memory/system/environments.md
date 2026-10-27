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
## Tison's local Windows machine (last verified 2026-10-27)

- **Identify by:** OS is Windows; Tisone's dev account; hostname `DESKTOP-3LRR8MD`; repo checkouts seen: `C:\Users\Lameck\Tisone\LocalMind` (S449-S462) AND `C:\Users\tison\Dev\LocalMind` (S421-S449 era, again live 2026-09-11 S465) — both paths are the same Windows 11 box; check `pwd` rather than assuming either.
- **OS:** Windows 11 (PowerShell, Git Bash available)
- **Runtimes:** Node.js v24.20.0, Python 3.14.7, backend venv `backend/.venv/Scripts/python.exe` -> Python 3.11.0 (re-verified 2026-09-09, S455)
- **Package manager:** npm (root `package-lock.json` with workspaces); pip (system Python, not venv — on Windows, PEP 668 is advisory only)
- **Verified commands:**
  - `node --version` → v24.13.0 (2026-07-11, re-verified 2026-08-31)
  - `python --version` → Python 3.14.2 (2026-07-11, re-verified 2026-08-31)
  - `npm --version` → 11.12.1 (2026-07-11, re-verified 2026-08-31)
  - Git Bash is the working shell for `.context_ledger/core/bin/*` scripts; `pwsh` also available (2026-08-31)
  - `backend/.venv/Scripts/python.exe -m pytest tests -q` (repo root) → full backend suite; no pytest-timeout plugin here — do NOT pass `--timeout` (2026-09-04)
  - `backend/.venv/Scripts/python.exe -m pytest <files> -q` (from `backend/`) → targeted suites (2026-09-04)
  - `backend/.venv/Scripts/ruff.exe check backend/src` → All checks passed (2026-09-11; was 32–34 findings 2026-09-04/05 — compare failure SETS, not counts)
  - `sh .context/core/bin/context-sync verify` → core OK on 0.9.1 — CRLF-safe since the 0.9.1 update (557b1fc); update runs from the package checkout C:/Users/tison/Dev/context (2026-09-05)
  - `cd frontend && npx tsc -b --noEmit` → 0 errors (2026-09-04)
  - `cd frontend && npx vitest run` → 365 tests; **timeout-boundary tests flake under parallel local load** — a stashed baseline flaked 9 vs 1-2 on the changed tree; verify failures in isolation before believing them (2026-09-04)
  - Isolated live harness: from `backend/`, `LOCALMIND_PORT=8765 LOCALMIND_HOME=<scratch>/home LOCALMIND_SHELL_ENABLED=true .venv/Scripts/python.exe server.py &` + curl `/api/chat` — the Session-330 one-command pattern works; env-var prefixes survive Git Bash (2026-09-04). Script-based: copy `scripts/live_test_cybercafe.py`, swap PROMPTS — copy settings.json (WITH api_keys) into the scratch home so the isolated server authenticates; never print values (2026-09-05, S423)
  - Live-test harness port hygiene (S425): after kill_port, VERIFY 8765 is free and grep the new server log for "already in use" + a fresh "parent-kernel] ready" line before trusting a trace — a stale listener answers health checks and the client silently measures OLD code (cost one invalid after-run). ledger-collab.ps1: use `--refs`, not `--re` (the alias breaks pwsh parameter binding). (2026-09-06)
  - Live-test server on Windows: launch children with PLAIN Popen (no DETACHED_PROCESS) when the harness waits in `finally` — DETACHED_PROCESS + piped stdout killed the server mid-turn, no traceback, client saw WinError 10054 (2026-09-05, S423)
  - OCR stack in backend/.venv: pillow + pytesseract installed (2026-09-05, S423); system Tesseract-OCR at `C:\Program Files\Tesseract-OCR\tesseract.exe`; image reads + .jpg path extraction live-verified (2026-09-05, S423)
  - Live-verify on a CONTENDED port: when a peer batch holds 8765, boot the isolated server on 8766 instead (`LOCALMIND_PORT=8766 LOCALMIND_HOME=<scratch>/home LOCALMIND_ADAPTER=bankofai PYTHONPATH=<repo>/backend/src` + `backend/.venv/Scripts/python.exe server.py`, boot+curl+taskkill in one bash invocation) — never kill_port a peer's port, never edit their harness script mid-claim (2026-09-09, S455; settings.json copied into the scratch home, keys never printed)
  - OneDrive Files-On-Demand on this machine: placeholders carry RECALL_ON_DATA_ACCESS (0x400000); with OneDrive.exe DOWN every read fails EINVAL/WinError 362 and does NOT auto-hydrate; file_task now auto-starts OneDrive and hydrates on sync (~30s+ for first file after cold start) (2026-09-05, S423)
- **Quirks:**
  - Windows paths use backslashes; PowerShell handles both `/` and `\`
  - No `make` — use npm scripts or PowerShell equivalents
  - Python is system-wide (no venv isolation required on Windows, but still recommended for backend work)
  - This is a local development machine — persistent storage, full filesystem access
  - **`core.autocrlf=true` made `context-sync verify` false-positive** (all core files FAILED, git tree clean) — documented flaw B-2026-08-30-17. RESOLVED 2026-09-05: core 0.9.1 hashes CR-stripped content + `.context/.gitattributes` forces eol=lf; on 0.8.x cores the old signature still applies (don't rollback on it — update the core instead).
  - **Git Bash mangles `$VAR`-holding-Windows-paths inside compound commands**: `> "$SC/file"` where `SC="C:/..."` can resolve to `/file` (root) and fail with permission denied. Workaround: write a small bash script with the paths baked in (`scratch/s416/trace.sh` pattern) and run `bash <script>` — env-var prefixes for the server boot still work fine inline. (2026-09-04, Session 416)
  - Worktree gate/harness setup re-verified 2026-09-09 (S452): the three junctions (`backend/.venv`, root `node_modules`, `frontend/node_modules`) + `sh` gate runner + venv harness all work from a fresh worktree; `mklink /J` via `cmd //c` from Git Bash, delete junctions with plain `rmdir` (never recursive delete through one). Bare `python` is still the Store alias stub — use `backend/.venv/Scripts/python.exe`.
- Core sync verified 2026-09-10 (S458): `.context_ledger/core/bin/ledger-sync.cmd verify/status/update` all work from Git Bash in the MAIN checkout — `update` applied 0.20.0→0.21.0 cleanly (source must be a COMMITTED, manifest-consistent release in `C:/Users/Lameck/Tisone/context-ledger`; a dirty or unrelocked source is refused). `.cmd` gate/sync runs touch `memory/core.lock` (em-dash churn) — `git restore` it before staging the ledger surface.
- Worktree junctions re-verified 2026-09-10 (S460): creating links must go through a baked-paths .bat (`cmd //c 'mklink /J "..." "..."'` direct from Git Bash mangles quoted args → "Invalid switch"); detect with `fsutil reparsepoint query` via batch, unlink with plain `rmdir` on the link. `git worktree remove` + `git worktree prune` are then safe (no reparse points left to traverse).
- Live-test scripts run clean on this box (2026-09-10, S462): `cd backend && PYTHONPATH=../backend/src backend/.venv/Scripts/python.exe ../scripts/live_test_dir_explorer.py --label L --adapter zen|zai|bankofai` — self-contained boot on 8765 (`--port` for contention), provider key bridged from env `<PROV>_API_KEY` or the real settings.json via `harness_common.provider_key` (never printed); `MSYS_NO_PATHCONV=1 git show <rev>:<path>` — the plain form fails because Git Bash converts the colon-path (same mangling family as `cmd //c` and `$VAR` above). Provider status observed that day: zen free tier 400 "Model is unavailable" all session, bankofai `credit insufficient balance: balance=0` (owner top-up), zai flaky-with-rate-limits (cooldown ≥40s; one completed turn took 310s) — re-check providers before planning live work around one.
- Benchmark harness live-run verified 2026-09-11 (S465, from the `C:\Users\tison\Dev\LocalMind` checkout): `cd backend && backend/.venv/Scripts/python.exe ../scripts/lm_benchmark.py --tests <ids> --adapter bankofai --model qwen3.8-flash --timeout 45 --cooldown 20` — boots 8765 + scratch home, scores 13/13 tests, saves `scratch/sse-*` evidence. Two-junction worktree setup (root `node_modules` + `backend/.venv`, baked-paths .bat + `rmdir` teardown) sufficient for gate + harness runs; pre-commit gate green in the worktree. Provider status that day: bankofai free tier answers ONLY `qwen3.8-flash`/`glm-5.3-flash` at balance 0, 429 storms after a peer's heavy use (pace batches, cooldown ≥20s); zen/zai/cerebras/chutes down (S464 map), gemini untried.
- Context sync verified 2026-09-11 (S467, from the `C:\Users\Lameck\Tisone\LocalMind` checkout): `git pull --ff-only`, `ledger-sync.cmd verify` (core OK 0.22.0) + `status` (source `C:/Users/Lameck/Tisone/context-ledger` at 1.0.0 — MAJOR, owner go-ahead required before `update -Major`), `ledger-gates.cmd checkpoint` + `run pre-commit` all green from Git Bash. The `.cmd` verify/status runs re-churn `memory/core.lock`'s em-dash line (S458 note confirmed still true on 0.22.0) — `git restore` it before staging the ledger surface.
- Core 1.0.0 adoption verified 2026-09-11 (S467, same day): `ledger-sync.cmd update -Major` ran the office migration cleanly (flat memory → `memory/office/`, durable files stayed at root; update auto-committed nothing — regroup committed by hand per the owner's message). Update-flag spelling: POSIX port/CHANGELOG say `--major`, the Windows ps1 binds `-Major` — on this box run `.context_ledger/core/bin/ledger-sync.cmd update -Major`. `ledger-sync.cmd verify` OK on 1.0.0; `ledger-mem.cmd check` OK on the office paths.
- Core 1.0.2 sync verified 2026-09-11 (S468, from the `C:\Users\Lameck\Tisone\LocalMind` checkout): `ledger-sync.cmd update` applied 1.0.0→1.0.2 cleanly (same-MAJOR, no migration step; source `C:/Users/Lameck/Tisone/context-ledger` at a committed 1.0.2). **The `core.lock` churn notes above (S458/S467) are OBSOLETE on 1.0.2:** `Write-Lock` is now byte-identical between the sh and ps1 ports (em-dash written from `[char]0x2014`) — the pending one-time diff is the header upgrade `--`→`—`, and a second `.cmd` verify after the update produced zero further churn; stage the new lock normally. `verify` now also parse-checks every port ("every port parses"). **Windows gate rc is still NOT trustworthy on 1.0.2:** the S467 gate-teeth flaw survives the 1.0.1 fix (a configured command that prints to stdout and exits nonzero still yields `FAILED (N)` then `GATE PASSED` + rc=0; flaw log S468 has the probe + real-repo proof) — the interim rule stands: read gate output for `FAILED (N)` lines, never trust rc alone. The office migration also left `gates.conf`'s backlog-dup line pointing at the dead pre-migration path `memory/tasks/backlog.md` (silently red, invisibly, since 1.0.0 adoption because of those broken teeth) — re-pointed to `memory/office/tasks/backlog.md` this session.
- Core 1.0.4 sync verified 2026-09-11 (S470, from the `C:\Users\tison\Dev\LocalMind` checkout): the 1.0.3/1.0.4 cores arrived via `git pull` (S469's push) and `ledger-sync.cmd update` then applied the same-MAJOR bump 1.0.2→1.0.4 from the local package clone — note the source is `C:/Users/tison/Dev/context-ledger` on THIS checkout, a different package path than the S467/S468 Lameck-checkout clone (`C:/Users/Lameck/Tisone/context-ledger`); `status` reports whichever clone is adjacent to the current checkout, both at 1.0.4. `core.lock` stayed churn-free through `.cmd` verify + update (the 1.0.2 Write-Lock fix holds); `verify` OK on 1.0.4 ("every port parses").
- Collab worktree verified 2026-09-12 (S472/Omari, from the `C:\Users\tison\Dev\LocalMind` checkout): one-junction worktree (`git worktree add ../LocalMind-omari-s472 -b …` + root `node_modules` junction via `powershell -NoProfile -Command "New-Item -ItemType Junction …"` — first try) was sufficient for frontend gates (tsc/eslint/vite/vitest all ran from the worktree `frontend/` through the junction); no backend venv needed for a frontend-only session. Teardown order per S469: `cmd /c rmdir` the junction before `git worktree remove`. Git-Bash cwd trap on this box: bare `cd C:\Users\…` in double quotes loses the backslashes (`/c/Userstison…`); always `cd /c/Users/tison/…`. Frontend has NO own node_modules — the npm workspace hoists to the root (`ci-check.sh` accepts either; the junction covers both).
- Core 1.1.3 sync verified 2026-09-15 (S004, from the `C:\Users\Lameck\Tisone\LocalMind` checkout): `ledger-sync.cmd verify` OK on 1.1.1, `status` saw source `C:/Users/Lameck/Tisone/context-ledger` at 1.1.3, `update` applied 1.1.1->1.1.3 cleanly (same-MAJOR PATCH, no migration step); `core.lock` staged normally. **Provider state as of 2026-09-15: bankofai is QUOTA-EXHAUSTED (400 `credit insufficient balance: balance=0`) — the primary live-test provider is unusable until the owner tops up/re-keys; zai works.**
- Core 1.0.5 sync verified 2026-09-12 (S473, from the `C:\Users\Lameck\Tisone\LocalMind` checkout): `sh .context_ledger/core/bin/ledger-sync verify` OK on 1.0.4 ("every port parses"), `status` saw source 1.0.5 in the Lameck-adjacent package clone (`C:/Users/Lameck/Tisone/context-ledger`), `update` applied 1.0.4→1.0.5 cleanly (same-MAJOR PATCH — backlog priority-table format only, no migration step); `core.lock` staged normally, churn-free. `ledger-gates`, `ledger-collab emit note/claim`, and `ledger-mem lint` all ran green via the sh ports from Git Bash. Entry-point note: the update refreshes `.context_ledger/README.md` itself but root `AGENTS.md` must be regenerated by hand when its template changes (done this session via `sed 's/<PROJECT_NAME>/LocalMind/g'`).
- Pull + protocol sync verified 2026-10-27 (S007, Lameck checkout): `git pull --ff-only` fast-forwarded `5ea4bef3..dc0ea44c` (61 files); `sh .context_ledger/core/bin/ledger-sync verify` OK on 2.2.0 ("every port parses"); `status` 2.2.0 up to date (refreshes `core.lock` with source metadata — stage it normally); `ledger-guard install` OK (pre-commit, prepare-commit-msg and pre-push hooks; `.claude/settings.json` already present); node v24.20.0 / Python 3.14.7 re-confirmed.

## Z.ai cloud sandbox (last verified 2026-10-26, Session S004)

- **Identify by:** workspace path `/home/z/my-project/`; env vars `FC_FUNCTION_NAME` / `SIGMA_APP_NAME` present; `CLAWHUB_WORKDIR=/home/z/my-project`
- **OS:** Linux 6.5 (Ubuntu-based, containerized — `KATA_CONTAINER=true`)
- **Runtimes:** Python 3.12.15, Node v24.21.0, npm 11.19.0 (re-verified 2026-10-26, S004; bun no longer observed on PATH)
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
  - **Background processes die immediately (Session 410):** `nohup <cmd> &` and `<cmd> & disown` both die when the parent Bash command returns — the sandbox shell reaps backgrounded children. This affects venv installs, full pytest runs, and any long-running command you try to background. Workaround: run long commands SYNCHRONOUSLY with a long timeout (300s+). The committed live-test harness scripts (`scripts/live_test_*.py`) are the exception — they manage `subprocess.Popen` + `kill_process_tree` internally and run fine synchronously. The `live-testing.md` "Harness gotcha (Session 330)" note documents this for the live-test server specifically; it generalizes to ALL backgrounded commands.
  - **Bash tool resets working directory (Session 410):** each Bash tool call starts at `/home/z/my-project`, and `cd /home/z/my-project/LocalMind && <cmd>` gets the cd stripped (likely a shell-quoting artifact). Workaround: use `git -C /home/z/my-project/LocalMind <cmd>` for git, and absolute paths (`/home/z/my-project/LocalMind/backend/.venv/bin/python`) for python/pip. Never rely on `cd` at the start of a Bash command.
  - **bankofai transient 400 on replan calls (Session 410):** bankofai can return HTTP 400 (`{"error":{"message":"openai_error","type":"bad_response_status_code",...}}`) on a gate-replan iteration mid-turn. This looks like a regression but is transient — re-run the SAME prompt to confirm. The live-testing protocol already notes "bankofai rate limits surface as an error event INSIDE the SSE stream (200 to the proxy)" but a 400 (vs 429) on a replan specifically is a new variant. Don't claim a regression without a reproducing second run.
  - **Verified commands (Session 65, 2026-08-02 — research-only, no venv/baseline re-run):**
    - `git clone "https://x-access-token:${GITHUB_PAT}@github.com/TisoneK/LocalMind.git"` → succeeded; PAT stripped from `.git/config` via `git remote set-url origin https://github.com/TisoneK/LocalMind.git` immediately after
    - `git config user.name "Tisone Kironget" && git config user.email "tisonkironget@gmail.com"` → set local git identity (sandbox default is `Z User <z@container>`, must be overridden)
    - `git pull --ff-only` → "Already up to date." (on `main`)
    - `sh .context/core/bin/context-sync verify` → "core OK: every file matches MANIFEST.sha256 (0.5.0)"
    - `sh .context/core/bin/context-sync status` → "core: 0.5.0, locked: 0.5.0, source: none reachable — skipping, this is fine"
    - `git clone https://github.com/CodebuffAI/open-codebuff.git` → succeeded (public, anonymous HTTPS, no auth needed)
- **Verified commands (2026-10-26, Ezra S004 — fresh sandbox wipe, full bring-up):**
  - `git clone https://github.com/TisoneK/LocalMind.git` → succeeded (public, anonymous; PAT wired for push only via a file-based credential helper outside the repo, never in `.git/config` at rest)
  - `cd backend && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"` → succeeded (all wheels; no compiler issues)
  - `npm install` (repo root, workspaces) → 914 packages, 0 vulnerabilities, ~12s
  - `cd frontend && npm run build` (tsc -b + vite build) → green in ~6s (684KB main chunk, chunk-size warning only)
  - Smoke: `(backend/.venv/bin/python backend/server.py &)` + `curl /api/health` on :8000 → HTTP 200, `engine_ready=true`, `parent_ready=true` (provider_reachable=false — Ollama not installed in sandbox; expected). NOTE: `uvicorn src.api.app:app` is NOT a valid target — the ASGI app is created by `backend/server.py`.
  - `sh .context_ledger/core/bin/ledger-sync verify` → core OK (2.0.4); `ledger-sync status` → no update source reachable, skipped
  - Smoke caveat: the subshell-background trick `(&)` + curl in ONE Bash call worked here, but per Session 410 the safe pattern is still single-invocation self-contained commands (the smoke was one command).

## Local macOS development machine (last verified 2026-09-10, Session 464)

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
  - Session 266 targeted run: `cd backend && .venv/bin/python -m pytest ../tests/storage/test_db.py ../tests/api/test_chat.py ../tests/core/test_guaranteed_persist.py -q` → 56 passed; full backend `pytest ../tests -q` → 1827 passed, 2 skipped, 4 pre-existing shell failures (verified pre-existing via git stash); frontend `npx vitest run` → 226 passed (27 files); `npx tsc -b` + `npx vite build` clean. (2026-08-16, Session 266)
  - **Ollama IS NOW INSTALLED on this machine (2026-08-17, Session 291) — the LOCAL path can finally be live-tested** (Sessions 287–290 kept shipping Ollama fixes "not verified on the user's box"; that caveat is retired). `ollama` reachable at `http://localhost:11434`; pulled models: `phi4-mini:latest` (chat, declares 131072 ctx) + `mxbai-embed-large:latest` (embeddings). Live-test recipe: boot the isolated harness with `LOCALMIND_ADAPTER=ollama OLLAMA_MODEL=phi4-mini:latest` (NO settings.json copy needed — Ollama needs no key), on `LOCALMIND_PORT=8765` + a scratch `LOCALMIND_HOME`. Verified S291: "Hi" → `mode=direct`, 0 tool_calls, ~46-50s (was a 247s tool-loop hang); "list files" → `mode=execute conf=1.00` (execute still works); `/api/models` context_window=32768; `_extract_context_length` against real `/api/show`=131072. **phi4-mini is SLOW: num_ctx load is 8192→13s / 32768→29s / 131072→84s (KV-cache prealloc); generation is ~0.2-1 tok/s** — a real tool-loop task can exceed 2 min, so use `curl --max-time 280` and expect long waits (not a hang). Its `/api/show` model_info has BOTH `phi3.context_length` (131072) and `phi3.rope.scaling.original_context_length` — match the canonical arch key, not any `.context_length` suffix. (2026-08-17, Session 291)
  - **Session 291 full suite is GREEN: `pytest ../tests -q` → 1916 passed, 2 skipped, 0 failures.** The long-standing "4 pre-existing shell + 1 model_router" failures were FIXED at the root this session (test-isolation bugs: shell tool disabled-by-default precondition; model_router not isolating from real saved keys) — do NOT reintroduce the "pre-existing, not mine" dismissal. (2026-08-17, Session 291)
  - Full backend suite → 2077 passed / 2 skipped / 0 failures; `backend/.venv/bin/ruff check backend/src` clean; pre-commit gate (`cd frontend && npx tsc -b --noEmit` + ruff) passed (2026-08-20, Session 323)
  - Live harness on bankofai/deepseek-v4-flash (the ACTIVE provider/model in `~/LocalMind/settings.json` since Session 322): isolated 8765 + scratch `LOCALMIND_HOME` (copy of settings.json, chmod 600) + `LOCALMIND_SHELL_ENABLED=true`; boot+curl+kill in ONE terminal command (Session 251 recipe — the shell reaps backgrounded servers otherwise). 3 traces of the "create a project" task reproduced the user's failure and verified the nudge fix (narration → anchored nudge → mkdir/file_write). Model LLM calls were fast (1.8-6.2s). (2026-08-20, Session 323)
- **Quirks:** The `python` command is unavailable and system `python3` is 3.9.6, below the backend's `>=3.10` requirement; use `backend/.venv/bin/python` (Python 3.12.13 via uv). Backend Ruff currently reports 132 E501 findings plus 3 non-E501 findings. `npm ci` reported 18 dependency vulnerabilities (17 high, 1 critical) and deprecated transitive packages. Local agent uses the user's existing git credentials and does not need a PAT for this public clone. The optional `agent-browser` CLI is not installed; BrowserAgent tests must mock `_run_browser_cmd` unless the CLI is installed for live smoke testing.
  - **Port 8000 is ALWAYS occupied** by the user's running LocalMind app instance — start trace servers on `LOCALMIND_PORT=8765` instead; never kill the user's instance.
  - **The ACTIVE provider is gemini-2.5-flash**, set via the app's Settings UI (its key is NOT in `backend/.env` — only `ZEN_API_KEY` is). The server startup log prints `adapter: <x> | model: <y>` — read it to learn the real active provider.
  - **Live recovery trace (Session 299, 2026-08-19):** isolated `LOCALMIND_HOME` + copied settings + `LOCALMIND_PORT=8765` + real z.ai `glm-4.5-flash` with thinking enabled successfully exercised a missing-path shell failure; the SSE carried `success:false`, `error_type=command_failed`, failed `tool_call`, `evidence_to_parent.failed=true`, `[RECOVERY]`, and no `agent_thinker_start`. A second corrective-follow-up trace was blocked by z.ai HTTP 429 and is not considered verification.
  - **Live capability A/B (Session 300, 2026-08-19):** same isolated z.ai/GLM task on committed HEAD vs working tree — parent initialization dropped from 19,956ms / 930 prompt tokens to a deterministic 2ms / 12 estimated prompt tokens; `Like what?` also completed in 2ms with distinct examples. Final smoke carried `fast_path=true` plus truthful skipped/done stage timings.
  - **Live generic direct boundary (Session 301, 2026-08-20):** isolated z.ai/glm-4.5-flash with thinking enabled verified generic conversational shapes and the exact `What can you do?` → `Like what` flow through one context-aware chat boundary; a real file-list request stayed `fast_path=false`, `mode=execute`, and made four shell calls. Final full CI 1996 passed / 2 skipped.
  - **`LOCALMIND_SHELL_ENABLED=false` in `backend/.env`** — trace servers must set `LOCALMIND_SHELL_ENABLED=true` or the shell tool reports "Shell tool is disabled".
  - **No `timeout` CLI on macOS** (GNU coreutils) — use `curl --max-time N`.
  - **BSD awk (`/usr/bin/awk`; `gawk` is NOT installed) aborts on non-UTF-8 bytes — so `ledger-collab check` can fail SILENTLY here (rc=2, no verdict, only `awk: towc: multibyte conversion failure`).** Six legacy markdown collab events carry a bare `0x97` (Windows-1252 em-dash) written by Windows agents. **Always run the ledger helpers as `LC_ALL=C sh .context_ledger/core/bin/ledger-collab …`** on this machine; the check then returns a real verdict. (2026-09-10, Session 464 — see inefficiencies/log.md.)
  - **Live-test provider reality (2026-09-10, Session 464):** this machine's `~/LocalMind/settings.json` has keys for bankofai/cerebras/chutes/gemini/zai/zen. Probed: **gemini up**; **bankofai key valid but its configured default `deepseek-v4-flash` is DELISTED** (free tier answers on `qwen3.8-flash` / `glm-5.3-flash` at balance 0; `/v1/models` returns 47 ids); zen 403 (Cloudflare 1010), cerebras 403 (1010), chutes 402 (balance $0), zai 401 (key expired). Don't trust an adapter's `default_model` for live work — probe it first.
  - `test_prompt_budget.py::test_init_prompt_is_under_budget` was stale before Session 239; classify-only init now passes the 2,500-character budget. Keep the test as a guard for future prompt growth.
  - `sh scripts/ci-check.sh` → all pass: backend 1996 passed / 2 skipped; Ruff clean; TypeScript clean; ESLint 0 errors / 71 existing warnings (2026-08-20, Session 302)
  - Isolated live harness on port 8765: z.ai/glm-4.5-flash direct native parent turn → no initializer event, one iteration, 1621 provider prompt tokens; Zen/hy3-free tool turn → describe_tool(shell) then shell execution; Cerebras headroom trace returned real 402 payment_required (2026-08-20, Session 302)
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
