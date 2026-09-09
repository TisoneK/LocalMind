# Agent Instructions — <PROJECT_NAME>

<!-- Generated at bootstrap from .context_ledger/core/templates/AGENTS.md.
Refreshed on core updates (fill <PROJECT_NAME> again). This is the canonical
entrypoint digest. Bootstrap also installs a CLAUDE.md pointer so Claude
Code (which auto-loads CLAUDE.md, not this file) is routed here. If the
project uses other agent tools, add a one-line "read AGENTS.md first"
pointer to their entrypoint too — Copilot: .github/copilot-instructions.md,
Cursor: .cursor/rules, Gemini: GEMINI.md, Codex/others: this AGENTS.md. -->

This repo uses the `.context_ledger/` protocol: persistent agent memory plus a
vendored copy of the full workflow, committed to git. **Before doing any
work, read `.context_ledger/kickoff.md` and follow it.** It routes you — local
IDE agent or cloud/sandbox agent — to the right instruction set in
`.context_ledger/core/rules/`.

If you read nothing else, obey these rules:

1. **Start at `.context_ledger/kickoff.md`.** Do not treat "start the context
   workflow" as running this project's app, and do not grep the codebase
   for "context" — the protocol lives in the `.context_ledger/` directory.
2. **Never write under `.context_ledger/core/`** — it is a read-only, versioned
   copy of the protocol. All project memory you write lives under
   `.context_ledger/memory/`.
3. **Pick your instruction set by YOUR agent type**, never by what a
   previous session recorded: local IDE agent →
   `.context_ledger/core/rules/ai-engineering-protocol-local.md`; cloud/sandbox
   agent → `.context_ledger/core/rules/ai-engineering-protocol.md`. Local
   agents never use PATs or clone this repo; cloud steps are not yours.
4. **Read memory before working:** at minimum
   `.context_ledger/memory/workflows/active.md`,
   `.context_ledger/memory/agents/sessions.md` (last entries),
   `.context_ledger/memory/agents/roster.md` (the "who's in the office" board —
   a live row you didn't write means a peer is here),
   `.context_ledger/memory/collaboration/README.md` and relevant event files
   when collaboration is enabled, `.context_ledger/memory/workflows/gates.conf`,
   `.context_ledger/memory/tasks/current.md`, and
   `.context_ledger/memory/inefficiencies/log.md` (known traps). If the
   active session has detailed notes at
   `.context_ledger/memory/sessions/`, skim them for current state.
5. **Check in first, then choose the mode from evidence.** Every session
   (solo or collaboration) adds or updates its row in
   `memory/agents/roster.md` — real name you pick (unique per group),
   codename `S<NNN>`, model, one line on what you're on — and pushes it
   before product work. Roster edits are additive — your row only: a live
   row you didn't write is a colleague's check-in, not sample text — never
   adopt a peer's name, never let an edit span a peer's row, review the
   `git diff` (exactly your row, `+1` on check-in) before committing. You
   are solo only when there is no shared
   collaboration `session` + `issue`, no live roster row you didn't
   write, and `tasks/current.md` is idle; otherwise coordinate (join or
   declare a session, isolated worktree/branch, `note` + `claim`) — a
   peer in the office is a teammate, not a rival, and the human is your
   supervisor: do not block teammates on `tasks/current.md`. Present
   yourself by your name — "John (S427)", never "peer". The everyday move
   is a
   `note` (the office channel — say what you're on, flag a coworker, review a
   diff); then `claim → work → release`. Save the `proposal → assessment → agreement`
   ceremony for a genuine conflict (same paths, incompatible changes).
   Before each next action run `ledger-gates checkpoint`; before commits,
   integration, and exit run the matching gate. On Windows, use the `.cmd`
   launchers (they run the `.ps1` ports; no execution-policy setup).
6. **Know which kind of file you're in.** *Append-only* logs
   (`agents/sessions.md`, `tasks/backlog.md`, `plans/decisions.md`,
   `flaws/log.md`, `inefficiencies/log.md`) grow at the bottom — never edit
   or delete past entries. *Update-in-place* registries
   (`system/ai-models.md`, `system/environments.md`) have one entry per key:
   correct them by **editing** the entry, never by appending a duplicate
   (its old value is in git history). `ledger-mem check` flags a dup key.
   Collaboration event files are stronger still: immutable, one event per
   file; emit a correction instead of editing one.
7. **No secrets in tracked files, ever.** Values go only in
   `.context_ledger/memory/secrets/` (self-gitignored). Never echo a secret or
   token in chat, logs, or commit messages.
8. **Two surfaces, two prefixes:** editing product code = normal commit
   prefixes; editing `.context_ledger/` = `chore(ledger):` (reports:
   `docs(review):`). Never mix both surfaces in one commit. Collaboration
   events are separate immutable context commits. And keep the surfaces
   apart in *content* too: never cite `.context_ledger` vocabulary (an ADR number,
   a bug ID, a `.context_ledger/` path) in a product docstring or comment — it's a
   dangling pointer for anyone reading only the product repo. `ledger-mem
   lint` flags it in your staged diff.
9. **The session is not done until everything is committed AND pushed**,
   the session is logged in `.context_ledger/memory/agents/sessions.md`, and
   `.context_ledger/memory/tasks/current.md` is cleared. Clock out too: remove
   your row from `.context_ledger/memory/agents/roster.md` in the closing
   memory commit, so the board shows who is in the office now — but only
   when you are actually leaving. The session is not over until the user
   says so; if you clocked out and the supervisor brings more work, check
   back in first (re-add your row, same name and codename `S<N>`) and
   extend your existing `sessions.md` entry — never a second `Session N`.
   If the user has to remind you to commit or push, that is a protocol
   failure — log it in `.context_ledger/memory/flaws/log.md`.
10. **Don't ask permission for the default next step.** Do it and
    report. Ask only on genuine ambiguity or destructive/irreversible
    actions.

Formats and file rules: `.context_ledger/core/schemas/ledger-schema.md` is
the single source of truth. Project-specific rule adjustments:
`.context_ledger/memory/overrides/rules.md` (they win over the edition).
