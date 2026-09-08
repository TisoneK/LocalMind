# Current Task

**Status:** IDLE — **Session 444 (Vera / ZCode local, glm-5.3-flash, Windows)
COMPLETE (2026-09-08): core 0.17.0 → 0.18.0 + Context Ledger rename SHIPPED
(`c97b6f6a` update+migrate, `686e152e` rename, `12857f7f` sweep+regen,
`56485ee9` fix(ci) script paths).**

**What landed:** the project now runs the renamed `.context_ledger/` layout
with core 0.18.0 verified. Entry points (kickoff.md, AGENTS.md, CLAUDE.md)
regenerated from the 0.18 templates with facts refilled (package upstream is
now `https://github.com/TisoneK/context-ledger.git` — the old
`TisoneK/.context` URL redirects). Living memory instruction files swept
(paths, `ledger-*` tool names, `chore(ledger):` prefix); append-only logs and
collaboration/events/ left as written. Product-side: gate scripts and
live-test harnesses repointed (`fix(ci):` — check-conflict-markers.sh would
have scanned a nonexistent directory and passed vacuously).

**Verified on this box:** pre-commit gate 5/5 via the POSIX runner on the new
paths. **Windows caveat unchanged:** the PS gate runner's aggregate verdict is
still untrusted (S443 flaw OPEN — 0.18.0's `Run-One` still swallows child
stdout through the return pipeline). Use
`sh .context_ledger/core/bin/ledger-gates run <gate>` for formal gates.

**Feature:** none

**Next up for the owner:** S443's Run-One stdout-capture patch is UNBLOCKED —
the upstream ledger refactor shipped in 0.18.0; apply the documented patch in
the package repo → upstream release → `ledger-sync update` locally.
B-2026-09-08-1 (next eslint tranche below 53) and B-2026-09-05-4 (the 22
tests/tools Windows failures — baseline file gives the gate a green path
meanwhile) remain open. Residue delete-list (B-2026-09-06-5) still awaits
owner confirmation.
