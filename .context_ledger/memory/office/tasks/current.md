# Current Task (overwrite each session)

Holds exactly one task — the one being worked on right now. Set it at
session start (protocol Step 3), clear it at session end (Step 15). If
you find a stale in-progress entry here, a prior session died mid-task —
its roster row (if left behind) says who was here; check the session
entry and backlog before starting.

<!-- TEMPLATE — replace everything below this comment:
- **Session:** YYYY-MM-DD — <agent> / <model>
- **Task:** <what is being worked on right now>
- **Status:** in-progress | done | blocked (<blocker>)
-->

- **Session:** 2026-09-15 — Baraka / qwen3.8-flash (Asha S007 clocked out; this task belongs to S005, untouched)
- **Feature:** none
- **Task:** tree-wide strip of .context_ledger vocabulary from product files (backlog B-2026-09-15-1) — lint hits (ADR refs, bug IDs, ledger paths, "per ADR") plus missed classes (Session N / S<NNN> references, lowercase adr refs, token-bearing filenames); exempt structurally-legit surfaces (generated agent-entrypoint files) via a documented override
- **Status:** in-progress (owned by S005)
