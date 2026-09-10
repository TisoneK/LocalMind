# Backlog (live queue — open work only)

Undone or partially done items for future sessions. Append new items at
the bottom. When an item is finished, **delete its line** — the backlog
holds only open work, never completed tombstones. The completion record
is the finishing session's `agents/sessions.md` entry and the commit
itself; git history keeps every removed line, so deleting loses
nothing. Never remove a line whose item is still open — a `- [ ]` line
vanishing from the diff without a matching session entry is a dropped
handoff, not cleanup. A checked-off `- [x]` line a session left behind
is a finished tombstone — sweep it with `ledger-mem closeout` (dry run
by default; `--confirm` deletes).

<!-- TEMPLATE — copy below the last entry:
---
- [ ] **<short title>** (added YYYY-MM-DD by <agent>) — <enough context that
      a fresh agent can act on this without any chat history. Severity if known.>
-->
