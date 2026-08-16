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

---
## 2026-07-27 — Super Z / GLM-5.2 (Session 31)

- **Problem:** The `docs/shell_tool_fix_analysis.md` doc was misleading on first read — it diagnoses the `re` conditional-import bug as the root cause of the user's "Tools execution failure" symptom, but that bug was already fixed in a prior session. I spent ~10 minutes verifying the shell tool was healthy before realizing the doc was stale and the actual remaining bug was the silent-failure FALLBACK PATH in the engine + agent loop.
- **Cost:** ~10 minutes of redundant code reading + a brief detour thinking I'd need to fix `shell.py` before realizing the tool was already healthy.
- **Cause:** The doc was written when the bug was live; it was never updated after the fix landed. Future agents reading it as authoritative would re-investigate the same already-fixed code.
- **Workaround / fix:** Verified the current state of `shell.py` directly (`import re` at line 38 — top of module; `SYSTEM = platform.system()` at line 54 — resolved once). Identified the real remaining bug (silent-failure fallback) by tracing the user's exact symptom through the code.
- **Prevent next time:** Backlogged: delete or rewrite `docs/shell_tool_fix_analysis.md` to reflect the current state. Either remove it (the analysis is historical) or convert it to a "historical record" section noting which items are fixed. A future session should pick this up.

---
## 2026-07-27 — Super Z / GLM-5.2 (Session 31)

- **Problem:** `AgentStep` dataclass requires `tool_input` and `observation` as positional args (no defaults), but the existing test pattern in `tests/core/test_empty_agent_fix.py` constructs it with positional args in some places and keyword args in others. When writing the new regression test, I used keyword-only args and missed `tool_input`/`observation` — got a `TypeError` on the first test run.
- **Cost:** One failed test run + one quick Edit to fix.
- **Cause:** `AgentStep`'s required fields aren't documented in the dataclass docstring; you have to read the definition or look at existing usage.
- **Workaround / fix:** Added the missing `tool_input=None, observation=None` kwargs to the test. Test passed on next run.
- **Prevent next time:** When constructing `AgentStep` in tests, always pass all required fields explicitly — don't rely on defaults that don't exist. Could be fixed at the source by giving `tool_input` and `observation` default values of `None`, but that's a behavior change for another session.

---
## 2026-07-27 — Super Z / GLM-5.2 (Session 31, addendum)

- **Problem:** I shipped a fallback message that guessed "free-tier model overload" as the cause of the "Tools execution failure" bug — WITHOUT testing against the real model first. The user correctly pushed back: "for a 4-step task, context overflow is not plausible." The "overload" diagnosis was a plausible-sounding but unverified self-diagnosis — same pattern as the earlier "tool output too large" message that turned out to be wrong.
- **Cost:** Two extra commits (f316904 + d09327c) and one extra round-trip with the user. The first fix (08d1934) was treating the symptom, not the cause. The revision (f316904) made the fallback more honest but was STILL treating the symptom. The actual root cause (two adapter bugs) wasn't found until the user provided an API key for real-model testing.
- **Cause:** I trusted my own plausible-sounding guess instead of testing it. The fallback message was written BEFORE any real-model testing. When the user pushed back, it took 10 minutes and 2 API calls to find the actual bug — should have done that FIRST.
- **Workaround / fix:** Real-model testing via the user's Zen API key found the root cause: (1) DeepSeek rejects messages ending with `tool` role → HTTP 400; (2) Phase 1 detection dropped tool_call deltas during long reasoning streams. Both fixed in commit d09327c.
- **Prevent next time:** When a fallback message GUESSES at a cause, treat the guess as a hypothesis to test, not a diagnosis to ship. If the user can provide an API key for the failing model, test against the real model BEFORE writing the fallback. The real-model test is almost always faster than the guess-revise-guess cycle. Logged as a flaw in `flaws/log.md` too — this is a protocol-level lesson, not just a project-level inefficiency.

---
## 2026-07-27 — Super Z / GLM-5.2 (Session 33)

- **Problem:** I shipped Session 32's fix (iteration limit + safety workflow + hit-limit-aware fallback) WITHOUT reading the flaw log first — and the flaw log explicitly contains the Session 31 lesson "don't ship without real-model testing." I repeated the exact same mistake: shipped code that broke the SSE stream because I didn't test against the real model.
- **Cost:** One broken session for the user (tools hung at "Running command") + one emergency fix session (Session 33). The user's trust in fix quality is eroded — "we have broken the tools again" is the third iteration of this pattern.
- **Cause:** I treated the `.context/` flaw/inefficiency logs as end-of-session bookkeeping instead of live diagnostic tools. The protocol requires reading them BEFORE starting work (to not re-hit logged traps) and appending AS I hit friction. I skipped the "read first" step.
- **Workaround / fix:** Found the regression by code inspection: Session 32's engine fallback called `_obs.drain()` (destructive) instead of `_obs.all()` (read-only), stealing events from the SSE bridge. Fixed in this session. But the deeper fix is process-level: I need to actually READ `flaws/log.md` and `inefficiencies/log.md` before starting any code changes.
- **Prevent next time:** BEFORE writing any code in a session, read `.context/memory/flaws/log.md` and `.context/memory/inefficiencies/log.md` IN FULL. Look for patterns that apply to the current task. If a prior session logged "don't do X without testing Y," and the current task involves X, test Y before shipping. This is the protocol's intended workflow — I've been skipping it.

---
## 2026-07-27 — Super Z / GLM-5.2 (Session 33 — ZenMux smoke test blocked)

- **Problem:** Tried to smoke-test the ZenMux provider (ADR-9) with the user's API key. The key authenticates (`GET /api/v1/models` returns 200 with 145 models) but every `POST /api/v1/chat/completions` returns 403 "You have no permission to access this resource." Tested 8 models across 6 providers (Grok 4.5, Claude Opus 5, Gemini 3.6 Flash, GPT-5.6 Luna, GLM-5.2, Ling 3.0 Flash, Kimi K3, MiniMax M3) — all 403. It's not a model-specific issue; it's an account-level access issue.
- **Cost:** ~10 minutes of testing before realizing the account can't make API calls at all. The smoke test caught this BEFORE any integration code was written — which is exactly what the smoke test is for. No code wasted.
- **Cause:** The user is on ZenMux's free plan ("5 Flows/5h, $0"), which explicitly states "Studio Chat only" and "No API Request access." The `/models` endpoint isn't gated (listing models is free), but `/chat/completions` requires a paid plan. The free Builder tier mentioned in the web research (~165 flows/month) apparently doesn't include API access either — it's Studio Chat only.
- **Workaround / fix:** None possible in code. The user needs to upgrade to a ZenMux plan that includes API access. Per ZenMux's pricing: Pro ($20/mo) adds latency/throughput insurance; Max ($100/mo) adds hallucination coverage; Ultra ($400/mo) includes SLA guarantees. Actual model usage is pay-as-you-go per-token against a topped-up balance, separate from the subscription. The user should check zenmux.ai for which plan includes API access — it may be that ANY paid plan unlocks it, or it may require a specific tier.
- **Prevent next time:** When integrating a new provider, check the plan requirements BEFORE requesting an API key. The web research for ADR-9 mentioned "free Builder subscription tier for personal development, capped at roughly 5 flows per 5 hours" — but didn't catch that this tier is Studio Chat only with no API access. ADR-9 has been updated to note: "the free plan does NOT include API access — a paid plan (Pro/Max/Ultra) is required for LocalMind integration." Future provider integrations should verify API access is available on the user's plan before starting the smoke test.

---
## 2026-07-31 — Buffy / openai/gpt-5.6-luna (Session 36)

- **Problem:** The first baseline command used `python -m pytest`, but this macOS environment exposes only `python3`, and its system Python 3.9.6 is below the backend's declared Python >=3.10 requirement.
- **Cost:** One failed baseline invocation and a short setup detour.
- **Cause:** The local environment differs from the previously recorded Windows/cloud environments, and the generic command did not account for the backend's version constraint.
- **Workaround / fix:** Reused the installed uv-managed Python 3.12.13, created `backend/.venv`, installed `backend[dev]`, and ran validation through `backend/.venv/bin/python`.
- **Prevent next time:** Check `pyproject.toml`'s `requires-python` and available uv interpreters before running Python baseline commands; prefer the project-local venv path.

---
## 2026-07-31 — Buffy / openai/gpt-5.6-luna (Session 37)

- **Problem:** The first reviewer report was returned as an internal reasoning fragment rather than a structured review summary, and the frontend has no test harness for its critical SSE parser.
- **Cost:** Review interpretation required an additional pass; the parser issue can currently be verified by code inspection but not locked with a frontend regression test.
- **Cause:** The project has strong backend coverage but no frontend tests, while the UI transport contract is split between a native stream parser and React state handlers.
- **Workaround / fix:** Used the backend API regression test for the shipped contract fix, validated the frontend with production build/lint, and recorded the parser follow-up separately instead of mixing it into the first fix.
- **Prevent next time:** Add a small frontend test harness around the SSE parser before changing more UI transport behavior.

---
## 2026-07-31 — Buffy / openai/gpt-5.6-luna (Session 38)

