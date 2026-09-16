# 2026-09-16 — S005 (Baraka) — ledger-vocabulary sweep of the product tree

## What happened

The agent-memory registries had grown ~1,500 citations inside product files over
hundreds of sessions — ADR numbers, bug IDs, "Session NNN" references and
`.context_ledger/` paths embedded in code comments, docstrings, test names, CSS
blocks and even the app's own prompt data. For anyone reading only the product
repo those pointers dangle: nothing in the shipped code says what `ADR-40` or
`B-2026-08-25-1` resolves to. The protocol requires stripping them on sight; at
this scale each strip needs judgment, so this session did the whole product
runtime surface by hand, line by line.

Method, per the supervisor's directive: read each citation in its context, then
rewrite the comment so the plain reason survives. No scripted bulk transform.
Where a citation lead was pure decoration the pointer was deleted and the
sentence capitalized; where it carried the reason it was replaced by the reason
in words — "per ADR-53" → "(parent-only scope)", "the F4 verifier" → "the
post-execution verifier", "B-2026-08-30-17 Phase 2" → a direct statement.
Live-trace evidence stayed: provider names, models, timings, transcripts.
Comments, docstrings, test titles and prompt data — **zero behavior change**.

## What is clean now (residual-citation count outside the exempt files)

- `backend/src` (every `.py`, SQL migrations' comments included after this
  report's follow-up), `backend/data` (app runtime memory + skills + workflows),
  `frontend/src` + `frontend/index.html` + `electron`, `CHANGELOG.md`,
  `localmind.md`, `scripts/` (three ledger-service scripts were *fixed
  structurally* instead of exempted: the conflict-marker checker and CI now
  take the memory dir as an argument; the suite-runner reads its key path from
  `LM_BANKOFAI_KEY_FILE`).
- Two test files renamed out of the ADR-tag class:
  `test_thinking_policy_adr41.py` → `test_thinking_policy.py`,
  `test_adr32_fail_fast.py` → `test_fail_fast.py` (live import repointed;
  `pyproject.toml` comment updated).

Documented exemptions (now recorded in `overrides/rules.md`): `AGENTS.md` and
`CLAUDE.md` are generated agent-entrypoint digests whose job IS to point at the
protocol — their lint hits are expected noise; `# noqa: S603`-style ruff codes
are rule IDs, not session codenames; and `tests/storage/test_db.py`'s
`"Session 1 message"` fixture strings are round-tripped app data.

## What remains for the next session (backlog B-2026-09-15-1 stays open)

~540 citation lines remain in the dev-only surface: `tests/` (~384, mostly test
docstring leads — the same mechanical class already cleared in 120 files),
`docs/` (~95 — design notes whose body text cites ADRs mid-prose; needs
sentence-level judgment), and `scripts/` live-test harness headers (~50).
Method that worked: grep each file's citation lines with context, build a
per-file exact-replacement table, verify counts, compile, residue-grep to zero.
Run `ledger-mem lint --tree` after to confirm.

## Cost of the session, honestly

Two process failures, both logged: the first long batch nearly shipped as a
blind-regex transform (rejected by the supervisor mid-session; retired after it
demonstrated real corruption on `demo.py`), and one `git commit` without a
fresh staged-set review swept a peer session's closeout files into a product
commit (b49d16d1). The correction is recorded in the event trail and the peer's
bookkeeping landed intact. After that the sweep ran in its own worktree — the
shared-checkout trap the office protocol warns about is real and fired twice.

Gate status: recorded in the session entry (pre-commit + full exit CI on the
merged tree).
