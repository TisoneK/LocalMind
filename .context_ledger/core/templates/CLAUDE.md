# CLAUDE.md — read this first, every session

<!-- Installed at bootstrap from .context_ledger/core/templates/CLAUDE.md. This is a
pointer, not the digest: agent tools that auto-load CLAUDE.md (Claude Code)
land here and are routed into the protocol. The full digest is AGENTS.md;
the authority is .context_ledger/kickoff.md + .context_ledger/core/. Keep this file short —
update AGENTS.md and the vendored core, not this pointer. -->

This repo runs the `.context_ledger/` engineering protocol (persistent agent
memory plus the full workflow, vendored into git). Your agent tool loaded
**this** file, but the protocol entrypoint is elsewhere — don't start work
from memory of this file alone.

## First action (before any edit, even a one-liner)

1. **Read [`AGENTS.md`](AGENTS.md)** — the protocol digest for this repo.
2. **Read `.context_ledger/kickoff.md` and follow it** (Step 0 → Step 1). It
   routes you to the right instruction set in `.context_ledger/core/rules/`.
3. **Sync and orient:** pull, then read
   `.context_ledger/memory/workflows/active.md` (standing params + push policy),
   `.context_ledger/memory/agents/sessions.md` (last few entries — the real HEAD
   and session number live here, not in the harness's start-of-session git
   snapshot, which can be stale), and `.context_ledger/memory/tasks/current.md`.
4. **Record the task** in `.context_ledger/memory/tasks/current.md` before editing.

Skipping this is a logged protocol failure — an agent once ran an entire
session with zero `.context_ledger/` discipline until the user had to ask whether
it had followed the protocol. This file exists so the kickoff read is the
first thing that happens, not the thing that gets skipped.

Everything else — git flow, gates, secrets, collaboration, exit checklist —
is in `AGENTS.md` and `.context_ledger/core/`.