- **Problem:** The frontend stream parser had no executable test boundary, so the final-buffer transport defect could only be identified by inspection during Session 37.
- **Cost:** The requested fix required introducing the first frontend test runner while repairing the parser.
- **Workaround / fix:** Added the project-local Vitest script/dependency, extracted a pure SSE parser, and locked the unterminated-event behavior with focused tests.
- **Prevent next time:** Keep transport helpers independently testable and add a public `streamChat()` integration fixture before changing additional UI stream behavior.

---
## 2026-07-31 — Buffy / openai/gpt-5.6-luna (Session 50)

- **Problem:** The optional `agent-browser` CLI was not installed on this macOS checkout, so live BrowserAgent smoke testing could not run.
- **Cost:** No code rework; live validation was deferred after the mocked contract tests passed.
- **Cause:** Browser automation is an optional external CLI dependency and is not installed by default in this environment.
- **Workaround / fix:** Verified the documented command syntax through authoritative documentation and tested the wrapper at its subprocess boundary with 50 focused mocked tests.
- **Prevent next time:** Install `agent-browser` and Chromium before a session that requires live browser verification; keep mocked tests as the deterministic regression layer.

---
## 2026-07-31 — Buffy / openai/gpt-5.6-luna (Session 52)

- **Problem:** The kickoff backend baseline is not fully green: one existing todo-plan assertion expects the older first-step label, while the current engine emits `Understand: ...`. Ruff also reports three non-E501 findings among the known line-length backlog.
- **Cost:** No implementation delay; the issue was documented rather than changed during a context-only kickoff.
- **Cause:** The test and current plan wording drifted across prior feature work, and safe lint cleanup was not folded into the related commits.
- **Workaround / fix:** Recorded the exact failing test and Ruff findings in the Session 52 review and environment handoff. No product changes were made.
- **Prevent next time:** Reconcile the todo-plan UI/test contract and clean the three non-E501 Ruff findings in a dedicated safe-fix session before starting the capability-family implementation.

---
## 2026-07-31 — Buffy / openai/gpt-5.6-luna (Session 53)

- **Problem:** No new implementation friction. The existing backend baseline still contains the known todo-plan assertion drift, so the full suite is not completely green.
- **Cost:** No rework; the catalog was validated independently and the unrelated failure was preserved rather than changed opportunistically.
- **Cause:** The test expects older wording than the current engine plan output.
- **Workaround / fix:** Recorded the failure separately and kept the new capability catalog behavior isolated from todo-plan semantics.
- **Prevent next time:** Reconcile the todo-plan test/UI contract in a dedicated safe-fix session before expanding runtime capability discovery.

---
## 2026-07-31 — Buffy / openai/gpt-5.6-luna (Session 54)

- **Problem:** The first observation implementation used a frozen outer dataclass while exposing mutable nested workspace/event objects.
- **Cost:** One review/fix cycle; no shipped defect because the issue was caught before commit.
- **Cause:** Top-level dataclass freezing was initially treated as sufficient snapshot immutability.
- **Workaround / fix:** Added private owned copies plus defensive-copy accessors and regression tests for source and accessor mutations.
- **Prevent next time:** Treat nested compatibility objects as mutable unless the ownership boundary is explicit; test both producer-side and consumer-side mutation.

---
## 2026-07-31 — Buffy / openai/gpt-5.6-luna (Session 55)

- **Problem:** A final runtime snapshot initially read only the pending event queue, so events already flushed by the SSE bridge would be missing.
- **Cost:** One review/fix cycle; no shipped defect because the gap was caught before commit.
- **Cause:** The existing collector intentionally makes `drain()` destructive, and the first integration reused `all()` without modeling full request history separately.
- **Workaround / fix:** Added `ObsCollector.history()` while preserving `all()`/`drain()` semantics; snapshots now capture full request history before the final drain.
- **Prevent next time:** Separate pending-queue semantics from request-history semantics whenever a stream has multiple consumers.

---
## 2026-07-31 — Buffy / openai/gpt-5.6-luna (Session 57)

- **Problem:** The first frontend observation mapper trusted the typed API response at runtime; malformed nested fields could have crashed the Observe panel.
- **Cost:** One review/fix cycle and two focused regression cases; no shipped defect because the issue was caught before commit.
- **Cause:** TypeScript interfaces describe expected payloads but do not validate JSON received over the network.
- **Workaround / fix:** Added a defensive client-boundary mapper for strings, numbers, arrays, events, and build metadata, plus legacy-null and malformed-payload Vitest coverage.
- **Prevent next time:** Treat every API response as untrusted at the client boundary and add malformed-payload coverage whenever a new nested response shape is introduced.

---
## 2026-08-01 — Buffy / openai/gpt-5.6-luna (Session 63)

- **Problem:** The real-time Observe metrics fix was validated but left uncommitted while the prior session had already been reported complete.
- **Cost:** One corrective closeout pass and an additional product/context commit cycle.
- **Cause:** The implementation flow stopped after review and testing instead of running the repository exit checklist through commit, push, context update, and clean-tree verification.
- **Workaround / fix:** Committed the product surface as `8f253bf`, pushed it, then prepared a separate context closeout with review, session, summary, environment/model, feature, and friction updates.
- **Prevent next time:** Treat validation as an intermediate gate only; always run the two-surface exit checklist before reporting completion, including `git status --short --branch` and remote synchronization.

---
## 2026-08-02 — Super Z / GLM-5.2 (Session 65)

- **Problem:** I produced the entire Codebuff research package (~2,300 lines across 6 files) at `/home/z/my-project/download/codebuff-research/` BEFORE loading the protocol edition (`.context/core/rules/ai-engineering-protocol.md`). The protocol requires reports in `.context/memory/reviews/` and session notes in `.context/memory/sessions/`. I had to move all the content into the repo's `.context/memory/` structure and delete the bogus `kickoff.md` I had created. The user caught the kickoff.md mistake; the rest of the package was salvageable (comparison.md, recommendations.md, codebuff-deep-profile.md were good content, just in the wrong location).
- **Cost:** ~20 minutes of wasted work creating the `/download/` package + ~10 minutes moving content into the repo's `.context/memory/` + one user round-trip ("was kickoff.md read-only or create???"). The research itself was not wasted — only the packaging location was wrong.
- **Cause:** I read `.context/kickoff.md` (Step 2 of the kickoff) but skipped Step 3 ("Load the protocol" — `.context/core/rules/ai-engineering-protocol.md`). Without the protocol loaded, I didn't know that reports belong in `.context/memory/reviews/YYYY-MM-DD-review.md` (per Step 13 of the protocol) or that session notes belong in `.context/memory/sessions/YYYY-MM-DD-N/notes.md` (per Step 17). I defaulted to writing to `/home/z/my-project/download/` (the sandbox's user-downloadable directory) because that's where my system prompt says deliverables go — but the `.context/` protocol overrides that for `.context/`-managed repos.
- **Workaround / fix:** Deleted the bogus `kickoff.md`. Loaded the protocol edition. Moved the research content into the repo: review report → `.context/memory/reviews/2026-08-02-review-1.md`, full research detail → `.context/memory/sessions/2026-08-02-1/` (notes.md + codebuff-deep-profile.md + comparison.md + recommendations.md), backlog items → `.context/memory/tasks/backlog.md`. Committed and pushed per the protocol's two-surface rule (`docs(review):` for the report, `chore(context):` for the memory updates).
- **Prevent next time:** ALWAYS load the protocol edition (Step 3 of kickoff) BEFORE producing any deliverable. The protocol tells you WHERE outputs go. Skipping Step 3 because "the task seems small" or "I know what a report looks like" is the exact anti-pattern the protocol warns about (Step 4: "Don't skip Phase 1 because the task seems small"). For `.context/`-managed repos, the protocol's output locations override the sandbox's `/home/z/my-project/download/` default. Also logged as a flaw — the kickoff template could be clearer that it's READ-ONLY.

---
## 2026-08-02 — Super Z / GLM-5.2 (Session 65, second inefficiency)

