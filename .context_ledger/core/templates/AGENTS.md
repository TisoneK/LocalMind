# Agent Instructions — <PROJECT_NAME>

<!-- Generated at bootstrap from .context_ledger/core/templates/AGENTS.md.
Refreshed on core updates (fill <PROJECT_NAME> again). ROUTER ONLY — the
actual rules live in kickoff.md's phases and the vendored core, not here;
this file used to restate them and drifted into a third copy of the same
ceremony (core 2.0.0 stopped that — see CHANGELOG). Bootstrap also
installs a CLAUDE.md pointer so Claude Code (which auto-loads CLAUDE.md,
not this file) reaches this same front door. If the project uses other
agent tools, add a one-line "read AGENTS.md first" pointer to their
entrypoint too — Copilot: .github/copilot-instructions.md, Cursor:
.cursor/rules, Gemini: GEMINI.md, Codex/others: this AGENTS.md. -->

This repo uses the `.context_ledger/` protocol: persistent agent memory
plus a vendored copy of the full workflow, committed to git.

**Before doing any work, read [`.context_ledger/kickoff.md`](.context_ledger/kickoff.md)
and follow it, in order.** It checks you in, points you at the session
digest (`memory/office/STATE.md`), and routes you — local or cloud/sandbox
agent, task scaled to size — to the right instruction set.

The one rule that can't wait for that read: **never write under
`.context_ledger/core/`** — it is a read-only, versioned copy of the
protocol, replaced only as a whole tree by `ledger-sync`. Check-in,
reading order, gates, secrets, collaboration, and commit prefixes are
`kickoff.md`'s job to route you to — this file's only job is getting you
there. Full spec if something here and there ever disagrees:
`.context_ledger/core/schemas/ledger-schema.md`.
