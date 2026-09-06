# Agent Instructions — <PROJECT_NAME>

<!-- Generated at bootstrap from .context/core/templates/AGENTS.md.
Refreshed on core updates (fill <PROJECT_NAME> again). This is the canonical
entrypoint digest. Bootstrap also installs a CLAUDE.md pointer so Claude
Code (which auto-loads CLAUDE.md, not this file) is routed here. If the
project uses other agent tools, add a one-line "read AGENTS.md first"
pointer to their entrypoint too — Copilot: .github/copilot-instructions.md,
Cursor: .cursor/rules, Gemini: GEMINI.md, Codex/others: this AGENTS.md. -->

This repo uses the `.context/` protocol: persistent agent memory plus a
vendored copy of the full workflow, committed to git. **Before doing any
work, read `.context/kickoff.md` and follow it.** It routes you — local
IDE agent or cloud/sandbox agent — to the right instruction set in
`.context/core/rules/`.

If you read nothing else, obey these rules:

1. **Start at `.context/kickoff.md`.** Do not treat "start the context
   workflow" as running this project's app, and do not grep the codebase
   for "context" — the protocol lives in the `.context/` directory.
2. **Never write under `.context/core/`** — it is a read-only, versioned
   copy of the protocol. All project memory you write lives under
   `.context/memory/`.
3. **Pick your instruction set by YOUR agent type**, never by what a
   previous session recorded: local IDE agent →
   `.context/core/rules/ai-engineering-protocol-local.md`; cloud/sandbox
   agent → `.context/core/rules/ai-engineering-protocol.md`. Local
   agents never use PATs or clone this repo; cloud steps are not yours.
4. **Read memory before working:** at minimum
   `.context/memory/workflows/active.md`,
   `.context/memory/agents/sessions.md` (last entries),
   `.context/memory/collaboration/README.md` and relevant event files
   when collaboration is enabled, `.context/memory/workflows/gates.conf`,
   `.context/memory/tasks/current.md`, and
   `.context/memory/inefficiencies/log.md` (known traps). If the
   active session has detailed notes at
   `.context/memory/sessions/`, skim them for current state.
5. **Choose the mode explicitly.** Without a shared collaboration
   `session` + `issue`, `tasks/current.md` is the single-agent lock. In
   collaboration mode you and your teammates are one team, not rivals, and
   the human is your supervisor: use an isolated git worktree/branch and the
   immutable event trail; do not block teammates on `tasks/current.md`. Pick
   a real name in `memory/agents/roster.md` (unique per group) and present
   yourself by it — "John (S427)", never "peer". The everyday move is a
   `note` (the office channel — say what you're on, flag a coworker, review a
   diff); then `claim → work → release`. Save the `proposal → assessment → agreement`
   ceremony for a genuine conflict (same paths, incompatible changes).
   Before each next action run `context-gates checkpoint`; before commits,
   integration, and exit run the matching gate. On Windows, use the `.cmd`
   launchers (they run the `.ps1` ports; no execution-policy setup).
6. **Know which kind of file you're in.** *Append-only* logs
   (`agents/sessions.md`, `tasks/backlog.md`, `plans/decisions.md`,
   `flaws/log.md`, `inefficiencies/log.md`) grow at the bottom — never edit
   or delete past entries. *Update-in-place* registries
   (`system/ai-models.md`, `system/environments.md`) have one entry per key:
   correct them by **editing** the entry, never by appending a duplicate
   (its old value is in git history). `context-mem check` flags a dup key.
   Collaboration event files are stronger still: immutable, one event per
   file; emit a correction instead of editing one.
7. **No secrets in tracked files, ever.** Values go only in
   `.context/memory/secrets/` (self-gitignored). Never echo a secret or
   token in chat, logs, or commit messages.
8. **Two surfaces, two prefixes:** editing product code = normal commit
   prefixes; editing `.context/` = `chore(context):` (reports:
   `docs(review):`). Never mix both surfaces in one commit. Collaboration
   events are separate immutable context commits. And keep the surfaces
   apart in *content* too: never cite `.context` vocabulary (an ADR number,
   a bug ID, a `.context/` path) in a product docstring or comment — it's a
   dangling pointer for anyone reading only the product repo. `context-mem
   lint` flags it in your staged diff.
9. **The session is not done until everything is committed AND pushed**,
   the session is logged in `.context/memory/agents/sessions.md`, and
   `.context/memory/tasks/current.md` is cleared. If the user has to
   remind you to commit or push, that is a protocol failure — log it in
   `.context/memory/flaws/log.md`.
10. **Don't ask permission for the default next step.** Do it and
    report. Ask only on genuine ambiguity or destructive/irreversible
    actions.

Formats and file rules: `.context/core/schemas/context-schema.md` is
the single source of truth. Project-specific rule adjustments:
`.context/memory/overrides/rules.md` (they win over the edition).
