# CLAUDE.md — read this first, every session

<!-- Installed at bootstrap from .context/core/templates/CLAUDE.md. This is a
pointer, not the digest: agent tools that auto-load CLAUDE.md (Claude Code)
land here and are routed into the protocol. The full digest is AGENTS.md;
the authority is .context/kickoff.md + .context/core/. Keep this file short —
update AGENTS.md and the vendored core, not this pointer. -->

This repo runs the `.context/` engineering protocol (persistent agent
memory plus the full workflow, vendored into git). Your agent tool loaded
**this** file, but the protocol entrypoint is elsewhere — don't start work
from memory of this file alone.

## First action (before any edit, even a one-liner)

1. **Read [`AGENTS.md`](AGENTS.md)** — the protocol digest for this repo.
2. **Read `.context/kickoff.md` and follow it** (Step 0 → Step 1). It
   routes you to the right instruction set in `.context/core/rules/`.
3. **Sync and orient:** pull, then read
   `.context/memory/workflows/active.md` (standing params + push policy),
   `.context/memory/agents/sessions.md` (last few entries — the real HEAD
   and session number live here, not in the harness's start-of-session git
   snapshot, which can be stale), and `.context/memory/tasks/current.md`.
4. **Record the task** in `.context/memory/tasks/current.md` before editing.

Skipping this is a logged protocol failure — an agent once ran an entire
session with zero `.context/` discipline until the user had to ask whether
it had followed the protocol. This file exists so the kickoff read is the
first thing that happens, not the thing that gets skipped.

Everything else — git flow, gates, secrets, collaboration, exit checklist —
is in `AGENTS.md` and `.context/core/`.
