# Session 5 Review — setup (core 2.2.0 + dev environment)

**Kai (S005), 2026-10-27 — task: "Pull latest and setup."**

## What happened

The checkout was pulled to the latest main and brought to a fully working
development state. The vendored protocol core was updated 2.0.4 → 2.2.0
(from the local package source at `../context-ledger`, same MAJOR), the
generated entry points were refreshed to match, and the new guard
tooling was installed. Both runtime environments were rebuilt and the
verification stack was proven end to end.

## Changes

- **Core 2.2.0** (`24377c08`): 18 files — notably the new `ledger-guard`
  tool (sh/ps1/cmd), its CI template, and the guard-reminder template.
  `ledger-sync verify` green on both PowerShell engines.
- **kickoff.md** (`c3fb0636`): Phase 1 now includes the guard-install
  step; Phase 2 is sync-first; exit step 6 includes `ledger-guard release`.
- **AGENTS.md / CLAUDE.md** (`cc670da5`): regenerated from the 2.2.0
  templates. The project's CLAUDE.md had silently missed the 2.0.3
  restorations and 2.1.0 sync wording — both now current.
- **.claude/settings.json** (`5469ad22`): Claude Code hooks (session-start
  and per-turn protocol reminder, tool-check), from `ledger-guard install`.
- **STATE.md + core.lock** (`5a62dc43`): digest regenerated; the lock
  records the 2.2.0 install.

## Environment

- Root `npm install` green (workspaces: frontend + electron).
- **Backend venv rebuilt on Python 3.13.1** with an editable + dev install.
  The first build used the machine-default Python 3.14.2, and pip resolved
  a cp313 `pydantic_core` build into it — `import pydantic_core` failed
  (`No module named 'pydantic_core._pydantic_core'`) and every pytest
  collection halted. `py -3.13 -m venv backend/.venv` + reinstall fixed it.
  Standing note: `python` on this machine is 3.14; the dev venv must be 3.13.

## Verification

- pre-commit gate: PASSED (tsc, ruff, conflict-marker check, backlog check).
- pytest smoke: `tests/api/test_config_adapter.py` 14/14.
- vitest: **619/619 (59 files)**.
- exit gate (`ledger-gates run exit`): result recorded in the session log.

## Process notes

- The pre-push guard rejected the first entry-point push for mixing
  surfaces (AGENTS/CLAUDE + kickoff in one commit); split into two
  surface-pure commits and re-pushed. The guard works as designed.
- The collaboration light path (claim → release) was emitted at close;
  the claim should have been emitted before the first edit — noted in the
  session entry so the next session does it at the door.

## Open items

- Full exit-gate pytest run has Windows-baseline failures counted as
  documented (see `scripts/pytest-baseline.txt`); anything new is a
  regression for the next product session to pick up.
