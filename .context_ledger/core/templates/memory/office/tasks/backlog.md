# Backlog (live queue — open work only)

Open items for future sessions, **arranged by priority so the shape of
the work is visible the moment the file opens**: one row per item, in
its priority table. When an item is finished, **delete its row** — the
backlog holds only open work, never completed rows. The completion
record is the finishing session's `agents/sessions.md` entry and the
commit itself; git history keeps every removed row, so deleting loses
nothing. Never delete a row whose item is still open — a row vanishing
from the diff without a matching session entry is a dropped handoff,
not cleanup. (Legacy checkbox-format backlogs: `ledger-mem closeout`
sweeps checked-off `- [x]` tombstones a session left behind — dry run
by default; `--confirm` deletes.)

Every row gets a stable **ID** — `B-<added YYYY-MM-DD>-<n>`, n = that
date's next sequence in the file — and a **Summary** cell with enough
context that a fresh agent can act on the item without any chat
history; keep status qualifiers in the summary text ("partial",
"done, pending sign-off", "deferred by owner", "advisory"). Priority
is the table an item sits in — when unsure, Medium.

This backlog belongs to the **current office**. When the office closes,
open items do not carry over implicitly — the closing session re-seeds
into the new office's backlog only what still matters, and records the
rest in the permanent record (`history/office-<NNN>.md`, "Open threads").

Full spec: `.context_ledger/core/schemas/ledger-schema.md` →
"The backlog: arrangement + workstream view".

## Open Items

### High Priority

| ID | Summary |
|----|---------|

### Medium Priority

| ID | Summary |
|----|---------|

### Low Priority

| ID | Summary |
|----|---------|

<!-- TEMPLATE — add one row to the matching priority table:
| B-<YYYY-MM-DD>-<n> | <enough context that a fresh agent can act on
      this without any chat history — status qualifiers in the text> |
-->
