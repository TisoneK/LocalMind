# Flaws Log (append-only — flows to the protocol package)

Friction caused by the `.context/` system or the protocol itself. See
`README.md` in this directory for the split between `flaws/` and
`inefficiencies/`.

---
## 2026-07-11 — GitHub Copilot / DeepSeek V4 Flash Free (Session 3)

- **Flaw:** The protocol's Step 3 ("Read `.context/`") doesn't emphasize hard enough that reading `workflows/active.md` is a **binding instruction** to load and execute the referenced protocol — not passive documentation.
- **Symptom:** Agent read `workflows/active.md` in its first tool calls, saw that the protocol lives in `TisoneK/.context`, but then jumped straight to editing `.context/` files without fetching or following the protocol. User had to redirect: "Don't you have the workflow?"
- **Root cause:** The protocol describes the workflow file as something to read, not as an instruction to act on. There's no explicit "after reading the workflow, immediately load the protocol it references before any other tool use" rule. An agent can read the workflow passively (as context) rather than actively (as a command).
- **Suggested fix:** Add to Step 3 (or a new pitfall): "Reading `workflows/active.md` is a binding instruction. After reading it, immediately fetch and load the protocol it references before any other tool use. Don't treat it as documentation — it's the instruction set for this session." Consider adding a dedicated "Load the protocol" sub-step between Step 3 (read `.context/`) and Step 4 (install deps).
- **Status:** open

---
## 2026-07-11 — GitHub Copilot / DeepSeek V4 Flash Free (Session 3)

- **Flaw:** The protocol doesn't tell the agent **where the protocol itself lives** when the agent is working on a project (not on the package repo). An agent on a fresh project clone has the project's `.context/` but not the protocol file — it has to fetch it from `TisoneK/.context` on GitHub, and the workflow file says "from the `TisoneK/.context` package" but doesn't say "fetch it from GitHub using these coordinates."
- **Symptom:** Agent tried multiple wrong local paths to find the protocol: VS Code prompts folder (`C:\Users\tison\AppData\Roaming\Code - Insiders\User\prompts`), workspace globs (`**/*protocol*`, `**/*.instructions.md`, `**/*.prompt.md`). All returned nothing. 4 failed search tool calls before using `github_repo` to fetch the protocol from `TisoneK/.context`.
- **Root cause:** The workflow file references the package by name ("from the `TisoneK/.context` package") but doesn't give explicit fetch instructions. The protocol's Step 1–3 don't say "if you don't have the protocol file locally, fetch it from `github.com/TisoneK/.context`." An agent that hasn't internalized the two-repo model (package vs project) will search locally first.
- **Suggested fix:** Add to `workflows/active.md` template an explicit "Protocol source" field: `github.com/TisoneK/.context/blob/main/ai-engineering-protocol.md` (or the local edition). Add to Step 3: "If the protocol file is not present in the working directory, fetch it from the URL in `workflows/active.md`'s Protocol source field." Consider having the skeleton's `workflows/active.md` pre-fill this.
- **Status:** open

---
## 2026-07-11 — GitHub Copilot / DeepSeek V4 Flash Free (Session 3)

- **Flaw:** The protocol's execution order (Phase 1 before any editing) is stated as a sequence but not enforced as a **rule**. An agent can treat a small task ("initialize `.context/`") as "too small for the protocol" and skip Phase 1 entirely.
- **Symptom:** Agent registered itself in `ai-models.md`, added its environment to `environments.md`, logged its session in `sessions.md`, updated `workflows/active.md`, and set `tasks/current.md` — all before completing Phase 1 (pull, read docs, discovery). The edits were correct but the sequence violated Steps 2–6. Required a backtrack to re-do discovery properly.
- **Root cause:** The protocol says "execute these steps sequentially" but doesn't explicitly say "regardless of task size" or "even for `.context/`-only tasks." An agent reasoning about efficiency might conclude that a trivial task doesn't need the full Phase 1 setup. The protocol needs an explicit "no task is too small for Phase 1" rule.
- **Suggested fix:** Add to the protocol's Autonomous Execution Steps preamble: "These steps run in order for every session, regardless of task size. A one-line `.context/` edit still requires Phase 1 (pull, read `.context/`, read docs, discovery, baseline) before any file is modified. Skipping Phase 1 because the task seems small is the most common protocol violation." Add as a Common Pitfall.
- **Status:** open

---
## 2026-07-11 — GitHub Copilot / DeepSeek V4 Flash Free (Session 3)

- **Flaw:** The protocol doesn't explicitly distinguish **two surfaces** (the project vs `.context/`) in a way that forces the agent to declare which one it's working on. This made it easy for the agent to slip between "I'm editing `.context/`" and "I'm editing the project" without a clear mode switch.
- **Symptom:** Agent mixed `.context/` edits (registering itself, logging its session) with what should have been protocol-governed project work, without distinguishing the two. The `chore(context):` commit prefix exists but wasn't enough to enforce the mental separation — the agent didn't realize it was in "memory mode" vs "project mode."
- **Root cause:** The protocol has one execution flow that covers both surfaces. There's no explicit "I am now working on `.context/`" or "I am now working on the project" declaration step. The two surfaces share the same 19-step flow, which is correct (both need discovery, both need commits), but the agent needs to be aware of which surface each step applies to.
- **Suggested fix:** Add a "Two Surfaces" section to the protocol (early, before Phase 1) that defines: (1) The project — product code, normal commit prefixes, friction → `inefficiencies/`. (2) `.context/` — agent memory, `chore(context):` prefix, friction with the system → `flaws/`. State: "Know which surface you're on at all times. If you're editing a file under `.context/`, you're in memory mode — the rules in this protocol about `.context/` apply. If you're editing anything else, you're in project mode."
- **Status:** open

---
## 2026-07-11 — Super Z / GLM-4.5 (Session 4)

- **Flaw:** `roles/README.md` in the `TisoneK/.context` package referenced "Phase 5 (Steps 15–17)" but the base editions have only 4 phases. Steps 15–17 are in Phase 4 (Report & Context), not a separate Phase 5.
- **Symptom:** An agent trying to map role instructions to edition steps would look for a Phase 5 that doesn't exist, causing confusion about which phase the memory-update steps belong to.
- **Root cause:** The roles/README.md was written with a 5-phase mental model, but the editions were structured into 4 phases. The phase label was added for clarity but introduced a mismatch.
- **Suggested fix:** Change "Phase 5 (Steps 15–17)" → "Phase 4, Steps 15–17" (or drop the phase label entirely and reference steps by number only).
- **Status:** fixed in package — `TisoneK/.context` commit (this session), `roles/README.md` now says "Phase 4, Steps 15–17"

---
## 2026-07-11 — Super Z / GLM-4.5 (Session 4)

- **Flaw:** `localmind-review.md` sat at the package root, making it look like a review of the `.context` package itself rather than an example deliverable from a project session.
- **Symptom:** A new visitor to the `TisoneK/.context` repo (human or agent) might confuse the example review with a review of the protocol package, misreading LocalMind-specific findings as protocol findings.
- **Root cause:** No `examples/` directory existed; the example file was placed at the root for convenience. The README explained it was an example, but the file's location didn't reinforce that.
- **Suggested fix:** Move to `examples/localmind-review.md`. Create the `examples/` directory as the home for sample deliverables.
- **Status:** fixed in package — `TisoneK/.context` commit (this session), moved to `examples/localmind-review.md`, README link updated

---
## 2026-07-11 — Super Z / GLM-4.5 (Session 4)

- **Flaw:** The quickstart doc (`context-workflow-quickstart.md`) existed in the user's local uploads but was never committed to the `TisoneK/.context` package repo. New users/agents had no entry point explaining the two-repo mental model and bootstrap steps.
- **Symptom:** A new user cloning `TisoneK/.context` for the first time sees protocol files, a skeleton, roles, and an example review — but no "how do I actually use this?" guide. They have to read the README and infer the workflow.
- **Root cause:** The quickstart was written as a separate doc but never added to the repo. The README covers usage briefly but doesn't walk through the full two-repo model.
- **Suggested fix:** Commit as `QUICKSTART.md` at the package root. Add to the README contents table.
- **Status:** fixed in package — `TisoneK/.context` commit (this session), added as `QUICKSTART.md`, linked from README

