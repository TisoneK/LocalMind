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

---
## 2026-07-11 — GitHub Copilot / DeepSeek V4 Flash Free (Session 3)

- **Problem:** Jumped straight into editing `.context/` files when asked to "initialize .context/" — never stopped to read the workflow/protocol first. The `workflows/active.md` explicitly says the protocol is from `TisoneK/.context` and which edition to use, but I skipped that step and started making changes. User had to point out "Don't you have the workflow?"
- **Cost:** One full round-trip with user redirecting me. Had to redo the initialization context-aware after reading the protocol.
- **Cause:** No workflow-reading habit — treated the request as an editing task instead of following the protocol's execution steps. The protocol's Step 1 "Read the active workflow" is meant to prevent exactly this.
- **Workaround / fix:** User redirected me. Read the workflow, fetched the protocol from `TisoneK/.context` on GitHub, then started following Steps 2–6 properly.
- **Prevent next time:** Before ANY action — even "trivial" initialization — read `workflows/active.md` and fetch/load the protocol it references. The protocol's Phase 1 (Setup) exists to prevent this. Treat all user requests as protocol-governed unless stated otherwise.

---
## 2026-07-11 — GitHub Copilot / DeepSeek V4 Flash Free (Session 3)

- **Problem:** When looking for the protocol file, tried multiple wrong local paths: the VS Code prompts folder (`C:\Users\tison\AppData\Roaming\Code - Insiders\User\prompts`), workspace-wide `file_search` for `**/*protocol*` and `**/*.instructions.md` and `**/*.prompt.md`. All returned nothing because the protocol lives in a GitHub repo, not on the local filesystem. The workflow file already says "from the `TisoneK/.context` package" — I had the answer and didn't connect it.
- **Cost:** 4 failed search tool calls + wasted time before using `github_repo` to fetch the protocol content.
- **Cause:** Expected protocol files to be on local disk or in a standard VS Code path. Didn't map the phrase "from the `TisoneK/.context` package" to "fetch it from GitHub". The `workflows/active.md` already documents this clearly.
- **Workaround / fix:** Used `github_repo` to query `TisoneK/.context` for the protocol. Got the full protocol content.
- **Prevent next time:** When the workflow says "from the <owner>/<repo> package", use the GitHub repo tool to fetch it. Don't search local paths first. Better: read the workflow file's protocol field carefully before reaching for any tool.

---
## 2026-07-11 — GitHub Copilot / DeepSeek V4 Flash Free (Session 3)

- **Problem:** The initial `.context/` edits (registering agent in `ai-models.md`, adding environment to `environments.md`, logging session in `sessions.md`, updating `workflows/active.md`, setting `tasks/current.md`) were all done BEFORE reading and following the protocol. The changes themselves are correct, but the sequence violated the protocol's Step 2 (pull first) and Step 3 (read .context first, which I had read but not in order), and skipped Steps 4–6 (verify deps, read docs, discovery). The protocol's execution order exists so that the agent works from complete context, not partial context.
- **Cost:** Required a backtrack to re-do the discovery phase properly (pull, read docs, discover conventions). Edits themselves were fine but workflow was out of order.
- **Cause:** Treated "initialize .context/" as a standalone file-editing task rather than as a session that follows a protocol. The protocol makes every session follow the same 19 steps regardless of task size.
- **Workaround / fix:** Backtracked to Step 2 (pull), Step 3 (re-read .context), Step 4 (verify deps), Step 5 (read docs), Step 6 (discovery summary). Confirmed all prior edits were consistent with the protocol's requirements.
- **Prevent next time:** Follow the protocol steps in order from the first user request. Don't treat any task as "too small for the protocol." Phase 1 (Steps 1–6) must complete before any file editing begins.

---
## 2026-07-11 — GitHub Copilot / DeepSeek V4 Flash Free (Session 3)

- **Problem:** After finding the protocol, still needed manual user direction ("Don't you have the workflow?") to actually load it and follow it. The workflow file had been read in the very first tool calls but its implications weren't acted on.
- **Cost:** User had to explicitly tell me what I should have inferred from the data already in context.
- **Cause:** Read the workflow file passively (as documentation) rather than actively (as an instruction set to execute). The difference between reading and following.
- **Workaround / fix:** Once user pointed it out, fetched the protocol and began executing its steps.
- **Prevent next time:** Reading a workflow file IS a binding instruction — not informational reading. After reading `workflows/active.md`, immediately load and start executing the referenced protocol. Don't proceed with any tool use until the protocol is loaded.
