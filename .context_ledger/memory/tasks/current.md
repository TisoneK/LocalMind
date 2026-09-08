# Current Task

**Status:** IDLE — **Session 443 (Iris / ZCode local, glm-5.3-flash, Windows)
COMPLETE (2026-09-08): B-2026-09-08-2 cross-platform gate portability SHIPPED
(product `4e114cd`, registry `202d81e`, logs `5fe0258`).**

**What landed:** the Windows gate path is fully portable and formally
verified end-to-end — ci-check.sh resolves the backend venv across
Scripts//bin layouts and runs tools via `python -m`; every gates.conf line
is a plain `sh scripts/...` invocation (new shims scripts/run-in.sh +
scripts/venv-run.sh) that parses under BOTH the POSIX runner and the
PowerShell 5.1 runner (the old `cd frontend && ...` tsc line was a PS parse
error — pre-commit could never pass here); pytest is baseline-aware against
scripts/pytest-baseline.txt (the documented 22 Windows failures, verified
this session; failure-SET compare, never-add/ratchet-down); bash-only
pipefail/`\<` removed from ci-check.sh + check-bookkeeping.sh; root
.gitattributes pins *.sh to LF.

**Verified on this box:** pre-commit gate 5/5 via context-gates.cmd; full CI
green direct (ruff clean, pytest 2939 passed / 22 = exactly the documented
baseline, tsc clean, eslint 0 err/53 warn, exit 0); formal exit gate GATE
PASSED via the POSIX runner. **Windows caveat until a core patch lands:** the
PS gate runner's aggregate verdict is untrusted (flaw filed S443 —
`Run-One` stdout swallow can report a failing command as GATE PASSED; patch
ready in flaws/log.md, blocked by an upstream package refactor mid-flight —
a peer was live there; tree left untouched). Use the POSIX runner for formal
gates meanwhile: `sh .context/core/bin/context-gates run <gate>`.

**Feature:** none

**Next up for the owner:** apply the documented Run-One patch upstream after
the ledger refactor settles → core release → `context-sync update` locally;
B-2026-09-08-1 (next eslint tranche below 53) and B-2026-09-05-4 (the 22
tests/tools Windows failures — the new baseline file gives the gate a green
path meanwhile) remain open. Residue delete-list (B-2026-09-06-5) still
awaits owner confirmation.