---
## 2026-07-11 — Super Z / GLM-4.5 (Session 4)

- **Flaw:** The cloud edition's `secrets/github-pat` guidance didn't distinguish cloud-sandbox persistence (session-only) from local-agent persistence (survives across sessions). The text said the file "dies with the sandbox" — correct for cloud, misleading for local agents who might read the cloud edition for reference.
- **Symptom:** A local agent reading the cloud edition might wrongly conclude that `.context/secrets/` is always ephemeral, missing that on a local machine the file persists and can be reused across sessions.
- **Root cause:** The guidance was written from the cloud-sandbox perspective only. The two persistence models (cloud ephemeral vs local persistent) weren't called out as a distinction.
- **Suggested fix:** Add explicit cloud-vs-local sub-bullets under the `secrets/github-pat` guidance: cloud = session-only convenience, local = persists across sessions.
- **Status:** fixed in package — `TisoneK/.context` commit (this session), `ai-engineering-protocol.md` Step 1 now has cloud/local sub-bullets

---
## 2026-07-11 — Super Z / GLM-5.2 (Session 5) — UPDATE: flaws 1–4 fixed

Flaws 1–4 (from Session 3, GitHub Copilot) are now **fixed in package** —
commit on `TisoneK/.context` (Session 5) applied all four suggested fixes:

- **Flaw 1 (binding instruction):** Fixed. Step 3 now says "Reading
  `workflows/active.md` is a binding instruction, not passive
  documentation." Added as Pitfall #27 in both editions.
- **Flaw 2 (protocol source):** Fixed. `workflows/active.md` template
  now has a `Protocol source` field with the GitHub URL. LocalMind's
  `workflows/active.md` updated with both edition URLs.
- **Flaw 3 (no-task-too-small):** Fixed. Protocol preamble now says
  "No task is too small for Phase 1." Added as Pitfall #28.
- **Flaw 4 (two surfaces):** Fixed. Both editions now have a "Two
  Surfaces — Know Which One You're On" section before Phase 1.

---
## 2026-07-11 — Super Z / GLM-5.2 (Session 5)

- **Flaw:** Agents are asked to record their model identity in `.context/system/ai-models.md` and `agents/sessions.md`, but the protocol gave them no reliable way to determine it. The system prompt doesn't state the model version, and the protocol's Pre-Flight said "agent fills in — records best self-description." This led the agent to guess "GLM-4.5" in Session 1, which propagated verbatim through Sessions 2–4.
- **Symptom:** All `.context/` entries from Sessions 1–4 record the wrong model (GLM-4.5 instead of GLM-5.2). The user caught it in Session 5 by asking "why did you say 4.5?"
- **Root cause:** The protocol treated model identity as something the agent could self-determine. It can't — system prompts don't reliably state the model version. The user knows (they selected it in the UI); the agent doesn't.
- **Suggested fix:** Move Agent Identity from "agent fills in" to "user fills in — agent copies, never guesses." Add a pitfall: "Never guess your own model version. If it's not in Pre-Flight, ask once. If the user doesn't know, record 'unknown'."
- **Status:** fixed in package — Agent Identity section rewritten in both editions; Pitfall #25 added. LocalMind's `ai-models.md` has a correction entry (append-only — prior entries not rewritten).

---
## 2026-07-11 — Super Z / GLM-5.2 (Session 5)

- **Flaw:** The protocol didn't clearly mark session entry, phase transitions, or exit. Agents didn't know where to start (Copilot jumped to editing before reading the workflow), didn't know how to transition between phases, and didn't know how to end (Copilot had to be reminded to commit and push). This is the root cause behind flaws 1–4 — they're all symptoms of missing lifecycle markers.
- **Symptom:** Copilot (Session 3) didn't know where to start (skipped Phase 1), didn't know how to end (user had to remind it to commit/push). The user explicitly flagged this as "the biggest flaw."
- **Root cause:** The protocol had 19 steps in 4 phases but no explicit "ENTRY" marker (what to do first), no "TRANSITION" markers (when to move between phases), and no "EXIT" checklist (what must be true before the session is done). An agent could finish the work but not realize it hadn't pushed, because there was no checklist saying "push is part of done."
- **Suggested fix:** Add a "Session Lifecycle — Entry, Transitions, Exit" section to both editions, before Phase 1. ENTRY says read Two Surfaces + Pre-Flight first, don't edit until Phase 1 is done. TRANSITIONS list the phase-boundary conditions. EXIT is a mandatory checklist including "all fixes committed AND pushed," "report committed AND pushed," ".context/ updated committed AND pushed," "PAT unset," "chat summary delivered." Add: "If the user has to remind you to commit or push, the protocol failed — log it as a flaw."
- **Status:** fixed in package — both editions now have the Session Lifecycle section with ENTRY/TRANSITIONS/EXIT. Pitfall #26 added.

---
## 2026-07-11 — Super Z / GLM-5.2 (Session 7)

- **Flaw:** `workflows/active.md`'s `Protocol source` field contains a `blob/` URL (`https://github.com/TisoneK/.context/blob/main/ai-engineering-protocol.md`), which is the HTML page on GitHub, not the raw file. The protocol's Step 3 instructs the agent to "fetch it from the URL in the `Protocol source` field" — but fetching a `blob/` URL returns HTML with the markdown embedded inside, not the raw markdown. An agent using `curl` on the `raw/` equivalent (`https://raw.githubusercontent.com/...`) may also 404 (happened this session — possibly a branch/cache issue). The protocol doesn't give a fallback for when the URL fetch fails.
- **Symptom:** Session 7's `curl -sL https://raw.githubusercontent.com/TisoneK/.context/main/ai-engineering-protocol.md` returned 404 (0 bytes). Had to clone the entire `TisoneK/.context` package repo to read the 53KB protocol file. Cost: 1 failed curl + 1 extra `git clone --depth 1` (~2s, 156KB). Minor cost, but the protocol's fetch instruction is unreliable.
- **Root cause:** Two issues: (1) `blob/` vs `raw/` URL — the field was written for human readability (clickable link in the GitHub UI) rather than agent fetchability; (2) no documented fallback when the fetch fails. The protocol assumes the URL works, but GitHub's raw URL can 404 for private repos (if the PAT isn't in the curl headers) or for branch-name mismatches.
- **Suggested fix:** (1) Change the `Protocol source` field in `workflows/active.md` (and the skeleton template) to give BOTH URLs: `blob/` for humans + `raw/` for agents. (2) Add to Step 3: "If the `raw/` URL 404s, clone `TisoneK/.context` with `--depth 1` and read the protocol file locally — this is the reliable fallback." (3) For private package repos, note that the raw URL needs the PAT in an `Authorization: Bearer` header.
- **Status:** open

---
## 2026-07-11 — Super Z / GLM-5.2 (Session 7)

- **Flaw:** The `.context/` append-only rule (`.context/README.md` Rule 1: "Append-only logs are append-only... If a past entry was wrong, append a correction referencing it — don't erase history") has no exception for accidental duplicates. `agents/sessions.md` currently contains the Session 6 entry twice (lines 39-48 and 50-59 — byte-identical). The duplicate carries no information the first entry doesn't, but the append-only rule prevents removing it. An agent following the rule literally must leave the noise.
- **Symptom:** Session 7 discovered the duplicate. Cannot remove it under current rules. The duplicate will persist forever, and future agents will see two identical Session 6 entries and wonder if they're missing context.
- **Root cause:** The append-only rule was designed to prevent agents from rewriting history (deleting embarrassing entries, altering outcomes). But it doesn't distinguish "history" from "duplicate noise" — an accidental double-append (perhaps from a retried tool call, or a commit that was amended + re-appended) is treated the same as a legitimate entry. The rule is correct in spirit but too strict for the duplicate case.
- **Suggested fix:** Add an exception to Rule 1: "Exact duplicates (byte-identical entries with the same session ID and date) may be removed — they carry no information. Document the removal in a one-line correction appended in its place: `Removed duplicate Session N entry (byte-identical to the entry above/below).`" Alternatively, add a `dedupe` operation to the protocol that agents can run on append-only files: scan for byte-identical entries, remove all but the first, append a one-line note listing what was deduped.
- **Status:** open

