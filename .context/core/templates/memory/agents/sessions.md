# Agent Sessions (append-only within the current group)

One entry per agent session in the **current group**, newest at the bottom.
Never edit or delete past entries — append corrections instead. This is not
append-only *forever*: when the group reaches `group_size` sessions (or a
milestone), `ledger-history close` consolidates these entries into
`.context_ledger/history/group-<NNN>.md` and starts a fresh group here. Closed
groups in `history/` and `archive/` are never read at session start.
Before closing, promote any open thread into its durable domain file — the
new group starts clean.

<!-- TEMPLATE — copy below the last entry and FILL IN every placeholder:
---
## YYYY-MM-DD — Session N
- **Agent:** <name> | **Model:** <model id> | **Platform:** <machine/sandbox + OS> | **Role:** <engineer, or overlay from .context_ledger/core/roles/> | **Core:** <version from .context_ledger/core/VERSION>
- **Task:** <what this session set out to do>
- **Commits:** <count> (<first-sha>..<last-sha>)
- **Outcome:** <done / partial / blocked — one line>
- **Open items:** <pointers into tasks/backlog.md, or "none">
- **Notes:** .context_ledger/memory/sessions/<date>-<N>/notes.md  (or "none")
- **Report:** .context_ledger/memory/reviews/YYYY-MM-DD-review.md
-->
