# Feature Archive (cold storage for completed features)

Completed features whose ledger line is filled in (merged `<sha>` or
abandoned + reason) may be moved here. Archiving is a normal session
step, not a special ritual — any session that notices a merged
feature's directory still in the hot path may archive it.

A feature directory may also be deleted (rather than archived) once its
ledger line is complete — the ledger is the permanent record, the
directory is working state. For LocalMind, the default is **archive**
(matches our conservative "never delete history" pattern from
`flaws/log.md` Session 7 — the append-only dedupe exception was the
first time we authorized removal, and only for byte-identical
duplicates; full feature deletion should wait until the ledger habit is
established).

<!-- TEMPLATE — when archiving:
git mv .context/memory/features/<slug> .context/memory/features/archive/<slug>
# then append a one-line note here:
- <slug> — archived YYYY-MM-DD (merged <sha> | abandoned: <reason>)
-->
