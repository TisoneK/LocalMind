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