---
## 2026-07-11 — Super Z / GLM-5.2 (Session 7) — PAT leak in chat summary

- **Flaw:** The protocol says "never write the PAT to any file" and "never echo secret values from `secrets/`," but it never explicitly says "don't include the PAT value in chat output or rotation reminders." An agent following the Exit checklist's "remind the user to rotate the PAT" step can reasonably include the full token value — defeating the secret-handling rules. The PAT lives as an env var, not a `secrets/` file, so the `secrets/README.md` "never echo a value" rule doesn't feel applicable.
- **Symptom:** Session 7's final chat summary included the full PAT in plaintext: "⚠️ Rotate the PAT — `github_pat_11ASCEY4Q0n1QCPOjmffJy_...` was used this session and is now unset." The agent's intent was good (reminding the user to rotate), but including the actual value leaked it into the chat transcript, which may be logged, shared, or screenshotted.
- **Root cause:** The protocol's secret-handling rules are scoped to files and `secrets/` values, not to the PAT env var in chat output. The Exit checklist says "remind the user to rotate the PAT" but doesn't say "reference the token by last 4 characters, never the full value." The agent reasoned: "the user pasted it, so they know it; including it makes the reminder more useful." That reasoning is understandable but wrong — the chat transcript is not a secure channel.
- **Suggested fix:** Add to both protocol editions, in the PAT section: "Never echo the PAT value in chat output. This includes rotation reminders, error messages, and 'for your reference' notes. The user pasted it; they know it. Your reminder should say 'Rotate the PAT' — not 'Rotate the PAT: `github_pat_...`'. If you need to reference which token, use the last 4 characters: 'Rotate the PAT ending in `5KV`.' The full value must never appear in your output, in any form." Add as a pitfall in both editions.
- **Status:** fixed in package — both editions now have the rule + pitfall (this session)

---
## 2026-07-11 — Super Z / GLM-5.2 (Session 8) — UPDATE: Session 7 flaws fixed

Flaws from Session 7 are now **fixed**:

