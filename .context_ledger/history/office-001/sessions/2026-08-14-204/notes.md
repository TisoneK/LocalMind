# Session 204 notes — authoritative current time/date handling

## Task

Fix the live trace where `whats the time?` caused a rejected `shell` call with
`Get-Date`, then returned a final answer with the verified August 14 date
corrupted to August 1.

## Findings

- `AgentRuntime` correctly routes the request through the LocalMind
  `ParentAgent → AgentLoop` path.
- The parent prompt did not state the time/date tool rule strongly enough for
  the free-tier model, even though older intent-oriented prompt text did.
- `shell.py` correctly rejects unstructured natural-language/legacy shell
  dispatch, so the `nl_dispatch_removed` result was a contract signal, not a
  shell execution bug.
- The successful `sysinfo` result was followed by another model generation;
  that paraphrase changed `August 14` into `August 1`.

## Implementation

- Strengthened `agents/parent/context_builder.py` with an explicit
  sysinfo-exclusive clock rule and an exact-value authority rule.
- Updated environment guidance in `core/context_builder.py`.
- Added pure helpers in `core/agent/text_tools.py` to recognize narrow current
  time/date/day requests, normalize accidental shell clock calls to sysinfo,
  and extract the exact authoritative sysinfo line.
- Applied normalization in both single and multi-tool paths in
  `core/agent/loop.py`.
- Added a clean terminal response after successful sysinfo for clock queries,
  preserving tool observability while preventing a corrupting paraphrase call.
- Added `tests/core/test_system_query_guard.py` and the Unreleased changelog
  entry.

## Validation

- Focused: 61 passed.
- Full backend: 1748 passed, 2 skipped.
- CI gate: passed — Ruff clean, TypeScript clean, ESLint 0 errors / 64
  existing warnings.
- Product commit: `ef03365`.
- No provider credentials were available/used for a new real-model smoke.
