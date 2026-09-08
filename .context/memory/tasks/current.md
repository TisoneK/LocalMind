# Current Task

**Status:** IDLE — **Session 442 (Nadia / ZCode local, glm-5.3-flash, Windows)
COMPLETE (2026-09-08): core sync 0.16.1 → 0.17.0 SHIPPED.**

**What landed (commit 278d80f):** vendored core updated 0.16.1 → 0.17.0 via
`context-sync update` (same-MAJOR, verify clean before and after). Headline
change: check-in is universal — every session (solo included) adds/updates a
roster row and pushes it BEFORE product work; solo-mode decision now requires
no live foreign roster row; clock-out (row removal) joins the closing memory
commit; `context-mem check` audits board-vs-duty-log. kickoff.md regenerated
from the 0.17.0 template and refilled (all facts verified — repo URL,
public, main, git identity); AGENTS.md regenerated from the new template with
all project addenda re-attached (Sessions 12–303 sections intact).

**Board hygiene (first use of the new audit):** `context-mem check` flagged
all nine S430–S441 rows as logged-done-without-clocking-out; rows removed
(duty record stays in sessions.md + roster git history). Board now: Nadia
S442 only at time of writing; Nadia clocked out in this session's closeout.

**Findings filed:** B-2026-09-08-2 — gates.conf pre-commit ruff entry
(`backend/.venv/bin/ruff`) is POSIX-only; on Windows it must be
`backend/.venv/Scripts/ruff.exe`. Gate currently fails that one command
every Windows session (substance passes: ruff + tsc verified clean by hand).
Also noted in inefficiencies: `context-mem lint` false-positives on
AGENTS.md (entrypoint digest cites `.context/` by design; exempt-list
candidate for the upstream core).

**Feature:** none

**Next up for the owner:** the standing queue is unchanged; B-2026-09-08-1
(eslint ratchet tranche below 53) and B-2026-09-08-2 (gate path fix) are the
newest items. Residue delete-list (B-2026-09-06-5) still awaits owner
confirmation.
