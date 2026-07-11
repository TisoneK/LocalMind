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