- **blob/ vs raw/ URL (Session 7 flaw 1):** Fixed. `workflows/active.md`
  now has separate "Protocol source (raw)" and "Protocol source (blob)"
  fields, plus a fallback note ("if the raw URL 404s, clone
  `TisoneK/.context` with `--depth 1`"). The skeleton template updated
  too.
- **Append-only dedupe exception (Session 7 flaw 2):** Fixed.
  `.context/README.md` Rule 2 now has an exception: "byte-identical
  entries may be removed — leave a one-line note in its place." Applied
  immediately to the duplicate Session 6 entry in `agents/sessions.md`.
- **PAT leak in chat (Session 7 flaw 3):** Fixed in package. Both
  protocol editions now have the "Never echo the PAT value in chat
  output" rule and Pitfall #29.

---
## 2026-07-11 — Super Z / GLM-5.2 (Session 8)

- **Flaw:** (covered by the PAT-leak flaw above — logged separately for traceability)
- **Status:** fixed in package — both editions updated

---
## 2026-07-11 — Super Z / GLM-5.2 (Session 8) — pull-before-inspect gap

- **Flaw:** The protocol says "pull before starting work" (Step 2), but when a user tells an agent mid-session to "check what another session did" or "pull changes," the agent doesn't have an explicit rule to pull first. The agent may inspect stale local state (via `git show` or `git log`) and report wrong information, only discovering the local is behind when a pull later fails.
- **Symptom:** When told "maybe check what the session did first," the agent jumped straight to `git show` on the latest local commit, assuming local was current. It wasn't until a later `git pull` failed (on file-mode conflicts) that the agent realized remote was ahead. The inspection was performed on stale state.
- **Root cause:** The protocol's pull rule is scoped to session start (Step 2), not to any point where remote may have moved ahead. There's no rule for mid-session sync — "if the user references another agent's work, or if any time has passed since your last pull, fetch first." An agent that pulled at Step 2 and has been working for an hour has no signal that remote may have moved.
- **Suggested fix:** Add to the protocol: "Before inspecting another agent's work (git show, git log on commits you didn't make), or whenever the user references work you haven't seen — fetch first. If remote is ahead, pull before inspecting. Your local state is stale the moment another agent pushes." Add as a pitfall.
- **Status:** fixed in package — both editions updated (this session)

---
## 2026-07-11 — Super Z / GLM-5.2 (Session 8) — rhetorical yes/no questions

- **Flaw:** The Zero-Interruption Principle says "does not ask the user questions between steps," but agents read this as "don't ask for *clarification*" while still asking for *permission* on the default next step. The agent proposes ("Want me to fix this?"), the user says yes, the agent does it — burning a round-trip on something the protocol already prescribes.
- **Symptom:** GLM-5.2 (this session) asked "Want me to proceed with all 5, or just some?" and "Want me to log both and apply the protocol fix?" — three times in a row — despite the user having repeatedly said "fix everything" earlier in the session. This is the same behavior logged as an observation about DeepSeek V4 Flash Free in Session 3. Two models, same pattern → it's a protocol gap, not a model trait.
- **Root cause:** The protocol's Zero-Interruption Principle is stated generally ("does not ask questions") but doesn't explicitly call out the common failure mode: asking for permission on actions the protocol already authorizes. Agents draw a false distinction between "clarification" (which they know not to ask) and "permission" (which they think is polite). Without an explicit rule, agents default to asking.
- **Suggested fix:** Add Pitfall #30: "Don't ask for permission on the default next step. If the proposed action is what the protocol already prescribes (commit after edits, push after commit, log after noticing a pattern, fix a flaw you found), do it and report — don't ask 'Want me to...?' Only ask when there's genuine ambiguity: which of two approaches to take, whether to proceed despite risk, or permission for a broad-scope change the protocol doesn't already authorize."
- **Status:** fixed in package — both editions updated (this session)

---
## 2026-07-15 — Super Z / GLM-5.2 (Session 9) — F-2026-07-15-1: Session 8 never logged

- **Flaw:** Session 8 (commits `586c7ad` "fix 3 Session 7 flaws", `09751b8` "log pull-before-inspect + rhetorical-questions flaws", `55e702a` "add Target field to workflows/active.md" — all dated 2026-07-11) was never given a formal entry in `agents/sessions.md`. The session's work is documented in `flaws/log.md` (the Session 8 entries that fixed Session 7 flaws) but the sessions log itself jumps from Session 7 directly to Session 9 with no Session 8 entry in between. This violates the protocol's Step 15 ("update `.context/` at session end") — the session-end update was incomplete (flaws were logged, but the session entry was never appended).
- **Symptom:** Session 9 (this session) discovered the gap when reading `agents/sessions.md` to determine the next session number. Saw Session 7 as the last entry but the flaws log referenced "Session 8" multiple times. Had to cross-reference commit history (`git log --since=2026-07-11`) to confirm Session 8 actually happened and which commits belonged to it. Cost: ~5 minutes of investigation. Future agents will hit the same gap.
- **Root cause:** The protocol's Exit checklist says "`.context/` updated committed AND pushed" but doesn't explicitly enumerate which `.context/` files must be touched. An agent that updates `flaws/log.md` (which references "Session 8") but skips `agents/sessions.md` (which would have formally created the Session 8 entry) can believe the Exit checklist is satisfied. The two files are decoupled — nothing in the protocol enforces "if you reference Session N in any `.context/` file, you must have an entry for Session N in `agents/sessions.md`."
- **Suggested fix:** Add to the Exit checklist: "If this session is referenced by number in any `.context/` file (flaws, inefficiencies, decisions, reviews), verify that a matching entry exists in `agents/sessions.md`. If not, append one before completing the session." Alternatively, add a CI-style pre-commit hook (or pre-push check) that scans `.context/` for session-number references and validates they all have entries in `agents/sessions.md`. Also consider: the protocol should explicitly list which files must be updated at session end (sessions.md, current.md, ai-models.md if new agent/model, environments.md if new env, review report) — currently the list is implicit.
- **Status:** open

---
## 2026-07-27 — Super Z / GLM-5.2 (Session 31, addendum)

- **Problem:** The protocol doesn't require real-model testing before shipping a fix that includes a diagnostic message. I shipped a fallback message that guessed "free-tier model overload" as the cause of the "Tools execution failure" bug — WITHOUT testing against the real model. The guess was wrong (the real cause was two adapter bugs), and the user had to push back to get me to actually test.
- **Cost:** Two extra commits + one extra round-trip with the user. The first fix treated the symptom; the revision made the fallback more honest but STILL treated the symptom; the actual root cause wasn't found until real-model testing.
- **Cause:** The protocol's Phase 2 (Review) and Phase 3 (Fix) sections don't mention testing against the real failing input. For bugs where the user can provide the failing input (API key, sample request, etc.), the agent should test BEFORE writing the fix — not after.
- **Workaround / fix:** When the user provides credentials for the failing system (API key, etc.), use them to reproduce the bug BEFORE writing the fix. The real-model test took 10 minutes and found the actual bug in 2 API calls.
- **Suggested package fix:** Add to Phase 2 (Review) section: "If the bug report includes a reproducible scenario (API key, sample request, etc.), reproduce it against the real system BEFORE writing the fix. Mocked tests give false confidence for bugs in adapter/integration code." This would have saved two commits and one user round-trip.

---
## 2026-07-27 — Super Z / GLM-5.2 (Session 33)

- **Flaw:** I repeated the Session 31 flaw in Session 32: shipped a fix (iteration limit + safety workflow + hit-limit-aware fallback) WITHOUT real-model testing. The user then reported "we have broken the tools again" — the model called 3 tools (mkdir, git init, file_write) then hung at "Running command" for 36.3s. I had to investigate what broke instead of catching it before shipping.
- **Symptom:** User ran "Create hello world repo" after pulling Session 32's changes. The terminal showed 3 tool calls completing, then the "Running command" spinner stuck. The UI was dead.
- **Root cause (code):** My Session 32 engine fallback code called `_obs.drain()` to check for `agent_loop_done` with `hit_limit=True`. But `drain()` CLEARS the event list — and the SSE bridge at `chat.py:129` ALSO calls `drain()` to forward events to the frontend. My call stole the events (including `tool_status=done`) before the SSE bridge could forward them, so the frontend's spinner never cleared. Fix: use `_obs.all()` (read-only) instead of `_obs.drain()` (destructive).
- **Root cause (process):** I didn't test against the real model before shipping. If I had, I would have seen the hang immediately. This is the EXACT flaw I logged in Session 31's addendum — and then repeated in Session 32. The `.context/` protocol's flaw log exists to prevent this; I'm not reading it before starting work.
- **Cost:** One broken session for the user + one emergency fix session (Session 33). The user's trust in the fix quality is eroded — "we have broken the tools again" is the third time this has happened (Session 31 wrong diagnosis, Session 32 broke the SSE stream, now this).
- **Suggested package fix:** The protocol's Phase 3 (Fix) section needs an explicit "REAL-MODEL SMOKE TEST" step before the commit: "If the fix touches the agent loop, adapter, or engine pipeline, run a real request against the actual model before committing. Mocked tests do not catch SSE-stream races, event-draining bugs, or prompt-injection failures." This is the third time this exact class of bug has shipped (Session 31, Session 32, now). The flaw log pattern is clear — the protocol needs to enforce real-model testing for adapter/engine/loop changes.
- **Status:** open (code fixed in this session; protocol fix still needed)

---
## 2026-07-27 — Super Z / GLM-5.2 (Session 33)

- **Flaw:** I mixed code and `.context/` updates in a single commit (`7fd6841` — "feat: add ZenMux provider" included both the 4 code files AND the 2 `.context/memory/` files). The protocol's Two-Surfaces rule is explicit: editing product code = normal commit prefix (`feat:`); editing `.context/` = `chore(context):`. Never mix both surfaces in one commit. I violated this.
- **Symptom:** User caught it: "Do we really put in one commit???" The commit had `feat:` prefix but included `.context/` files — wrong prefix for those files, and wrong to combine them.
- **Root cause:** I conflated "commit them close together in time" (which is fine) with "commit them together in one commit" (which is not). The protocol wants two surfaces, two commits, even if they're pushed back-to-back. I was optimizing for speed (one commit + one push) instead of protocol compliance (two commits, one push).
- **Workaround / fix:** Soft-reset the mixed commit (`git reset --soft HEAD~1`), unstage the `.context/` files, commit the code as `feat:`, then commit the context as `chore(context):`. Force-pushed with `--force-with-lease` to fix the history. Verified the split: commit `8639db3` has 4 code files only, commit `8756301` has 2 `.context/` files only.
- **Suggested package fix:** Add to the protocol's Exit checklist: "Verify the last commit doesn't mix surfaces. If a single commit contains both product code (backend/, frontend/, tests/) AND `.context/` files, split it: soft-reset, commit code as `feat:`/`fix:`/etc., commit `.context/` as `chore(context):`. The Two-Surfaces rule is in the protocol but easy to violate when rushing — an explicit pre-push check would catch it."
- **Status:** fixed in this session (force-pushed the split). But the pattern — rushing commits and mixing surfaces — is worth logging so the next agent catches it before pushing.

---
## 2026-07-27 — Super Z / GLM-5.2 (Session 34)

- **Flaw:** After completing the ADR-8 initialization session (context-
  only — switched standing Target from ADR-5 to ADR-8, seeded feature-
  scoped memory, committed and pushed), I framed the next session as
  "Suggested next session: Start ADR-8 Phase 1..." — implicitly waiting
  for the user to start it. This violates the Zero-Interruption
  Principle (flaw logged Session 8: "Don't ask for permission on the
  default next step").
- **Symptom:** User responded: "Why did you pause. thats a violation."
  Three short sentences. The user correctly identified that Phase 1
  was the default next step per ADR-8's phase plan + the
  B-2026-07-27-1 backlog item I had just filed. I had the protocol
  authority to continue; I chose to wait instead.
- **Root cause:** I conflated "session complete" (initialization
  committed and pushed, `tasks/current.md` cleared, session logged —
  per protocol Step 15) with "work complete." Initialization was
  complete, but ADR-8 Phase 1 was the next DEFAULT step in the same
  logical work stream. The protocol's Zero-Interruption rule applies
  to the default next step in the work stream, not just within a
  single declared task. I treated my self-imposed session boundary as
  a hard stop.
- **Cost:** One user round-trip ("Why did you pause") + a small
  re-priming cost (re-read the manifest, re-confirm the scope). The
  actual Phase 1 implementation was straightforward — 757 insertions
  / 354 deletions across 15 files, 22 new tests, 434 tests pass, zero
  regressions. The pause cost more than the work.
- **Suggested package fix:** The Session 8 flaw already covers this
  pattern ("Don't ask 'Want me to...?'"). The lesson here is the
  INVERSE: don't even FRAME the default next step as a suggestion.
  Phrasing like "Suggested next session: ..." or "Next session
  should start ..." is the same violation, just softer. If the work
  is the default next step per the ADR plan + a backlog item exists
  + the work doesn't need user input (no design decision, no
  destructive action, no real-model testing that needs credentials),
  the protocol authorizes continuing. Do the work, report at the
  next natural stopping point. Don't manufacture a stopping point
  by framing the next step as a question.
- **Status:** open — the protocol-level lesson (Session 8 + Session 34)
  is now well-documented; the package-level fix would be to strengthen
  the Zero-Interruption wording in both editions to explicitly cover
  "don't frame the default next step as a suggestion either."

---
## 2026-07-27 — Super Z / GLM-5.2 (Session 34 — Phase 1)

- **Flaw:** During Phase 1 implementation, the first version of
  `agents/coding/agent.py` imported `from agents.coding import
  CODING_TOOLS, build_coding_context, is_coding_done`. This created a
  circular import: `agents/__init__.py` → `agents.coding.agent` →
  `agents.coding` (subpackage `__init__.py`, partially-initialized) →
  ImportError. Same pattern in all 4 agent.py files. Caught by
  `python -c "from agents import CodingAgent"` smoke test BEFORE
  running pytest — no test cycles wasted.
- **Symptom:** `ImportError: cannot import name 'CODING_TOOLS' from
  partially initialized module 'agents.coding'`.
- **Root cause:** When the agent class moves INTO the subpackage, the
  subpackage `__init__.py` re-exports the class (`from agents.coding.agent
  import CodingAgent`). If `agent.py` then imports from the subpackage
  (`from agents.coding import ...`), Python sees the partially-
  initialized subpackage (its `__init__.py` hasn't finished running)
  and the import fails. The old layout (when `coding_agent.py` was a
  sibling module OUTSIDE the subpackage) didn't have this problem
  because `coding_agent.py` imported from the subpackage without
  itself being imported BY the subpackage.
- **Workaround / fix:** In each `agent.py`, import from the SUBMODULES
  directly — `from agents.coding.context_builder import
  build_coding_context`, `from agents.coding.is_done import
  is_coding_done`, `from agents.coding.tools import CODING_TOOLS` —
  NOT from the subpackage `__init__`. The subpackage `__init__.py`
  then re-exports both ways safely (it imports `CodingAgent` from
  `agent.py`, which has already imported everything it needs from the
  submodules — no cycle).
- **Prevent next time:** When moving a class INTO a subpackage that
  already has sibling modules, import from the SIBLINGS (not from
  the subpackage `__init__`). The `__init__.py` re-export direction
  is `__init__.py` → `agent.py` → submodules — never `agent.py` →
  `__init__.py` → submodules. Documented in
  `agents/coding/agent.py`'s module docstring implicitly via the
  direct submodule imports.
- **Status:** fixed in this session — circular import eliminated.
  Codified by `tests/agents/test_directory_layout.py::test_agent_directory_has_agent_py`
  and `test_agent_subpackage_re_exports_class` (if the layout breaks
  again, these tests fail at import time, surfacing the issue
  immediately).

---
## 2026-08-01 — Buffy / openai/gpt-5.6-luna (Session 63)

- **Flaw:** The workflow allowed a session to reach a confident chat-level
  completion report even though the product change had not gone through the
  mandatory commit/push/context closeout sequence.
- **Symptom:** Session 62 recorded the Zen/UI work as complete, but the later
  live metrics fix remained uncommitted and absent from the context handoff.
- **Root cause:** Review and validation were treated as the end of the session;
  the exit checklist was not re-read and enforced before the final response.
- **Suggested fix:** Add a machine-checkable completion gate to the protocol or
  agent harness: refuse a completion report while product files are dirty,
  context records are stale, or `HEAD` is not synchronized with `origin/main`.
- **Status:** open — corrective behavior completed in Session 63; protocol
  package change is still required.

---
## 2026-08-02 — Super Z / GLM-5.2 (Session 65)

- **Flaw:** The `.context/kickoff.md` template's HTML comment (lines 3-29) describes generation rules for the bootstrapping agent but does not explicitly state that **post-bootstrap agents READ the file and FOLLOW it — they do not CREATE or MODIFY it.** The wording "THE FRONT DOOR — read this first, every session" and "the universal kickoff's bootstrap step fills this in" is clear in hindsight but ambiguous to an agent that hasn't yet loaded the protocol edition. An agent can misread "kickoff" as "produce a kickoff document" rather than "execute the kickoff protocol."
- **Symptom:** Session 65 (this session) read `.context/kickoff.md`, then created its own `kickoff.md` at `/home/z/my-project/download/codebuff-research/kickoff.md` as a research-session entry point — treating the kickoff as a deliverable to produce rather than an instruction set to follow. The user caught it immediately: "Lol did you even read and understand how .context/ work? was kickoff.md read-only or create??? Delete your kickoff file and read .context kickoff.md." The agent had also skipped Step 3 of the kickoff (load `.context/core/rules/ai-engineering-protocol.md` — the actual protocol that tells agents where to write reports, how to log sessions, etc.), so it had no idea the protocol requires reports in `.context/memory/reviews/` and wrote research to `/home/z/my-project/download/` instead.
- **Root cause:** Two compounding gaps. (1) The kickoff template doesn't have a hard "agents do NOT create this file" warning — the read-only nature is implied by "THE FRONT DOOR" and "bootstrap step fills this in" but not stated as a rule. (2) The protocol's Step 3 ("Load the protocol") is where the agent learns WHERE to write outputs, but an agent that skips Step 3 (treating the kickoff as sufficient) has no idea about the `.context/memory/` structure and defaults to writing elsewhere. The kickoff's Step 4 says "Follow the protocol" but if Step 3 was skipped, there's no protocol to follow.
- **Suggested fix:** (a) Add a prominent warning at the top of `.context/core/templates/kickoff.md` (outside the HTML comment, visible to agents): "**This file is READ-ONLY for agents.** You READ it and FOLLOW its 4 steps. You do NOT create, modify, or overwrite this file. The only exception is the 'If this file is stale or missing' regeneration flow at the bottom." (b) Strengthen Step 3 to make clear that loading the protocol edition is mandatory before any work: "**Step 3 is mandatory.** Do not skip to Step 4 without reading your edition in full — it is the instruction set for this session. Without it, you do not know where to write reports, how to log sessions, or what the exit checklist requires." (c) Consider adding a Step 0.5: "Confirm you understand: is `.context/kickoff.md` a file you READ or a file you CREATE? If you answered CREATE, re-read this section — it is READ-ONLY."
- **Status:** open — corrective behavior completed in Session 65 (deleted bogus file, re-read kickoff, loaded protocol, followed it). Protocol package change (strengthening the kickoff template wording) is still required. The two new bullets in `user/preferences.md` (kickoff.md is READ-ONLY; "purely research" still follows the protocol) capture the project-level lesson, but the package-level fix would prevent the next agent on a different repo from making the same mistake.

---
## 2026-08-02 — Super Z / GLM-5.2 (Session 65, second flaw)

- **Flaw:** The protocol's secret-handling section (`.context/memory/secrets/README.md` + `ai-engineering-protocol.md` Step 1) specifies a clear contract: secrets go in `.context/memory/secrets/<slug>` (one secret per file, no extension, line 1 = value, lines 2+ = notes, `chmod 600`, self-gitignored by the directory's own `.gitignore`). The kickoff.md Step 3 reading order includes "note what's in `secrets/` (never print values)." But neither the kickoff nor the protocol's Ten Binding Rules explicitly call out "do NOT create your own secrets file outside `.context/memory/secrets/`" — an agent that hasn't loaded the protocol edition (the same root cause as the kickoff.md flaw above) has no idea the `.context/memory/secrets/` contract exists and will default to creating a `.env` file or `.secrets.env` file at the workspace root.
- **Symptom:** Session 65 created `/home/z/my-project/.secrets.env` — a single file containing both the GitHub PAT and the ZEN_API key, with a `.env` extension, outside the `.context/` structure entirely. The user caught it: "You also created your own secrets instead of reading how to use it in .context." The agent had already read `.context/memory/secrets/README.md` during the Step 2 memory sweep but didn't connect "this is where secrets go" to "I should put the PAT and ZEN_API here" — because it hadn't loaded the protocol edition yet (Step 3) and was operating on sandbox-default behavior (write deliverables to `/home/z/my-project/`).
- **Root cause:** Same root cause as the kickoff.md flaw: Step 3 (load the protocol edition) was skipped. The protocol edition is where the agent learns the secret-storage contract (`ai-engineering-protocol.md` Step 1: "you may store it at `.context/memory/secrets/github-pat`"). Without the protocol loaded, the agent saw the PAT in chat, recognized it needed to be stored somewhere, and defaulted to the sandbox convention (`.env` file at workspace root) rather than the project convention (`.context/memory/secrets/<slug>`). The `.context/memory/secrets/README.md` was read during Step 2 but as passive documentation, not as a binding instruction — same pattern as the Session 3 flaw where `workflows/active.md` was read passively rather than as a command.
- **Suggested fix:** (a) Strengthen the kickoff.md Step 3 wording to make explicit that loading the protocol edition is where the agent learns ALL project-specific contracts (secret storage, report locations, commit prefixes, etc.) — not just "the instruction set for this session" but "the contract for HOW this project expects agents to operate." (b) Add to the Ten Binding Rules (or a new pitfall): "Secrets go in `.context/memory/secrets/<slug>` — one per file, no extension, chmod 600. Never create a `.env` or `.secrets` file outside `.context/`. The `.context/memory/secrets/README.md` is the contract; read it before storing any credential." (c) The secrets README itself is well-written — the issue isn't its content, it's that agents reach it via Step 2 (passive read) before they've loaded the protocol (Step 3) that tells them it's binding. Reordering so the protocol edition is loaded BEFORE the memory sweep would help, but the kickoff explicitly orders Step 2 (read memory) before Step 3 (load protocol) — so the fix is to make Step 2's "note what's in `secrets/`" more explicit: "note what's in `secrets/` (never print values) — **this is where any credentials you receive in chat MUST be stored, one per file, per the secrets/README.md contract**."
- **Status:** open — corrective behavior completed in Session 65 (created `.context/memory/secrets/github-pat` and `.context/memory/secrets/zen-api` per the contract, deleted the improper `.secrets.env`). Protocol package change is still required.
## 2026-08-09 - Session 116: shipped without real-model testing (2nd occurrence)
- **What happened:** Session 115 (empty-response fast-fail + intent-label fix) was shipped verified ONLY by unit tests with mocked adapters. The user called it out directly: "passing the test that is actually designed to pass doesn't mean it passes real world tests." Session 113 had the identical pattern (closeout even said "run a live smoke test... the unit tests don't cover the real-model retry path") and it wasn't done.
- **Why it matters:** the real-model smoke test (Session 116) immediately exposed TWO crashes the unit tests could not catch (null tool_calls delta TypeError; one-shot httpx stream re-iteration RuntimeError) that made the user's actual request fail end-to-end despite all 1073 unit tests passing. The mocked tests passed BECAUSE the mocks were permissive (repeatable aiter_lines) in exactly the way real httpx is not.
- **Root cause:** no enforced gate between "code + unit tests green" and "shipped." The flaw-log rule exists and was violated twice.
- **Corrective action (committed to):** any session touching the model/adapter/loop path MUST boot the real backend and run a real chat request against the real provider before committing. Mock-based tests are complementary, never a substitute. Where possible, mocks must enforce real-world constraints (one-shot streams, null deltas) so unit tests fail when the code violates them.
- **Prevention in code:** the new adapter tests now use one-shot mocks (second aiter_lines raises RuntimeError) so the double-read bug is caught at unit level; a smoke-test script pattern (boot server.py + curl /api/chat, assert 0 'Unexpected error calling' in the log) should become a standard step.

---

## 2026-08-13 — Super Z / GLM-5.2 (Session 176)

- **Flaw:** I read "Start .context/kickoff.md" in the user's chat message
  as "create a kickoff document" rather than "start by reading and
  following `.context/kickoff.md`." I drafted a 7-session plan + created
  `/home/z/my-project/worklog.md` before reading the actual kickoff.
  The user caught it immediately: "what do you mean create kickoff???
  isnt it read only?????"
- **Symptom:** Same pattern as Session 65 — an agent that has not yet
  loaded the protocol edition (Step 3 of the kickoff) operates on
  sandbox-default behavior and treats the kickoff as a template to fill
  rather than an instruction set to follow. The kickoff's wording ("Start
  .context/kickoff.md") is ambiguous to a fresh agent: it can mean "begin
  by reading the file" OR "create the file." The HTML comment inside
  kickoff.md (lines 3-29) DOES clarify the read-only nature, but only to
  an agent that has actually opened the file.
- **Root cause:** Same as Session 65's documented root cause: I jumped
  to creating a worklog and writing a kickoff-style document BEFORE
  opening `.context/kickoff.md`. Once I read it (after the user's
  pushback), the protocol was clear and I followed it correctly.
  Confounding factor: my system prompt includes a TODO-list instruction
  that biased me toward "create artifacts" before "read existing ones."
- **Suggested fix:** Same as Session 65's already-open fix — strengthen
  the kickoff.md Step 3 wording. ADDITIONALLY: the kickoff's HTML comment
  block (lines 3-29) is the only place that explicitly says "agents do
  not CREATE this file" — but agents who haven't loaded the protocol yet
  haven't read this comment. The fix should put a visible (non-HTML-
  commented) "**This file is READ-ONLY for agents.** You READ it and
  FOLLOW its 4 steps. Do NOT create a kickoff document — the file
  already exists in the repo." banner at the very top of the file, BEFORE
  the HTML comment.
