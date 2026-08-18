# Agent Instructions — <PROJECT_NAME>

<!-- Generated at bootstrap from .context/core/templates/AGENTS.md.
Refreshed on core updates (fill <PROJECT_NAME> again). Optionally also
copied to CLAUDE.md and .github/copilot-instructions.md so tools that
auto-load those paths get the same digest. -->

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
   collaboration mode, use an isolated git worktree/branch and the
   immutable event trail; do not block peers on `tasks/current.md`. Before
   each next action run `context-gates checkpoint`; before commits,
   integration, and exit run the matching gate.
6. **Append-only files are append-only:** `agents/sessions.md`,
   `tasks/backlog.md`, `plans/decisions.md`, `flaws/log.md`,
   `inefficiencies/log.md`. Add at the bottom; never edit or delete
   past entries. Collaboration event files are stronger: immutable,
   one event per file; emit a correction instead of editing one.
7. **No secrets in tracked files, ever.** Values go only in
   `.context/memory/secrets/` (self-gitignored). Never echo a secret or
   token in chat, logs, or commit messages.
8. **Two surfaces, two prefixes:** editing product code = normal commit
   prefixes; editing `.context/` = `chore(context):` (reports:
   `docs(review):`). Never mix both surfaces in one commit. Collaboration
   events are separate immutable context commits.
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
