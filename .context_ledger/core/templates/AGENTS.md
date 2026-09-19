# Agent Instructions — <PROJECT_NAME>

<!-- Generated at bootstrap from .context_ledger/core/templates/AGENTS.md.
Refreshed on core updates (fill <PROJECT_NAME> again). THE WEAK-AGENT
FLOOR — this is the one file some sessions on this repo will ever read in
full, so the single most safety-critical behavior (check in before
reading/analyzing) is stated here directly, not only routed to
kickoff.md. Everything else — reading order, gates, secrets,
collaboration, commit prefixes — IS routed to kickoff.md's phases and the
vendored core, not restated here (core 2.0.0 cut that three-way
duplication; core 2.0.2 restored just the check-in line after it caused
a real collision — see CHANGELOG). Bootstrap also installs a CLAUDE.md
pointer so Claude Code (which auto-loads CLAUDE.md, not this file)
reaches this same front door. If the project uses other agent tools, add
a one-line "read AGENTS.md first" pointer to their entrypoint too —
Copilot: .github/copilot-instructions.md, Cursor: .cursor/rules, Gemini:
GEMINI.md, Codex/others: this AGENTS.md. -->

This repo uses the `.context_ledger/` protocol: persistent agent memory
plus a vendored copy of the full workflow, committed to git.

**Do this before reading anything else in this repo — including the
rest of this file:** add your row to
[`memory/office/agents/roster.md`](.context_ledger/memory/office/agents/roster.md)
(a real name you pick — never your own model or product name; plus a
codename `S<NNN>`, your model, one line on what you're doing, and
Status `Working`), then commit and push it:
`chore(ledger): <name> (<codename>) checks in — <task>`. Reading or
analyzing first — even skimming this file to the end before pushing —
is how two sessions collide mid-task without ever seeing each other on
the board; the check-in **is** the session's first write, not a
formality to get to once you're settled in.

**Then** read [`.context_ledger/kickoff.md`](.context_ledger/kickoff.md)
and follow it, in order. Its Phase 2 covers this same check-in with the
full mechanics if anything above was unclear, then routes you — local
or cloud/sandbox agent, task scaled to size — to the right instruction
set.

The one rule that can't wait either: **never write under
`.context_ledger/core/`** — it is a read-only, versioned copy of the
protocol, replaced only as a whole tree by `ledger-sync`. Reading order,
gates, secrets, collaboration, and commit prefixes past check-in are
`kickoff.md`'s job to route you to. Full spec if something here and
there ever disagrees: `.context_ledger/core/schemas/ledger-schema.md`.
