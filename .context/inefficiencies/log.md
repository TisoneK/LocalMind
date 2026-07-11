# Inefficiency Log (append-only, mandatory)

Every session appends one block — honestly. Friction you absorb silently
is friction the next agent hits blind. "None this session" is valid only
if literally nothing slowed you down.

---
## 2026-07-09 — Super Z / GLM-4.5 (Session 1)

- **Problem:** PAT pasted in the kickoff template file was redacted to `[REDACTED:github_token]` by the upload pipeline — agent couldn't clone the private repo.
- **Cost:** One full round-trip with the user (agent reported "PAT is a placeholder", user had to paste it in chat).
- **Cause:** The IM gateway / file-upload pipeline scrubs secrets from uploaded files before they reach the agent.
- **Workaround / fix:** User pasted the PAT directly in chat. Agent used it as a transient env var.
- **Prevent next time:** Protocol now documents this — PAT goes in chat, never in the file. The `ai-engineering-protocol.md` Pre-Flight section warns about this explicitly.

---
## 2026-07-09 — Super Z / GLM-4.5 (Session 1)

- **Problem:** `pip install -e ".[dev]"` failed with `externally-managed-environment` error on system Python.
- **Cost:** One failed command before creating a venv.
- **Cause:** System Python 3.12 on the sandbox is locked down per PEP 668.
- **Workaround / fix:** Created a venv: `python3 -m venv .venv && source .venv/bin/activate`, then `pip install` succeeded.
- **Prevent next time:** Protocol now says "ALWAYS create a virtualenv first" in Step 4 and lists it as Common Pitfall #3.

---
## 2026-07-11 — Super Z / GLM-4.5 (Session 2)

- **Problem:** `git push` failed after the first commit because the remote URL had been stripped of the token (Step 2 strips it for security).
- **Cost:** One failed push before figuring out the re-add-token → push → strip-token dance.
- **Cause:** The clone command embeds the token in the remote URL, which persists in `.git/config` on disk. Step 2 correctly strips it, but that breaks subsequent pushes.
- **Workaround / fix:** Re-add the token to the remote URL before push, push, then strip it again: `git remote set-url origin "https://x-access-token:${GIT_TOKEN}@..." && git push && git remote set-url origin https://github.com/...`
- **Prevent next time:** Protocol Step 12 now documents this explicitly with the exact commands. Common Pitfall #19 added.

---
## 2026-07-11 — Super Z / GLM-4.5 (Session 2)

- **Problem:** The LocalMind clone from Session 1 was gone — the sandbox wipes `/home/z/my-project/` between sessions (only `/home/z/my-project/download/` persists).
- **Cost:** Had to re-clone the repo (30s) and re-create the backend venv (60s). No work lost since everything was pushed to remote.
- **Cause:** Cloud sandbox environment — no persistent storage between sessions by design.
- **Workaround / fix:** Re-cloned and re-installed. All prior work was safely on `origin/main`.
- **Prevent next time:** This is inherent to the sandbox. The `.context/` system (now bootstrapped) means the next session will at least have full context of what happened before, even though the local clone is gone. No protocol change needed — just be aware that cloud sandboxes start fresh each session.

---
## 2026-07-11 — Super Z / GLM-4.5 (Session 2)

- **Problem:** The SSRF redirect bypass fix initially had a test failure — `_is_url_safe()` tried to resolve `attacker.example.com` via real DNS, which failed (the domain doesn't exist).
- **Cost:** One failed test run before mocking `_is_url_safe` directly.
- **Cause:** The test mocked `httpx.AsyncClient` but not `_is_url_safe` — the real function still ran and hit real DNS.
- **Workaround / fix:** Mocked `_is_url_safe` with `patch("tools.web_fetch._is_url_safe", side_effect=_fake_is_url_safe)` so the test isolates the redirect-following logic without DNS dependency.
- **Prevent next time:** When testing functions that call external network resolution, mock the resolution function too — not just the HTTP client. Added a comment in the test file explaining this.

<!-- Session 3 (GitHub Copilot / DeepSeek V4 Flash Free) had 4 workflow-level
     inefficiencies that were moved to flaws/log.md on 2026-07-11. Those
     entries were about the protocol/.context/ system itself, not about
     LocalMind's code/environment. See .context/flaws/log.md for the full
     entries. Project-level inefficiencies from Session 3 (if any) would
     appear below. -->


---
## 2026-07-11 — Super Z / GLM-5.2 (Session 7)

- **Problem:** The `workflows/active.md` Protocol source field contains a `blob/` URL (`https://github.com/TisoneK/.context/blob/main/ai-engineering-protocol.md`), not a `raw/` URL. Fetching it via `curl https://raw.githubusercontent.com/...` (the raw equivalent) returned 404. Had to clone the entire `TisoneK/.context` package repo to get the 53KB protocol file.
- **Cost:** One failed `curl` (404) + one `git clone --depth 1` of the package repo (~2s, 156KB). Minor — the clone worked fine and also gave me the `roles/` and `examples/` directories for reference.
- **Cause:** The `blob/` URL is the HTML page on GitHub (rendered markdown with navigation chrome), not the raw file. The protocol's Step 3 says "fetch it from the URL in the `Protocol source` field" — an agent following literally would fetch HTML, not raw markdown. The `raw/` equivalent (`https://raw.githubusercontent.com/TisoneK/.context/main/ai-engineering-protocol.md`) should work but returned 404 this session (possibly a caching/timing issue, or the default branch isn't `main`).
- **Workaround / fix:** Cloned `TisoneK/.context` fresh: `git clone --depth 1 "https://x-access-token:${GIT_TOKEN}@github.com/TisoneK/.context.git" _context_pkg`. Read `ai-engineering-protocol.md` from there. Stripped token from `_context_pkg/.git/config` after clone.
- **Prevent next time:** Update `workflows/active.md` Protocol source field to give BOTH the `blob/` URL (for human browsing) AND the `raw/` URL (for agent fetch), OR instruct agents to clone the package repo as the reliable fallback. The protocol's Step 3 could say: "If the raw URL 404s, clone `TisoneK/.context` with `--depth 1` and read the file locally." Logged as a flaw too.

---
## 2026-07-11 — Super Z / GLM-5.2 (Session 7)

- **Problem:** `npm install` emitted `allow-scripts` warnings for `electron@33.4.11` (postinstall: `node install.js`) and `esbuild@0.25.12` (postinstall: `node install.js`). The scripts were not run — npm 11's `allow-scripts` feature blocks postinstall scripts by default for security.
- **Cost:** Zero — the frontend typecheck (`tsc -b`), lint (`eslint .`), and build (`vite build`) all work without these scripts. Electron's postinstall downloads the Electron binary (only needed for `npm run dev:electron` / `npm run build` of the desktop app). esbuild's postinstall downloads the platform-specific binary — but Vite brings its own esbuild binary, so this is redundant.
- **Cause:** npm 11 (installed on this sandbox) enables `allow-scripts` by default. Older npm versions ran postinstall scripts automatically.
- **Workaround / fix:** No workaround needed for review/lint/test work. If a future session needs to build the Electron app (`npm run build`), run `npm approve-scripts --allow-scripts-pending` first, or `npm approve-scripts electron esbuild` for just those two.
- **Prevent next time:** Documented in `system/environments.md` Quirks section. Future sessions doing Electron builds: approve the scripts first.