- **Problem:** I stored the GitHub PAT and ZEN_API key in `/home/z/my-project/.secrets.env` (a single file, `.env` extension, outside the `.context/` structure) instead of `.context/memory/secrets/<slug>` (one secret per file, per the secrets README contract). The user caught it: "You also created your own secrets instead of reading how to use it in .context."
- **Cost:** ~5 minutes to create the proper secret files (`github-pat` and `zen-api` in `.context/memory/secrets/`), delete the improper `.secrets.env`, verify gitignore + chmod 600, and log the flaw. Minor in time, but it's a second protocol violation in the same session (after the kickoff.md mistake) — both rooted in the same cause: skipping Step 3 (load the protocol edition).
- **Cause:** I read `.context/memory/secrets/README.md` during Step 2 (the memory sweep) but treated it as passive documentation rather than a binding contract. When the user provided the PAT and ZEN_API in chat, I defaulted to the sandbox convention (`.env` file at workspace root) instead of the project convention (`.context/memory/secrets/<slug>`). The connection between "secrets/README.md describes a contract" and "I must use this contract when I receive credentials" wasn't made because I hadn't loaded the protocol edition (Step 3) that tells agents to store credentials at `.context/memory/secrets/github-pat` per `ai-engineering-protocol.md` Step 1.
- **Workaround / fix:** Created `.context/memory/secrets/github-pat` (line 1 = PAT, lines 2+ = scope/added/rotate notes, chmod 600) and `.context/memory/secrets/zen-api` (same format). Verified both are gitignored via `git check-ignore`. Deleted `/home/z/my-project/.secrets.env` and the `/home/z/my-project/.gitignore` I had created to exclude it. The proper secret files are now in place for any future session on this sandbox (though cloud sandboxes wipe between sessions, so they'll need to be recreated next time — the user will need to paste the PAT in chat again per the protocol).
- **Prevent next time:** When you receive a credential in chat (PAT, API key, etc.), the storage location is `.context/memory/secrets/<slug>` — one file per secret, no extension, line 1 = value, lines 2+ = notes, chmod 600. Read `.context/memory/secrets/README.md` if you need a refresher on the format. Never create a `.env`, `.secrets`, or `.secrets.env` file outside `.context/`. This is documented in `ai-engineering-protocol.md` Step 1 and `.context/memory/secrets/README.md` — both of which I had read but didn't apply because I hadn't loaded the protocol as a binding instruction set (Step 3).
---
## 2026-08-03 — Buffy / openai/gpt-5.6-luna (Session 66)
- **Problem:** The first incremental code-execution reader returned strings, but the caller still decoded them as bytes; the focused tests caught the regression immediately. The first shell integration test also used an overcomplicated subprocess mock and failed to model process polling correctly.
- **Cost:** Two short validation/fix cycles.
- **Cause:** The reader's return contract changed during the bounded-capture refactor, and the test initially mocked implementation details instead of exercising a real command.
- **Workaround / fix:** Kept decoding inside the stream reader, treated collected output as strings, simplified shell coverage to a real short-lived command, and added compile/Ruff/full-suite validation before commit.
- **Prevent next time:** When changing stream ownership, define and test the reader return type before wiring callers; prefer real short-lived subprocess tests for capture behavior and reserve mocks for failure-specific cases.

---
## 2026-08-09 — Buffy / deepseek-v4-flash (Session 67)

- **Problem:** `docs/PERFORMANCE_BOTTLENECK_REPORT.md` and `docs/PERFORMANCE_IMPLEMENTATION_PLAN.md` (2026-05-15) were the first hit when verifying the reviewer's latency claim, and both are stale in three misleading ways: they reference dead file paths (`core/engine.py` — now `core/engine/_pipeline.py`), claim `DISPATCHER_HIGH_CONFIDENCE_SKIP=0.7` (now 0.6), and recommend reducing `MAX_ITERATIONS` 8→5 — which directly contradicts the Session 32 standing contract ("Do NOT lower below 8"). I had to verify the current pipeline code directly instead of trusting the docs, and had to be careful not to carry the docs' superseded recommendation forward.
- **Cost:** ~15 minutes of cross-checking code vs docs; one real risk avoided (I nearly treated "reduce MAX_ITERATIONS to 5" as a live recommendation before catching the Session 32 contract).
- **Cause:** The docs were written 2026-05-15 (pre-Sessions 21-32) and never updated after the trivial-input short-circuit (Session 21), the parallel memory retrieval, the skip-logic changes, and the Session 32 MAX_ITERATIONS contract.
- **Workaround / fix:** Verified the live behavior in `_pipeline.py` / `thinking_dispatcher.py` / `trivial_input.py` directly. Filed B-2026-08-09-7 to rewrite/annotate both docs as historical records.
- **Prevent next time:** When a doc references a `core/engine.py` path or pre-2026-07 constants, check `.context/memory/plans/decisions.md` and recent session entries for superseding contracts before following any recommendation in it. Also found while reviewing: `THINKING_DISPATCH_TIMEOUT_SECS=12.0` (constants.py) vs `DISPATCHER_TIMEOUT_SECS=30.0` (thinking_dispatcher.py) disagree — backlogged as B-2026-08-09-11.

---
## 2026-08-09 — Buffy / deepseek-v4-flash (Session 68)

- **Problem:** When refactoring `trivial_response` to share a helper with the new `conversational_response`, I first wrote the helper as a plain `def` containing `async for` (SyntaxError: 'async for' outside async function) and then as an `async def` that `return`ed the inner async generator instead of iterating it — the latter makes the public functions coroutines, breaking `async for chunk in conversational_response(...)` at runtime.
- **Cost:** One failed test run (collection SyntaxError) + one runtime-shape fix, plus a third edit to correct the `async def` return-vs-iterate mistake. ~5 minutes.
- **Cause:** Two async-generator pitfalls hit in sequence: forgetting `async` on a generator helper, then assuming `return <async generator>` from an `async def` keeps it an async iterator (it doesn't — no `yield` in the body makes it a coroutine function).
- **Workaround / fix:** Made the helper `async def` with `yield` inside, and both public wrappers iterate it (`async for chunk in helper(...): yield chunk`).
- **Prevent next time:** When a public `async def` must be an async iterator, the body must contain `yield` (or explicitly iterate a child generator) — `return <agen>` silently converts it into a coroutine function. Add a quick test that does `[c async for c in fn(...)]` for every new streaming helper.

---

- **Session:** 69 (2026-08-09)
- **Symptom:** `py_compile` failed with `IndentationError: unexpected indent (_pipeline.py, line ~2299)` right after wiring `_StageClock` into the graph-execution branch.
- **Cost:** One failed compile + one corrective `str_replace` + recompile. ~3 minutes.
- **Cause:** The `str_replace` oldString for the graph block was written with 12-space leading indentation while the target block sits inside an `else:` at 16 spaces — the edit applied but de-indented the block, breaking Python's block structure.
- **Workaround / fix:** Re-anchored the replacement on the block's exact surrounding lines (`self._metrics.start_request()` … `executed_graph = await execute_graph(`) preserving 16-space indent; verified with `py_compile`.
- **Prevent next time:** Before inserting lines into an `if/else` block, copy the exact indentation of the anchor lines (16 spaces inside `else:`, not the 12 of the parent) and always run `py_compile` on the edited module immediately after a multi-line edit — a 1-second check that catches structural breaks before tests.

---
## 2026-08-09 — Buffy / deepseek-v4-flash (Session 70)

- **Problem:** (1) Two `spawn_agents` calls for `code-searcher` failed with "Invalid params: expected array" — the `searchQueries` array was omitted from params, so each failure cost a wasted round-trip. (2) The B-8 `toolsUsed` staleness fix in `useLocalMind.ts` took real verification effort to confirm it is defensive-only: SSE `turn_complete` obs events never carry `tools_used` (only `_store_observation` does), so the streaming panel's tools are driven by `tool_call` events + the send()-time reset; the `!== undefined` fix is correct semantics but changes nothing observable today.
- **Cost:** 2 failed spawns (~1 min) + ~5 min verifying backend obs-event key semantics across 5 `turn_complete` emit sites.
- **Cause:** (1) Tool schema slipped while batching parallel spawns. (2) The B-8 backlog line pointed at `useLocalMind.ts` ~L605 without noting that the SSE obs payload omits `tools_used`, so the "stale tools" symptom is not reachable via the streaming path.
- **Workaround / fix:** (1) Re-issued spawns with explicit `searchQueries`. (2) Kept the frontend fix (harmless, future-proof) and recorded the backend reality here + in sessions.md.
- **Prevent next time:** Always include `params.searchQueries` when spawning code-searcher. Before implementing a frontend fix that reads an obs-event field, grep the backend `_obs.emit(...)` call sites for that exact kwarg — if it only appears in `_store_observation`, the streaming path never sees it.

---
## 2026-08-09 — Buffy / deepseek-v4-flash (Session 71)

- **Problem:** The trivial/conversational short-circuit cleanup blocks called `self._store.add_message(session_id, "user", message)` — but `SessionStore` has NO `add_message` method. The call raised `AttributeError` inside the best-effort try, so `trivial_short_circuit_done` never actually emitted and the user message was never persisted on short-circuit turns. Pre-existing silent failure (the try swallowed it since the trivial path was introduced).
- **Cost:** One failed test run (new turn_complete assertions got 0 events) + a debug script to pinpoint the exception (~10 min).
- **Cause:** The trivial path used a nonexistent `SessionStore.add_message` API instead of the persistence mixin's `_persist_user_message(session_id, message)` used by every other completion path.
- **Workaround / fix:** Switched both short-circuit paths to `self._persist_user_message`. Also restructured so `turn_complete`/`_store_observation` run in their OWN best-effort try — observability must never depend on persistence succeeding.
- **Prevent next time:** When adding a test that asserts an obs event fires, first confirm nothing earlier in the same try block can raise — a swallowed exception in a best-effort try silently skips every following emit. Grep for the correct persistence API (`_persist_*` mixin) rather than assuming `SessionStore` has a method with a guessed name.

---
## 2026-08-09 — Buffy / deepseek-v4-flash (Session 72)

- **Problem:** One `str_replace` in `client.test.ts` used an oldString that was a PREFIX of an existing test's body (3 lines of a larger assertion) instead of a unique whole-block anchor. The replacement inserted a copy of that block's ending + the new describe block, and the original continuation was left orphaned — the file temporarily had a duplicated `observation` matcher and a stray dangling block.
- **Cost:** One inspection + one corrective `str_replace` + re-run (~3 min).
- **Cause:** The oldString matched the first 3 lines of the last test's `toMatchObject` call — not unique/self-contained — so the edit duplicated instead of replacing cleanly.
- **Workaround / fix:** Re-read the file, identified the orphaned duplicate at EOF, and removed exactly that block with a targeted replacement.
- **Prevent next time:** When appending a new describe/test block to an existing test file, anchor the insertion on a UNIQUE, self-contained boundary (e.g. the final `});` of the file, or a complete statement) — never on a partial line sequence that could be a prefix of larger content. After any multi-line edit to a test file, run the test suite immediately (a SyntaxError or duplicate-assertion failure surfaces within seconds).

---
## 2026-08-12 — Buffy / deepseek-v4-flash (Session 152)
- **Problem:** Four `code-searcher` spawns failed with `ENOTDIR: not a directory, posix_spawn '/Users/bao/.config/manicode/rg'` when the `cwd` param pointed at a FILE (`loop.py`) instead of a directory.
- **Cost:** ~1 min (one wasted round-trip).
- **Cause:** `searchQueries[].cwd` must be a directory; passing a file path made ripgrep's spawn target resolve through the config shim and fail.
- **Workaround / fix:** Re-issued with `cwd` omitted and file-targeted searches scoped via `-g 'loop.py'` / `-g '_pipeline.py'` glob flags.
- **Prevent next time:** Never pass a file path as `cwd` — scope single-file searches with `-g '<filename>'` flags.

---
## 2026-08-12 — Buffy / deepseek-v4-flash (Session 153)
- **Problem:** Restarting the dev backend to reload code left the app DOWN for several minutes. Two `nohup ... &` restarts from agent shells died the moment the spawn session ended, and two `launchctl submit` retries failed with server.py's `[startup] Port ... already in use` exit-42 even though nothing was LISTENing.
- **Cost:** ~6 min of restart churn + probes.
- **Cause:** (1) Processes backgrounded from an agent shell are killed when the harness reaps the shell's process group — `nohup` only guards SIGHUP, not a group kill; (2) `backend/server.py:is_port_in_use()` binds WITHOUT `SO_REUSEADDR`, so a graceful shutdown's lingering TIME_WAIT sockets (~15s on macOS) make the pre-check fail with exit 42; (3) server.py's graceful shutdown takes ~4s, so a kill+immediate-relaunch hits the race.
- **Workaround / fix:** Relaunch via `launchctl submit -l com.localmind.backend -- <venv-python> /abs/path/backend/server.py` (a launchd job survives agent sessions), AFTER waiting for `lsof -i :8000` to show ZERO sockets. Electron's normal flow also restores the backend (main.js spawns server.py when its health check fails).
- **Prevent next time:** To reload backend code on this machine: (1) `launchctl remove com.localmind.backend`, (2) poll until `lsof -i :8000` is empty, (3) `launchctl submit -l com.localmind.backend ...`, (4) poll /api/health. Never rely on nohup'd processes from an agent shell for anything that must outlive the session.

---

## 2026-08-13 — Super Z / GLM-5.2 (Session 176)

- **Problem:** `uv sync` in `backend/` fails because `pyproject.toml`
  specifies `readme = "../README.md"` and hatchling refuses paths outside
  the project directory ("Readme path must be within the project
  directory").
- **Cost:** ~3 min of trial-and-error + reading the uv error.
- **Cause:** Hatchling's build backend enforces project-directory
  containment; the LocalMind backend `pyproject.toml` is a sub-package of
  the root repo and points at `../README.md`. uv's `sync` invokes the
  build backend to compute metadata, hitting the refusal.
- **Workaround / fix:** Don't use `uv sync`. Use the verified pattern:
  `uv venv backend/.venv --python 3.12` then `uv pip install --python
  backend/.venv/bin/python -e 'backend[dev]'` with a temporarily-patched
  `pyproject.toml` (sed the readme path to a local copy, install, restore
  the original). One-liner documented in
  `system/environments.md` Session 176 entry. The pre-existing venv at
  `backend/.venv` already has all deps installed from prior sessions, so
  fresh-install is rarely needed in practice.
- **Prevent next time:** Read `system/environments.md` BEFORE attempting
  `uv sync` — Session 52 already recorded the working pattern. Don't
  rediscover.

---

## 2026-08-13 — Super Z / GLM-5.2 (Session 184)

- **Problem:** The Bash tool times out when running long Python scripts (>2 min). The smoke test script (8 prompts × ~30-60s each = 4-8 min) exceeded the 2-minute default timeout and the 10-minute max timeout. The tool returned "context deadline exceeded" repeatedly.
- **Cost:** ~3 failed attempts before identifying the fix: split the smoke into per-prompt scripts that each complete within the 2-minute default timeout.
- **Cause:** Each Bash tool call has a max timeout of 600000ms (10 min). Long-running scripts that boot backend + frontend + run 8 prompts + capture screenshots exceed this. The bash tool itself also seems to have a shorter internal timeout (~90s observed) that kills the call even when the timeout parameter is set higher.
- **Workaround / fix:** 
  1. Boot backend + frontend ONCE via `setsid`-detached `subprocess.Popen(start_new_session=True)` — they survive across bash calls.
  2. Run each prompt in a SEPARATE bash call (each takes ~30-60s, well within the timeout).
  3. Use a separate script to generate the summary from the saved transcripts.
  The scripts are at `/home/z/my-project/scripts/smoke_boot.py` (boot/shutdown/run-by-index) and `/home/z/my-project/scripts/smoke_summary.py` (parse + summarize).
- **Prevent next time:** When a Python script takes >2 min to run, split it into: (a) a detached boot step, (b) per-item execution steps, (c) a summary step. Never run a monolithic 5+ minute script through the Bash tool — it will time out. Use `start_new_session=True` (not `preexec_fn=os.setsid` — they conflict and cause "Exception in preexec_fn").

---

## 2026-08-13 — Super Z / GLM-5.2 (Session 184, second inefficiency)

- **Problem:** Port 8000 stays in TIME_WAIT after backend shutdown (~15s on this Linux sandbox), causing the next boot to fail with "Port 127.0.0.1:8000 is already in use" even though no process is LISTENing.
- **Cost:** ~3 min of restart churn across multiple boot attempts.
- **Cause:** Same as Session 153's documented issue (macOS launchctl pattern). On Linux, the fix is `fuser -k -9 8000/tcp` + wait 5s for TIME_WAIT to clear, THEN re-launch.
- **Workaround / fix:** Before booting the backend: `fuser -k -9 8000/tcp 2>/dev/null; sleep 5`. The `smoke_boot.py shutdown` command handles this automatically via `os.killpg(SIGTERM)`.
- **Prevent next time:** Add a `wait_for_port_clear(port, timeout=15)` helper to the smoke script that polls `ss -tlnp | grep :{port}` until empty before attempting to boot.

- 2026-08-13 (Session 185, post-merge): ADR-19 level-aware memory retrieval keys off the dispatcher plan task_type, but ADR-22 demoted the dispatcher to a hint because free-tier misclassifies (3/8 prompts in the 184 smoke). A misclassified task retrieves the wrong memory levels. Fix direction: re-key the level-aware re-retrieval on the task_type the agent settles on during planning. Also: session numbers 176-179 are now ambiguous (two parallel branches used them) - cite commit SHAs when referencing sessions.

- 2026-08-13 (Session 186): RESOLVED the ADR-19 x ADR-22 composition finding above. Level-aware memory retrieval + decision-ledger recall + decision sink + summarizer policy now key off `_settled_task_type = resolve_task_type(hint, intent)` — the task type the agent settles on during planning (intent is the settled routing for AGENT turns). Explicit canonical hints still win except a 'chat' hint on a non-CHAT routing (definitionally a misclassification). Full backend 1635 green.

---
## 2026-08-14 — Buffy / openai/gpt-5.6-luna (Session 197)

- **Problem:** The first `python --version` probe failed because this macOS
  shell has no `python` alias; an initial compound probe stopped before the
  remaining runtime output was shown. Two `code_search` calls also failed when
  a compound/file `cwd` was supplied, and one later call hit the vendored-rg
  executable path error.
- **Cost:** Minor diagnostic delay; no product impact.
- **Cause:** macOS PATH and project search-tool invocation constraints.
- **Workaround / fix:** Used `python3` for discovery, the project
  `backend/.venv/bin/python` for all checks, and single-directory `code_search`
  calls for source navigation.
- **Prevent next time:** Start runtime probes with the recorded venv path and
  keep each code search scoped to one directory.

---
## 2026-08-14 — Buffy / openai/gpt-5.6-luna (Session 198)

- **Problem:** The focused freshness test command returned non-zero several times while the new test fixture and import ordering were being adjusted; the historical progress output did not retain the failure details.
- **Cost:** A few short reruns and inspections before the final focused suite passed.
- **Cause:** Incremental test edits were validated before the fixture had reached its final contract.
- **Workaround / fix:** Re-read the current test and implementation, reran the focused suite from the final working tree, then ran the full CI gate.
- **Prevent next time:** Capture the full focused-test output on the first failure instead of relying on a progress summary, and rerun the focused suite after the final edit before starting the full gate.

---
## 2026-08-14 — Buffy / openai/gpt-5.6-luna (Session 199)

- **Problem:** The initial delegation trace had to distinguish the internal
  parent `ToolResult` path from the separate observability/SSE path; treating
  all child output as one channel would have either leaked raw results or
  hidden useful progress.
- **Cost:** One clarification turn and a targeted boundary review.
- **Workaround / fix:** Kept complete child events in the child collector,
  forwarded only progress metadata through `ChildObsProxy`, and added a second
  SSE presentation filter for child-tagged/delegation events.
- **Prevent next time:** When debugging agent interception, trace internal
  tool messages and user-facing observability events separately before changing
  the parent loop.

---
## 2026-08-14 — Buffy / openai/gpt-5.6-luna (Session 200)

- **Problem:** Several scoped `code_search` calls failed because the vendored
  ripgrep executable path was unavailable, and combined reads of large context
  files were truncated.
- **Cost:** Minor navigation delay during the legacy-path trace.
- **Cause:** The local Codebuff search wrapper's configured rg path was stale;
  the repository's session logs and pipeline files are large.
- **Workaround / fix:** Used one-directory searches where available, direct
  bounded file windows, and read-only shell inspection (`grep`, `tail`, `sed`)
  for large memory files. No product behavior depended on the failed searches.
- **Prevent next time:** Start with bounded file windows and fall back quickly
  to direct read-only shell inspection when the search wrapper reports a missing
  vendored rg binary.

---
## 2026-08-14 — Buffy / openai/gpt-5.6-luna (Session 201)

- **Problem:** The first replacement slice temporarily treated the reference
  name “Buffy” as a LocalMind product agent, then had to be reverted after the
  user clarified that Buffy/Codebuff/Freebuff were research references only.
- **Cost:** A mistaken uncommitted implementation slice and several inspections;
  no incorrect product code was retained.
- **Cause:** The reference research used “Buffy” as the orchestrator identity,
  and the implementation note was read as a naming requirement instead of an
  architectural behavior reference.
- **Workaround / fix:** Removed the accidental `agents/buffy/` tree completely,
  reread ADR-8 and the LocalMind feature records, and implemented the runtime
  under the neutral LocalMind-native `ParentAgent` name.
- **Prevent next time:** Treat names in prior-art research as examples unless
  the repository ADR explicitly requires them; confirm product identity from
  the active architecture records before creating new modules.

---
## 2026-08-14 — Buffy / openai/gpt-5.6-luna (Session 203)

- **Problem:** The first product commit command failed because shell heredoc
  quoting interacted poorly with an apostrophe in the commit body.
- **Cost:** One retry; no repository changes were lost.
- **Cause:** Embedded shell quoting in a generated commit command.
- **Workaround / fix:** Removed the apostrophe from the message and reran the
  commit command successfully.
- **Prevent next time:** Keep heredoc commit messages free of shell-sensitive
  punctuation or use a quoted message without nested apostrophes.

---
## 2026-08-14 — Buffy / openai/gpt-5.6-luna (Session 204)

- **Problem:** The current-time regression needed to be fixed in a large
  parent-loop module with multiple single-/multi-tool seams, and the first
  focused test assertion used `August 1` as a substring that also matched the
  valid `August 14` result.
- **Cost:** One focused test failure and one small test correction; no product
  behavior was lost.
- **Cause:** The assertion checked a non-boundaried date prefix.
- **Workaround / fix:** Changed the assertion to reject the complete invalid
  date `August 1, 2026`; then reran focused, full, and CI validation.
- **Prevent next time:** Use complete date tokens or regex boundaries when
  asserting that one calendar date is absent from another date's text.

---
## 2026-08-14 — Buffy / openai/gpt-5.6-luna (Session 205)

- **Problem:** The first live-SSE implementation added a shielded pending task,
  but tool observations still remained queued until the next engine chunk.
- **Cost:** One implementation pass and an additional selective-drain helper
  were needed before the transport actually exposed tool results during a slow
  operation.
- **Cause:** Connection keepalive and user-visible progress were treated as the
  same concern; a comment heartbeat does not flush application observations.
- **Workaround / fix:** Added `ObsCollector.drain_matching()` and a heartbeat
  bridge for tool/terminal events, leaving unrelated observations queued.
- **Prevent next time:** When adding streaming heartbeats, test event ordering
  while the producer is deliberately pending; an HTTP keepalive-only test is
  insufficient.

---
## 2026-08-14 — Buffy / openai/gpt-5.6-luna (Session 206)

- **Problem:** Restoring the trivial-input runtime call initially caused a
  circular import during test collection.
- **Cost:** One failed focused test invocation and a small import adjustment.
- **Cause:** `trivial_input` imports `core.engine._helpers`, while the
  `core.engine` package initializer imports `AgentRuntime`.
- **Workaround / fix:** Loaded the trivial/conversational helpers lazily inside
  `AgentRuntime._process_unlocked()` at the boundary where they are needed.
- **Prevent next time:** Treat helpers imported by `core.engine` submodules as
  lazy-import candidates when wiring them into the runtime module.

---
## 2026-08-14 — Buffy / openai/gpt-5.6-luna (Session 207)

- **Problem:** The first workflow-progress test fixture used a shortened
  `STEPS:` format that LocalMind's parser intentionally rejects, so the test
  could not observe the parsed plan summary.
- **Cost:** One focused test failure and one fixture correction.
- **Cause:** The fixture omitted the planner contract's `UNDERSTANDING`/
  `ARGS_PRECHECK` framing and used filler step labels that the parser filters.
- **Workaround / fix:** Made the fixture match the real structured planner
  format and use concrete tool-bearing steps; the focused workflow tests then
  passed.
- **Prevent next time:** Reuse the actual planner output contract when testing
  plan parsing, including concrete step wording that survives filler filtering.

---
## 2026-08-14 — Buffy / openai/gpt-5.6-luna (Session 208)

- **Problem:** The first frontend validation command ran from the repository root,
  where no `package.json` or root `tsconfig.json` exists; both npm test and
  TypeScript failed before running project checks.
- **Cost:** One parallel validation pass and a short rerun.
- **Cause:** The frontend package is under `frontend/`, while backend commands use
  the repository root with the project-local backend venv.
- **Workaround / fix:** Read `frontend/package.json` and reran `npm test -- --run`
  plus `npx tsc -b && npm run lint && npm run build` with `cwd=frontend`; all
  passed.
- **Prevent next time:** Use the recorded package boundary: backend checks from
  the repo root with `backend/.venv/bin/python`; frontend npm checks from
  `frontend/`.

---
## 2026-08-14 — Buffy / openai/gpt-5.6-luna (Session 209)

- **Problem:** The user-facing transcript still felt like `prompt → tool →
  answer`, despite existing plan/status/tool UI. The live web-search path ended
  the parent turn before the parent could decide what to do with search evidence.
- **Cost:** One architecture trace and one focused regression slice; no frontend
  rewrite was needed.
- **Cause:** Three duplicated web-search branches in AgentLoop called the legacy
  synthesis helper and returned terminal chunks directly. The normal tool-message
  continuation path was bypassed only for web search.
- **Workaround / fix:** Removed the terminal shortcut from native, MiniMax/text,
  and late-intercepted calls. Search results now follow the ordinary tool-message
  path and the parent makes the next decision. Added a second-decision regression.
- **Prevent next time:** When adding a special tool handler, test that successful
  output re-enters the parent loop and that only a verified parent response emits
  `done`; never infer completion from tool success alone.

---
## 2026-08-14 — Claude Code / claude-opus-4-8 (Session 210)

- **Problem:** Wanted a visual screenshot of the redesigned Actions
  timeline. Built a throwaway vite dev harness (`harness.html` + a small
  `src/harness.tsx` mounting the real component with mock `ToolCall`
  data). The harness threw React "Invalid hook call / Cannot read
  properties of null (reading 'useState')" — a dev-server dual-React
  resolution quirk for an extra entry point that pulls in framer-motion
  hooks — and separately the in-app browser pane wouldn't composite
  frames ("pane is not displayed"), so no screenshot was possible.
- **Cost:** ~15 min on the harness + browser round-trips, abandoned.
- **Cause:** (1) The in-app Browser blocks `navigate` to `localhost`;
  `preview_start {url}` opens it but the pane stayed hidden this session.
  (2) A second vite entry that imports framer-motion can resolve a
  duplicate React in dev optimize-deps, breaking hooks — the app's own
  build/tests are fine (production `vite build` + jsdom vitest pass).
- **Workaround / fix:** Dropped the harness; verified with a durable
  `ToolSteps.test.tsx` (9 jsdom render cases) + `vite build`. This is
  better anyway — permanent coverage instead of a throwaway screenshot.
- **Prevent next time:** For a pure component visual check, prefer a
  jsdom render test over a live harness. If a real screenshot is needed,
  drive the actual app (single React graph) rather than a bespoke second
  vite entry, and confirm the browser pane is displayed before relying on
  `computer{screenshot}`. Live-app visual verification still needs a
  provider credential to produce a real streaming turn.

---
## 2026-08-14 — Buffy / openai/gpt-5.6-luna (Session 220)

- **Problem:** The Claude Code handoff ended during closeout while the full
  suite was still running, leaving ADR-32's loop-level remainder and memory
  records unfinished.
- **Cost:** No product rework was needed beyond the handoff's in-progress
  changes; one closeout pass was required to reconcile the adapter and loop
  stages and record the completed suite.
- **Cause:** The session exhausted its token budget after product validation
  but before the separate review/backlog/session-memory closeout.
- **Workaround / fix:** Resumed from the committed handoff, completed the
  loop/runtime fail-fast propagation, waited for the full suite result, then
  recorded the review, feature manifest, backlog closure, and append-only logs
  as separate context work.
- **Prevent next time:** Treat closeout as a required phase with its own
  bounded checklist; do not mark an ADR complete until the full suite result,
  review, backlog, feature memory, session log, and clean-tree verification are
  all recorded.

---
## 2026-08-14 — Buffy / openai/gpt-5.6-luna (Session 221)

- **Problem:** The screenshot mixed two symptoms—an addressed greeting taking
  a provider round-trip and provider errors appearing after a wait—so the
  first diagnosis needed a source trace rather than assuming the parent loop
  was broken.
- **Cost:** One focused trace across `AgentRuntime`, `trivial_input`,
  `AgentLoop`, the adapter, and the SSE boundary; no broad rework.
- **Cause:** `Hey LM` was not covered by the whole-message greeting regex.
  The provider-error cards were a separate real-call failure path, already
  covered by ADR-32's terminal propagation tests.
- **Workaround / fix:** Added addressed-greeting matching and runtime tests
  for zero adapter acquisition/parent entry; documented the distinction
  between direct-chat provider latency and parent-loop execution.
- **Prevent next time:** Classify the transcript by execution mode first—
  deterministic social, direct conversational, or substantive parent—then
  inspect provider error timing within that mode instead of treating every
  assistant turn as one loop shape.

---
## 2026-08-14 — Buffy / openai/gpt-5.6-luna (Session 222)

- **Problem:** Session 221 fixed one addressed greeting with another prompt-shaped
  exception, but that left the architectural complaint unresolved: the model was
  still not the owner of the initial meaning/response decision.
- **Cost:** One additional architecture trace and a deliberate rewrite of the
  previous session's runtime-routing tests; no live-provider test was possible.
- **Cause:** The request runtime had accumulated two execution shapes—deterministic
  direct helpers and the parent loop—rather than one parent initialization contract.
  The existing free-form planner was not typed and could not choose direct,
  clarify, or execute.
- **Workaround / fix:** Added a bounded model-owned initialization decision, removed
  the live direct runtime branch, reused execute decisions as the parent plan, and
  surfaced an authoritative `agent_initialize` stage. Compatibility regex helpers
  remain but are no longer routing owners.
- **Prevent next time:** When a user calls out an architectural failure, do not add a
  new prompt exception to the old boundary. Trace the owner of the decision, move
  that decision into the correct runtime primitive, and add a regression proving the
  old branch is not live.

---
## 2026-08-14 — Buffy / openai/gpt-5.6-luna (Session 223)

- **Problem:** After ADR-33, it was tempting to declare the agent UX solved
  because every turn now reaches a model-owned initializer. The user correctly
  identified that the visible experience still starts with context work, splits
  tool output across chat/Actions/Observe, and leaves the Agents workspace passive.
- **Cause:** The runtime ownership fix and the presentation/transport contract
  were treated as separate concerns, but the user experiences them as one loop.
  Initialization is model-owned in code yet not first in the observable timeline;
  evidence is parent-owned in code yet not clearly separated from final chat
  content.
- **Prevent next time:** For agentic UX work, audit event ordering and rendering
  ownership together. A typed decision is insufficient unless its public lifecycle
  events, evidence boundary, active workspace, and final synthesis channel are
  all explicit and tested end-to-end.

---
## 2026-08-15 — Claude Code / claude-opus-4-8 (Session 231)

- **Problem:** Spent Session 230 wrongly concluding the spaceless output was the weak model's raw JSON, when it was our own bug: an edge-trimming normalizer (`_strip_minimax_tool_calls`, ends with `.strip()`) applied per streamed delta ate the spaces between fragments.
- **Cost:** One session's misdiagnosis (blamed the model, backlogged as "needs real-model repro") before the user pushed back with the exact spaceless output.
- **Cause:** Reasoned "the answer streams verbatim (loop.py:1482), so it's the model" — verbatim, but of an ALREADY per-delta-trimmed buffer. Didn't trace the chunk accumulation upstream of the emit.
- **Workaround / fix:** Whitespace-safe `_strip_minimax_tool_calls_stream` (no trailing strip) for per-chunk use.
- **Prevent next time:** Never apply an edge-trimming text normalizer to individual streamed deltas — trim only complete texts. When output is spaceless/garbled, trace the FULL accumulation path (adapter delta → per-chunk filters → join), not just the final emit.

---
## 2026-08-15 — Buffy / deepseek-v4-flash (Session 234)

- **Problem:** A backend regression test (`test_synthesis_uses_current_result_without_stale_competitor`) silently rotted overnight: it hardcoded Aug 14, 2026 as the fixture's "current" block, so once `date.today()` became Aug 15 every block was stale, synthesis correctly refused to answer, and the test IndexError'd on an empty message list. It passed for exactly one calendar day.
- **Cost:** Full-suite run flagged it; a few minutes of diagnosis to confirm it was date-rot and not a synthesis regression. Real cost: any future agent seeing this failure could have shipped a pointless "fix" to the synthesizer.
- **Cause:** Freshness logic computes `today = today or date.today()` internally, but the test fixture used a literal date instead of deriving it from `date.today()`.
- **Workaround / fix:** Fixture dates now relative to today (today + today−6d) via a `_block_date()` helper; assertions reference the same computed strings.
- **Prevent next time:** Any test whose assertions depend on a calendar date (freshness, "today", aging, TTL) must build fixtures from `date.today()`, never a literal. Also: when a session adds custom window chrome, gate it on the platform that is actually frameless — the previous gate (`window.electronAPI` exists) duplicated native controls on macOS and Windows.

---
## 2026-08-15 — Claude Code / claude-opus-4-8 (Session 237)

- **Problem:** Could not diagnose/fix the Thinker's real behavior — the zen free tier is exhausted (persistent 429 `FreeUsageLimitError`), so every `/api/chat` request fails immediately. This is THE recurring meta-blocker for Thinker development: ADR-36 mandates live-model validation, but the only configured provider (zen free) is both slow AND rate-limit-exhausted, and has blocked live validation across many sessions.
- **Cost:** A session that could only diagnose the blocker, not do the requested work.
- **Cause:** Free-tier provider quota exhaustion + no fallback provider configured.
- **Fix / recommendation:** For Thinker (and general) development, configure a MORE GENEROUS, FAST free provider — Cerebras (1M tokens/day free) or Groq — instead of relying on zen's small free quota. This unblocks live validation AND fixes the latency complaints. Then Thinker work can actually be observed and validated live (backend from source + curl `/api/chat`, capturing `understanding`/`understanding_details`/`mode`).
- **Prevent next time:** Before starting a live-validation-dependent session, confirm the provider isn't exhausted (`curl /api/chat` once). If it is, unblock the provider FIRST.

---
## 2026-08-15 — Claude Code / claude-opus-4-8 (Session 237, cont.)

- **Problem:** The free models available cannot support agent-loop development. The capable one (`deepseek-v4-flash-free`) is quota-exhausted (429); the working one (`nemotron-3.5-lightning-free`) is too WEAK to terminate a tool loop — live-traced "list my dev folder": it ran 8+ iterations repeatedly calling `shell ls` / `find_path` on the same folder, gate-replan timing out each round, never producing an answer (90s, garbled "BasedTheBased" output). The earlier CLEAN 10s/2-iteration run was on the capable deepseek model.
- **Cost:** Could implement the synthesis fix but not live-validate it (its empty-answer branch is only reached when the model actually TERMINATES, which nemotron doesn't).
- **Cause:** Free-tier models are either quota-capped (capable) or too weak for tool loops (available). This is THE wall for developing/validating the Thinker + agent loop.
- **Fix / recommendation:** Agent-loop + Thinker development needs a model that can reliably run tool loops. Options: (1) wait for `deepseek-v4-flash-free` quota to reset (it terminated cleanly), or (2) use a capable model (zen paid: claude-sonnet-5 / gemini-3.7-flash). Chat-only tiers (1/2) work on any model; tier-3 (tools) needs real capability.
- **Prevent next time:** Before validating agent-loop changes, confirm the ACTIVE model can complete a simple tool task end-to-end (one clean tier-3 turn), not just answer chat.

---
## 2026-08-15 — Buffy / z-ai-glm-5.2 (Session 238)

- **Problem:** (1) Port 8000 is occupied by the user's running LocalMind instance — every attempt to start my own backend from source failed with "Port already in use" before I checked `lsof`. (2) The `timeout` CLI doesn't exist on macOS — my curl trace command died instantly with `timeout: command not found` and produced a 33-byte empty file. (3) The active provider (gemini-2.5-flash) is set via the APP's Settings, NOT in `backend/.env` (only `ZEN_API_KEY` is there) — I assumed the failing model was zen until the server startup log revealed `adapter: gemini | model: gemini-2.5-flash`. (4) `LOCALMIND_SHELL_ENABLED=false` in `backend/.env` silently disabled the shell tool in my trace (first trace showed "Shell tool is disabled" in the tool output).
- **Cost:** ~10 minutes across the four; the trace harness from Session 237 (backend from source + curl) worked once port + shell-enable were right.
- **Cause:** Local-only environment facts not recorded; `timeout` is GNU coreutils, not macOS; provider keys can live in the app's settings DB rather than `.env`.
- **Workaround / fix:** Traces on `LOCALMIND_PORT=8765` with `LOCALMIND_SHELL_ENABLED=true`; `curl --max-time` instead of `timeout`; read the server startup log for the ACTIVE adapter/model. Recorded all four in `system/environments.md`.
- **Prevent next time:** Before any live trace, check `lsof -i :8000`, read the startup log for the active provider, and verify shell-enable — the environments block now says all of it.

---
## 2026-08-15 — Claude Code / claude-opus-4-8 (Session 237, gemini trace)

- **Finding (live, gemini-2.5-flash — user added a Gemini key):** Chat tiers work well (hi=1s direct clean; "what can you do"=6s direct, good capabilities answer, no persona leak). But **tier-3 tool tasks fail**: "list my dev folder" → `mode=execute` (correct), but the execute tool-planning call returns an EMPTY response in 788ms (0 tools). The loop's `agent_loop_empty_response` path (loop.py:3695) fires → "The model returned an empty response…". The nearby "fabrication warning: produced text without tool calls" (loop.py:3522) is MISLEADING — its condition (`iteration==0 and agent intent and not trace.steps`) fires even when the buffer is empty.
- **Root pattern:** the agent loop's tool-calling is MODEL-FRAGILE. Across three models: `deepseek-v4-flash-free` runs tools & terminates cleanly (but free quota exhausted), `nemotron-3.5-lightning-free` runs tools but never terminates (8+ redundant iterations), `gemini-2.5-flash` returns EMPTY on the first tool-planning call (0 tools). Each fails differently → the tool path lacks per-model robustness. This — not the Thinker code — is why tool tasks "don't work". The Thinker (ADR-38 mid-loop consult on evidence) is blocked because no evidence is ever gathered.
- **Next-agent guidance:** (1) Determine WHY gemini returns empty on the tool call — inspect the raw request the adapter sends gemini (tool schema format / size; gemini's OpenAI-compat tool support) vs. what deepseek receives (which works). Likely a tool-format or tool_choice/force issue for gemini. (2) When a model returns empty OR text-without-tool on an execute iter-0, REPROMPT with a forced tool nudge instead of failing empty (loop.py:3522/3695). (3) Re-test `deepseek-v4-flash-free` quota — it's the one model that runs tools cleanly; if reset, build the Thinker against it. Trace harness: backend from source + `curl /api/chat`, parse `agent_initialization_done`/tool_call/token.

---
## 2026-08-15 — Session 239 (user correction: preserve != delete)

- **Problem:** I kept the legacy intent system ALIVE while working on the rebuild: (1) `thinking_dispatcher.py` + `execution_graph.py` + `workspace/orchestrator.py` + `engine/routing_helpers.py` sat orphaned for 30+ sessions (Session 201 removed their only callers) with ~3,500 lines and 6 test files still maintained; (2) my Step 1 init rewrite kept parsing the legacy fields (facts/ambiguities/tool_names/plan_steps/success_criteria) "for backward compatibility" and kept rendering them in `plan_text()`. The user corrected me twice: "you are focused on returning the old code instead of deleting it" / "you are now talking about new agent code instead of legacy code".
- **Cost:** ~half the session (my first pass kept improving the new loop around the dead system; the deletion sweep itself was fast). Plus 30+ sessions of dead-code maintenance, and the acceptance-gate replan gotcha in one test (init-fed criteria were masking weak answers with the "✓ criteria met" suffix).
- **Cause:** "Backward compat" framing — treating deleted contracts as if they could still arrive, instead of deleting the parse path with the contract; and no sweep step after Session 201's architectural replacement.
- **Workaround / fix:** (A) Deleted the 4 orphaned modules + their models.py contracts + dead constants/helpers + their tests; (B) deleted the init legacy fields end-to-end (decision → parser → plan_text → streaming block → events → gate feed). (C) Added a Lesson to sessions.md: when a system is replaced, the orphaned modules and their tests get deleted in the same arc.
- **Prevent next time:** after any architectural replacement (pipeline → runtime), grep for modules whose only importers are other orphaned modules and delete them in that session; never keep a parse path for a contract you deleted — a model emitting old fields is ignored, not preserved.

---
## 2026-08-15 — Buffy / openai/gpt-5.6-luna (Session 241)

- **Problem:** The full validation run emitted four existing RuntimeWarnings from test mocks and the Electron build emitted nonfatal metadata/code-signing warnings.
- **Cost:** No implementation delay; all validation gates passed.
- **Cause:** Existing async mock shapes and the local macOS environment has no valid Developer ID signing identity.
- **Workaround / fix:** Recorded the warnings, kept the product scope focused, and verified backend tests, changed-file Ruff, frontend build, and diff checks independently.
- **Prevent next time:** Treat these as known validation noise unless a warning changes test behavior or packaging output; live provider testing still requires the user's configured app credentials and quota window.

---
## 2026-08-15 — Claude Code / claude-opus-4-8 (Sessions 244–245 — the user drove the root cause, not me)

- **Problem:** Across this arc the USER, not me, named the disease each time while I defaulted to patching the symptom in front of me. Concretely:
  1. For "25s / 11k tokens", I shipped a single-prompt routing fix ("what can you do" → direct) and presented it as the fix. The user pushed back: *"you fixed 1 prompt 25s→2s — that is not the real fix; if you had fixed the real agent loop it would be the real win... Claude Code runs 3 min with many tools in few tokens yet our 'hi' consumes 11k."* Only then did I find the actual disease (uncached fat prefix + the current TIME baked into the cacheable prompt busting caching) → ADR-39.
  2. I had already been told this in Session 237 — *"diagnosing a single prompt means we are curing one prompt, not the disease"* — yet I kept treating spacing/latency/limit reports as isolated one-offs.
  3. I presented changes as fixes before live verification, drawing repeated *"It didn't fix anything!"*. When all providers were walled I let that become an excuse to GUESS (the spacing bug) rather than plainly saying "cannot verify — here is the honest state."
  4. I misread *"Do only context"* as my personal `~/.claude` memory and started writing there; the user corrected *"i meant .context"*.
- **Cost:** A very long, multi-pass session. Work that a single root-cause pass could have covered became several symptom passes with round-trips of correction. The user carried the architectural framing (the Claude-Code caching comparison; "cure the disease") that I should have produced myself. Wasted effort circling the spacing bug against walled providers, and one misdirected memory write I had to revert.
- **Cause:** I optimize for "fix the reported input" over "find the system-level cause", and I narrate plausible changes as done before I have evidence. I also treated provider walls as a reason to speculate instead of a reason to stop and state uncertainty.
- **Workaround / fix:** When a report arrives, decide FIRST "is this an input problem or a loop/system problem?" and measure the shared cost before writing code (I did eventually — the per-call token composition + the time-in-prefix finding are what unlocked ADR-39). Never present an unverified change as a fix; if providers are walled, say so.
- **Prevent next time:** Lead with a measured root-cause hypothesis, not a patch. Treat a SECOND "that's not the real fix" as proof I'm still at the symptom layer and must step up a level. Verify live or label the claim unverified — no exceptions. Recorded the standing preference in `user/preferences.md` → "Fixing approach & verification" (cure the disease; verify before claiming).

---
## 2026-08-16 — Buffy / deepseek/deepseek-v4-pro (Session 246)

- **Problem:** `ActionHistory` crashed (`toFixed` of null) because the frontend `ToolCall.duration` type is `number | undefined` but the backend can emit `duration: null`, which survives JSON round-tripping where `undefined` does not.
- **Cost:** One UI crash surfaced as a user-pasted trace; small, but the type lied.
- **Cause:** Optional-number guard used `!== undefined` instead of `!= null`, so the JSON-serialized `null` slipped through to `.toFixed(1)`.
- **Workaround / fix:** Guard changed to `!= null`. General rule: backend-emitted optional numbers reach the client as `null` (not `undefined`), so frontend checks must handle both.
- **Prevent next time:** When the type is `T | undefined` but the value crosses a JSON boundary (API/SSE), treat `null` as a live possibility and prefer `!= null` guards, or normalize at the deserialization boundary.

---
## 2026-08-16 — Buffy / deepseek/deepseek-v4-pro (Session 247)

- **Problem:** The "agent welds words together" bug resurfaced in the final-synthesis path. Session 231 had fixed the same per-chunk `.strip()` bug in the init producer + plan stream, but missed `_force_final_answer`, so web-search/tool answers still collapsed into spaceless text.
- **Cost:** A second bug report for the same root cause; one more round-trip.
- **Cause:** The fix was applied call-site-by-call-site rather than sweeping for every per-chunk use of the trimming `_strip_minimax_tool_calls`.
- **Workaround / fix:** Switched `_force_final_answer` to `_strip_minimax_tool_calls_stream` + regression test.
- **Prevent next time:** When fixing a "wrong variant of a helper on streamed deltas" bug, grep for ALL per-chunk call sites of the offending helper in the same session — not just the one path that surfaced the symptom.

---
## 2026-08-16 — Buffy / deepseek/deepseek-v4-flash (Session 248)

- **Problem:** Chat transcripts showed every assistant reply TWICE after closing and reopening a chat. The guaranteed-persist safety net's dedup checked `get_history(session_id, limit=2)` — but `get_history` orders ASC, so `limit=2` returned the OLDEST two messages, never the just-saved reply. Every reply from turn 2 onward was written twice.
- **Cost:** A backend bug that looked like a frontend render issue at first; a chat-history corruption that shipped silently until the user reopened a chat.
- **Cause:** Assumed `get_history(limit=N)` returns the most recent N messages; the helper is ascending. The dedup compared against the wrong window and always failed for multi-turn chats.
- **Workaround / fix:** Added `SessionStore.get_recent_history()` (newest-first) and pointed both `_guarantee_persist_assistant` implementations (agent_runtime.py + `_persistence_mixin.py`) at it; dropped the now-wrong `reversed()`.
- **Prevent next time:** Any "check the latest N" logic must read the helper's ordering — `get_history` is ASC, so `limit=N` is the OLDEST N. Verify ordering semantics before trusting a limit window for recency checks; when in doubt, add a tiny test of the helper's ordering first.

---
## 2026-08-16 — Buffy / deepseek-v4-flash (Session 251)

- **Problem:** The SYNC run_terminal_command reaped the backgrounded trace server as soon as the command returned — `nohup .venv/bin/python server.py &` started fine (health check passed 4s later) but the process died before the next command's curl ran (Connection refused).
- **Cost:** One failed trace attempt + a confusing "server started then vanished" diagnosis.
- **Cause:** The tool kills the command's process group when the SYNC command completes; nohup alone doesn't detach from that group.
- **Workaround / fix:** Run the server, the curl trace(s), and the cleanup in ONE command: `server & PID=$!; sleep 6; curl ...; kill $PID`. Also: `A && B & C` backgrounds the ENTIRE `&&` chain, so `$!` is the chain's PID and a later `rm -rf "$TMPHOME"` in the foreground sees an EMPTY `TMPHOME` (shell vars from the backgrounded subshell don't leak back). That left a temp LOCALMIND_HOME (with a copy of the user's settings.json incl. API keys) on disk — caught, deleted, values never printed/committed.
- **Prevent next time:** For trace servers, always server+curl+kill in one command; when mixing `&` with `&&`, parenthesize the backgrounded part: `( A && B ) &` and clean up temp secret-copies immediately after the kill. Verify no `lm251_home.*` leftovers before ending a session.

---
## 2026-08-16 — Buffy / deepseek-v4-flash (Session 251)

- **Problem:** SSE trace parsing returned zero events twice — the regex `data: (\{.*\})` with `re.S` (GREEDY `.*`) matches from the first `data: {` to the LAST `}` of the whole file, so `json.loads` failed on the giant multi-object match and every event was skipped.
- **Cost:** Two wasted parse passes (~2 min).
- **Cause:** Greedy `.*` with `re.S` crosses newlines to the final `}`; the files are JSON-only SSE (no `event:` lines — the type is inside the JSON), so the whole stream is one line-wise sequence of `data: {...}` objects.
- **Workaround / fix:** Non-greedy `data: (\{.*?\})\s*\n` per event. The events are `data: {"obs_event": {"type": ..., "data": ...}}` — parse each line's JSON and read `.obs_event.type`.
- **Prevent next time:** Grep the raw bytes first (the hi trace at `/tmp` is the reference), and always use a non-greedy per-event regex for SSE.

---
## 2026-08-16 — Buffy / deepseek-v4-flash (Session 252)

- **Problem:** `classify_failure()` (`core/failure_memory.py:52`) returns `tool_failure` whenever ANY tool step has `tool_failed=True` — even when the run then SUCCEEDED (the model rejected a first guess, loaded the right tool, and completed the task). ADR-40 option C makes this more likely: the on-demand round trip means the model may fire a long-tail tool with a guessed arg BEFORE describe_tool, the loop rejects it as degenerate input, and that one rejected step poisons the run's failure memory (`agent_loop_failure: tool_failure` emitted, Remember stage records noise for a successful turn).
- **Cost:** Incorrect failure-memory records for successfully-adapted runs (observed in the Session 252 zai live trace: describe_tool(skill)→skill(python-testing) succeeded end-to-end, yet the loop emitted `tool_failure: skill()`).
- **Cause:** `classify_failure` looks at any-step-failed, not last-step/outcome; pre-existing since the Session 175 failure-memory work, surfaced now by the C round trip.
- **Fix (future session):** only classify `tool_failure` when the failing step is TERMINAL (the run ended on a failed step) or when no successful outcome followed — e.g. skip steps that were followed by a successful step of the same tool, or gate on `not trace.gate_passed` plus last-step-failed. Add a regression test: a run with one rejected first guess + successful retry must NOT emit agent_loop_failure. Filed as review-42's recommended next step.
- **Prevent next time:** when adding a mechanism that can produce a rejected first attempt (on-demand loading, new validators), check whether rejection paths feed classification/health signals.

---
## 2026-08-16 — Claude Code / claude-opus-4-8 (Session 249/253 — blamed the model AGAIN)

- **Problem:** In Session 249 I concluded GLM-4.5-flash's terse/incomplete output was "a model-quality limitation" and shipped that in review-39 + the model registry. It was wrong: our adapter UNCONDITIONALLY disables GLM's thinking (`_add_provider_params`, zai → `thinking:disabled`) for a justification (the ThinkingDispatcher's 10s timeout) DELETED in Session 239. The model is capable (the user proved it in Copilot — full agentic "Analyze codebase"). I had a standing memory note — "use any capable model; a model failing is OUR bug" — and violated it, again (same class as the Session 244/245 entry).
- **Cost:** A wrong conclusion written into three .context surfaces (review-39, ai-models.md, backlog), which Buffy's Session 252 then partly echoed ("free-tier budget"). The user had to hand me the counter-evidence to redirect. Session 253 spent correcting the record + writing the real handover (ADR-41/review-43/B-2026-08-16-3).
- **Cause:** I reached for "the model is weak" instead of first auditing our HARNESS for disabled capabilities / obsolete workarounds. `finish_reason`/`completion_tokens=28` told me *what* the model emitted, not *why* — and I didn't ask why our harness would make a capable model emit that.
- **Prevent next time:** before ever concluding "the model is weak/terse/incapable", grep the adapter + loop for anything that DISABLES or constrains the model (thinking/reasoning flags, max_tokens, stop sequences, per-call timeouts, forced modes) and check each justification is still valid. A capable model producing bad output in our harness is a harness bug until proven otherwise. See `user/preferences.md` "Fixing approach & verification" and the Session 244/245 entry above.

---
## 2026-08-16 — Buffy / deepseek-v4-flash (Session 254 — backgrounded server reaped)

- **Problem:** Same class as the Session 251 entry: launching uvicorn in a backgrounded subshell in ONE tool command works when the curl runs in the SAME command, but launching it in a separate tool call gets the process reaped when the tool shell exits (nohup + disown did NOT help; macOS has no `setsid`). Cost ~4 failed launch attempts this session before I remembered the Session 251 pattern.
- **Cause:** the tool's shell kills its process group on exit; only a server+curl in one command survives long enough.
- **Prevent next time:** for any live server trace, run `(cmd &) && sleep N && curl ...` in ONE command (the Session 251/254 pattern). Never launch a background server in a separate tool call.

---
## 2026-08-16 — Buffy / deepseek-v4-flash (Session 265)

- **Problem:** `git commit -m "$(cat <<'EOF' … EOF)"` heredoc failed with `bash: -c: line 3: unexpected EOF while looking for matching ''` because the commit body contained an apostrophe (`turn's`). Cost one failed command + a rewrite.
- **Cost:** ~1 minute (one failed run, one re-typed commit).
- **Cause:** the heredoc is parsed by the tool's bash wrapper; an unescaped apostrophe in the body ends the single-quoted heredoc delimiter early.
- **Workaround / fix:** keep commit-message bodies apostrophe-free (rewrite "turn's" → "turn"). Works reliably.
- **Prevent next time:** when using `$(cat <<'EOF' ... EOF)` for multi-line commit messages, scan the body for apostrophes first and reword them away.
