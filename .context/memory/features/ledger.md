# Feature Ledger (append-only — permanent, one line per feature)

One line per feature ever — slug, started, outcome, finished. The
append-only guarantee protects the ledger; the feature directory is
working state, like `tasks/current.md`. A feature directory may be
archived or deleted **only after** its ledger line records the outcome
(merged `<sha>` / abandoned + reason) and the finish date.

<!-- TEMPLATE — copy below the last entry:
- **<slug>** — started YYYY-MM-DD · <merged <sha> | abandoned: <reason> | active> · finished YYYY-MM-DD | —
-->

- **agent-loop-closed-loop** — started 2026-07-26 · active · finished —
- **adr-8-agent-centric-routing** — started 2026-07-27 · active · finished —