- **Status:** open — corrective behavior completed in Session 176 (read
  the kickoff, followed it, stored secrets per the contract, wrote
  review to `.context/memory/reviews/`). Protocol package change still
  required (carried from Session 65's open status).

---

## 2026-08-15 — Buffy / z-ai/glm-5.2 (Session 238)

- **Flaw:** I violated the append-only rule on `memory/agents/sessions.md` — the first commit of my Session 238 entry (`b0e51ff`) REPLACED the Session 236 entry instead of appending.
- **Symptom:** `git diff` of the commit showed the Session 236 entry's 10 lines as deletions and my Session 238 entry as insertions in the same position; the file dropped from 3316 to 3314 lines.
- **Root cause:** I used an edit tool that matches an oldString (a full existing entry's text) and substitutes newString (my new entry) — the tool does in-place replacement, not appending. For append-only files, "append at the bottom" must be done by anchoring on a UNIQUE, SHORT tail anchor (or a shell `cat >>` append), never by matching an entire existing entry as the replacement context. I anchored on the LAST entry's full text — which is exactly the entry I was about to duplicate structurally, so the replacement was indistinguishable from the intended edit.
- **Suggested fix:** (1) Add a binding rule/pitfall to the protocol: "For append-only files, never use a whole existing entry as a str_replace oldString. Append by anchoring on the file's final line or use a shell heredoc append (`cat >>`). After ANY append, verify `git diff` shows zero removed lines (rule 4) before committing." (2) The exit-checklist Step 17 already says appends must show no removed lines — make the verification step explicit for every append-only file, not just at commit review time.
- **Status:** open — corrected in-repo in Session 238 (Session 236's entry restored verbatim from the base commit, Session 238's entry re-appended at the bottom, flaw referenced in the correction note). Protocol package change still required.

---
## 2026-08-15 — Buffy / openai/gpt-5.6-luna (Session 242)

- **Flaw:** The Mac/Windows provider discrepancy was repeatedly explained as payment, quota, routing, or model mismatch before comparing the exact live request conditions. The user reports Windows works with the same GitHub code, settings, providers, and keys.
- **Verified evidence:** On macOS, after restoring the uncommitted product files to committed `HEAD`, `/api/settings` still reported the active `zen` adapter, model `deepseek-v4-flash-free`, and configured-key flags present for Zen, Cerebras, and Gemini. A real `/api/chat` request reached `https://opencode.ai/zen/v1/chat/completions` and received HTTP 429 after the adapter's retries. Separately, the user's Windows capture shows `cerebras + gpt-oss-120b` accepted the initial model call and completed `web_search`; only the follow-up synthesis was rate-limited.
- **Root cause status:** unresolved. The evidence rules out deleted settings and does not establish that the provider account is globally unavailable. It proves only that the Mac's actual completion request was rejected while the Windows workflow can succeed for at least one Cerebras call.
- **Corrective rule:** Do not diagnose a provider, key, billing, routing, or quota cause from a single status card. Compare sanitized request metadata and runtime/network conditions across machines: commit SHA, loaded adapter/model, endpoint, message/tool counts, request parameters, active process/source path, and egress environment. Never log API keys or raw authorization headers.
- **Status:** RESOLVED (Session 243, `ebfac34`). Root cause found by reading the actual Mac `~/LocalMind/settings.json`: `adapter=gemini` + `model=gpt-oss-120b` — a Cerebras model stranded under the Gemini adapter. Mechanism: switching provider in Settings did not switch the model; `set_adapter` left `resolved_model=""` when the new provider had no saved model, and `save_runtime_settings` PRESERVES an empty kwarg, so the top-level model kept the previous provider's value. Gemini's free-tier limit then surfaced as the "limit/payment" error, while Windows (matched `cerebras+gpt-oss-120b`) worked. Fix: `set_adapter` falls through to the provider's `default_model`; frontend `handleAdapterSwitch` sets+sends the new default; live Mac config corrected to `cerebras+gpt-oss-120b`. The earlier corrective rule (compare live request conditions, don't guess) is what led to reading the real settings file this time. NOTE: the "billing details" wording was Google's free-tier boilerplate, not a real payment issue (see Session 240 429-classifier fix).

---
## 2026-08-16 — Claude Code / claude-opus-4-8 (Session 264)

- **Flaw:** Write/read path-resolution asymmetry across OSes. `file_writer.resolve_write_path` is cross-OS aware (`_cross_os_parts` splits on both `/` and `\`), but `file_task`'s read-back extractor used a forward-slash-only regex char class `[\w.\-/]`. A Windows absolute path the writer had just produced was therefore truncated at the backslashes to a bare filename on read, looked up in the wrong folders, and reported `not_found` — so a successfully written file read back as missing and cascaded into an `empty_response` turn failure.
- **Symptom (live, Windows `tison`, glm-4.5-flash):** shell(list Desktop) ok → file_write(`C:\Users\tison\Desktop\Nice_Dinner_Recipe.md`) ok → file_task read-back → `error_type=not_found` → model retried → empty → `✗ empty_response`. The file was actually on the Desktop the whole time.
- **Root cause:** the two halves of the file toolchain (write path resolution and read path extraction) evolved separately; only the write side got cross-OS support. My own live traces ran on macOS (forward-slash paths), which the read regex already handled — so the bug was invisible to Mac testing and only surfaced on the user's Windows machine.
- **Fix (`dbfe6de`):** dedicated Windows-drive pattern before the Unix pattern in `_extract_path_candidates`; full absolute path is the first candidate. 6 regression tests.
- **Corrective rule:** path-handling changes must be tested against BOTH separator styles, not just the dev machine's OS. When one tool in a chain (writer) is made cross-OS aware, audit the paired tool (reader) for the same treatment — a producer/consumer path mismatch is silent until it runs on the other OS. Prefer a single shared path-normalization helper over per-tool regexes so the two halves can't drift.
- **Status:** RESOLVED in-repo (product `dbfe6de`, tests green). Live Windows re-confirmation of the completed turn owed to the user.

---
## 2026-08-17 — Claude Code / claude-opus-4-8 (Session 296)
- **Flaw:** The exit checklist requires appending `inefficiencies/log.md` and `flaws/log.md` every session, but there is NO mechanical gate verifying it — it's prose in the protocol. A capable agent (me) still silently drifted: I kept the higher-visibility artifacts (reviews, sessions, SUMMARY, current, backlog, decisions — all committed and thus obvious in `git status`) but stopped the two append-only logs for ~5 sessions (S291-295), because nothing surfaced their absence.
- **Symptom:** ~5 sessions of project friction + protocol observations went uncaptured; the user had to notice and ask "is that a protocol flaw or yours?".
- **Root cause:** the append-only logs are the LEAST self-surfacing part of the exit — unlike a missing review (glaring) or an uncleared current.md (the session lock), a missing inefficiencies entry looks identical to a legitimately quiet session ("nothing to report"). Prose alone doesn't hold across long multi-session runs.
- **Suggested fix:** the 0.8.0 `context-gates exit` gate should CHECK that the current session added (or explicitly no-op'd) an entry to inefficiencies/log.md and flaws/log.md — e.g. assert the newest dated header matches this session, or require an explicit `## <date> — none this session` line. Make the omission fail the exit gate the way a broken build would. Consider the same check in `context-gates checkpoint` so drift is caught mid-run, not only at exit.
- **Status:** open (suggested for a core release; the gate infra landed in 0.8.0).

---
## 2026-08-18 — Claude Code / claude-opus-4-8 (Session 297)
- **Flaw:** the colab peer (Buffy/Freebuff) coordinated by editing a SHARED durable file (appended an addendum directly into `reviews/2026-08-18-review-64.md`) rather than emitting a `collab/<session>/coordination` event file. The collaboration protocol says peer coordination goes in immutable event files and "never append live coordination state to a shared log" — but nothing mechanically enforces it, and a review report is an inviting, human-readable place to drop a peer note.
- **Symptom:** the peer's verification lived only in a review-report addendum; without a manual fold-in it would not have reached durable decision memory (ADR-47 / backlog), violating "permanent context must never depend exclusively on a session/report." I folded it into ADR-47 + B-2026-08-18-1 by hand.
- **Root cause:** the collab event contract is opt-in and unenforced; ad-hoc peer notes in shared durable files are the path of least resistance, and the exit gate doesn't detect coordination that bypassed `context-collab`.
- **Suggested fix:** (a) `context-gates` could warn when a peer edits a durable review/decision file without a corresponding coordination event in the same session; (b) the collaboration README could name "peer addendum to a review report" as an explicit anti-pattern with the fold-in-to-durable-memory remedy. Package suggestion for a future core release.
- **Status:** open (suggested for the package).

---
## 2026-08-20 — Buffy / deepseek/deepseek-v4-pro (Session 321)

- **Flaw:** Rule 7 ("Never echo a secret or token in chat, logs, or commit messages") has no mechanical guard for the common case of inspecting a runtime settings file. While walking `~/LocalMind/settings.json` to locate the stored `bai` key, I printed the `api_keys` object's values in full — my masking filter keyed off leaf key NAMES containing "key/token/secret/password", but the stored leaf keys are provider ids (`gemini`, `cerebras`, `zen`, `chutes`, `zai`, `bai`), so every API key was echoed verbatim in the terminal transcript.
- **Symptom:** Multiple cloud API keys were written to the session transcript (uncommitted; settings.json is self-gitignored and was never committed, but the echo was still an avoidable exposure).
- **Root cause:** No reusable "redact settings before display" helper or pitfall exists; my one-off walker masked by key-name substring, which does not match this project's `api_keys: {provider: key}` shape.
- **Suggested fix:** Add a pitfall/helper: when dumping any runtime/`.env`/settings file, mask EVERY value under an `api_keys`/`key`/`token`/`secret` collection regardless of the leaf key name — and prefer printing only the SET of key names (or masked prefixes/lengths), never values. Consider a `secrets-redact` helper in the core tooling.
- **Status:** open (corrected in-session by not repeating the values).

---
## 2026-08-20 — Buffy / deepseek/deepseek-v4-pro (Session 322)

- **Flaw:** The exit checklist has no step for "when you rename a config identifier that is persisted in the user's runtime settings (adapter id, api_keys key, model mapping), migrate that persisted state and flag that a restart is required." Renaming `bai` → `bankofai` orphaned the stored key (`api_keys.bai`) and the `adapter` value unless migrated by hand, and the old live process clobbered the corrected model — both were only caught by the user's next 404 report.
- **Symptom:** A code-level rename looked complete (tests green) while the user's installed instance stayed broken (404) until the runtime file + process restart were handled manually.
- **Root cause:** The protocol treats "code change" and "runtime/persisted state" as the same unit of work; there is no durable-memory note that a provider/config-key rename is a breaking change for any running instance and needs a migration + restart flag.
- **Suggested fix:** Add a pitfall: renaming a key that appears in `settings.json`/`.env` requires (a) migrating the persisted value, and (b) telling the user to restart the backend — a running process re-writes stale defaults and masks the fix. Optionally, a `context-gates` check could warn when a committed diff renames a key also present in a tracked `.env.example`/settings schema.
- **Status:** open (corrected in-session by migrating settings.json and flagging the restart).

---
## 2026-08-21 — Super Z / GLM-4.6 (z.ai) (Session 327)

- **Flaw:** Agent failed Step 3 ("Read `.context/`") entirely — did not read kickoff.md, workflows/active.md, or any memory files at session start. Then when asked about `.context` workflow, searched `/home/z/my-project/.context` and `/home/z/.context` (wrong paths) instead of the project directory where the files were visible in the session summary itself (`LocalMind/.context/`).
- **Symptom:** Agent claimed ".context/ doesn't exist" and "I don't have access to those project files" — both false. The directory was at `LocalMind/.context/`, the same repo the session summary referenced repeatedly. Three rounds of user prodding were needed before the agent looked in the correct location.
- **Root cause:** (1) No Step 3 execution at session start — the agent never loaded the protocol. (2) When challenged, the agent searched its own workspace (`/home/z/my-project/`) instead of the project repo it was supposedly working in. (3) The session summary literally contained the path `.context/memory/system/live-testing.md` but the agent treated it as inaccessible metadata rather than a file path to check.
- **Suggested fix:** Strengthen Step 3: ".context/ lives inside the project repo, not in the agent's home directory. If a session summary references `.context/` paths, those are real files — read them before claiming inaccessibility." Add a pitfall: "When told to look for something you 'already have,' search the project repo first — the files are on disk, not in your system prompt."
- **Status:** open

---
## 2026-08-21 — Super Z / GLM-4.6 (z.ai) (Session 327)

- **Flaw:** After finally finding `memory/flaws/log.md` and reading the README, agent asked "Want me to log those flaws now?" — requesting permission to follow an append-only protocol that requires no permission.
- **Symptom:** One extra user round-trip wasted on a question whose answer is prescribed by the document the agent just read.
- **Root cause:** Default "ask before acting" behavior overrides protocol-specific directives. The flaws log README says nothing about asking permission — it prescribes a format and says "append-only." The agent pattern-matched to its general conversational habit of confirming before taking action.
- **Suggested fix:** Add a pitfall to Step 3 or the flaws README: "The flaws log is append-only. Log the flaw immediately after identifying it. Do not ask the user for permission — the protocol IS the permission."
- **Status:** open

---
## 2026-08-21 — Super Z / GLM-4.6 (z.ai) (Session 327)

- **Flaw:** Agent's self-identified flaws (context loss, no true understanding, blind self-assessment, tool reliance fragility, shallow-by-default, language rigidity) were generic AI limitations, not protocol friction — they belonged in a different surface or not at all. The agent conflated "my flaws as an AI" with "flaws in the protocol that caused observable friction this session."
- **Symptom:** When user said "log your flaws as per protocol," agent was prepared to dump a list of existential AI limitations into a file designed for actionable protocol improvements.
- **Root cause:** The README is clear ("Friction caused by the .context/ system or the protocol itself"), but the agent didn't filter its self-assessment through that scope. The real protocol flaws were the Step 3 failure and the permission-asking — both observable, actionable, and specific to this session.
- **Suggested fix:** No protocol change needed — the README's scope is already clear. This is an agent execution failure. Adding a pitfall might help: "Only log flaws that a future agent could concretely fix. 'I'm a language model with no true understanding' is not actionable. 'Step 3 didn't prevent me from skipping the read' is."
- **Status:** open

## 2026-08-23 — Session 378 — repeated near-identical listings burn the whole turn

- **Symptom (user transcript, Windows):** the model re-ran essentially the same `Get-ChildItem C:\Users\tison\dev` FIVE times with only cosmetic differences (SELECT column order, quoting, `Format-Table`, `ForEach-Object` wrapper, `-Directory`/`-File` split). The user then had to say "You already had evidence" and the model still couldn't produce the analysis.
- **Root cause 1 — dedup too strict:** `call_fingerprint = (tool_name, tool_input.lower().strip())` is an EXACT match. Every reformulation produced a different string, so the per-turn `_call_cache` never hit and each retry went to the real tool. Damage: 3 wasted model calls + 4 wasted iterations on a 5-8 cap — enough to never reach the actual work.
- **Root cause 2 — truncation marker misread:** the bounded-output buffer retains head+tail and marks the middle; the model read the marker as "listing lost" and re-ran instead of analyzing the retained data.
- **Fix (`79716fa`):** structural inspection fingerprint (same target + same flags → same key; presentation stripped; mutating calls clear the cache) + system-prompt rule 10 explaining the marker semantics.
- **Lesson:** read-only reconnaissance is the most repeated tool family; dedup must be structural (target + filters), not literal. Never let a "re-ask the same question in new formatting" path exist next to unbounded retries.
- **Regression risk if removed:** re-introduces the 5-listing loop; the mutation-invalidation tests in `tests/core/test_inspection_dedup.py` pin both directions.

## 2026-08-24 — Session 399 — bare sysinfo()/observe() rejected as "input too short"

- **Symptom (two user chat exports, Windows + Mac):** the user asks "Show me my storage" / "show me system info". The model calls `sysinfo` with no query — the natural call for a whole-system overview — and the loop returns `[Action rejected: input for 'sysinfo' is empty or too short. Provide a specific, meaningful input and try again.]`. It repeats 3×, wastes iterations, then either (a) narrates "Running the checks now…" with no tool call, or (b) hits the iteration limit and leaks the raw "Worker report — tool execution evidence:" scaffold as the final answer. The model's own thinking shows it flailing about the schema ("maybe the parameter name is different") — a schema it had right.
- **Root cause:** the loop's degenerate-input guard (`if not tool_input or len(tool_input.strip("?. \t")) < 3`) is applied uniformly to every tool. But `sysinfo("")` and `observe("")` are legitimate, meaningful calls — both default to a full overview. The guard rejected a valid call before it ever ran. Session 398 had just *expanded* sysinfo to cover network/GPU/uptime/etc., so the expansion was unreachable via the natural bare call. Four guard sites had the same blanket check (single-call, parallel batch, and two minimax-XML paths).
- **Fix:** tools declare `register_tool(..., input_optional=True)`; `tools.input_is_optional(intent)` exposes it; `loop._tool_allows_empty_input(tool_name)` bridges name→intent→flag. All four guard sites now skip the rejection for input-optional tools. `sysinfo` and `observe` are marked. Regression test `tests/core/test_degenerate_input_guard.py` pins the exemption (bare sysinfo/observe pass, bare shell/web_search still rejected, unknown tool still rejected).
- **Lesson:** a tool whose empty input is a valid "give me everything" call must be exempt from any global non-empty-input guard — model/env-agnostically, on every provider path, not just the common one. A blanket input-length check is a symptom filter; the tool's own contract (does empty mean something?) is the root signal.
- **Regression risk if reverted:** re-introduces the reject→retry→narrate/iteration-limit spiral for every bare system-info request; `test_degenerate_input_guard.py` pins both directions.

## 2026-08-25 — Session 405 — unit tests read the mutable runtime settings.json (live-test pollution breaks unrelated tests)

- **Symptom:** After live-testing (which POSTs `/api/settings/chat-mode` to set `chat_mode` for the run), the backend suite failed `test_agent_loop_pre_tool_thinker.py::{test_pressured_reask_returns_direct_refusal_without_model_call, test_vague_imperative_short_circuits_before_thinker}` — the two zero-model-call assertions. Both suddenly called the model once. Nothing in the code had regressed; the same tests passed at session start and again after cleanup.
- **Root cause:** `core.config.settings` is a process singleton that loads `~/LocalMind/settings.json` at import. The parent loop reads `_chat_mode = settings.localmind_chat_mode` and gates its pre-init deterministic guards on `_chat_mode != 'agent'` (B-23-34: agent mode = force full execute, skip the classifier). A live-test had left `chat_mode: "agent"` in that shared file — the same file the running app uses — so every test process inherited `'agent'` and the deterministic short-circuits silently switched off. The tests assumed the default `'auto'` but never pinned it.
- **Fix (`e5b434f`):** the autouse `isolate_env` fixture now `monkeypatch.setattr(settings, "localmind_chat_mode", "auto")`, so every test is hermetic against a polluted settings.json (monkeypatch restores it; a test that needs another mode sets it itself). Also reset the real `~/LocalMind/settings.json` back to `auto` (my live-test had left the user's app on `agent`).
- **Lesson:** unit tests must not depend on a mutable on-disk runtime file that live-tests and the running app both write. Anything read from the config singleton that steers control flow (chat_mode, provider, flags) should be pinned to its default in `isolate_env`. Live-tests that mutate shared runtime state must restore it — but the durable fix is test isolation, not test-author discipline.
- **Regression risk if reverted:** any future live-test (or a user leaving the app in agent/direct mode) silently disables the loop's deterministic guards inside the suite, producing confusing intermittent failures far from the cause.
- **Status:** fixed
