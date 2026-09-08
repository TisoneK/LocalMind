# archive/ — cold storage of old session groups

Older closed groups, one gzipped tarball each (`group-<NNN>.tar.gz`),
produced automatically by `ledger-history` when `../history/` exceeds its
readable-keep window. Cold storage: unzip one only for a deep lookback.

**Not read at session start**, and never by default.

This zone is capped. When it exceeds `archive_keep` tarballs (default 12),
`ledger-history gc --confirm` deletes the oldest first, down to the cap —
a forced, consistent rule so `archive/` cannot grow unbounded either.
Deletion removes the tarball from the working tree only; it stays
recoverable in git history. Nothing durable is lost: every group's durable
knowledge was promoted into the live `memory/` domain files before the group
was ever archived.
