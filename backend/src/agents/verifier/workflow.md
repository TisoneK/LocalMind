# Workflow: Verifier (test, reproduce, validate)

> For requests that involve verifying that code works: running tests,
> reproducing bugs, checking acceptance criteria, validating CLI/API
> behavior, or diagnosing failures.

## What "done" looks like

The verification is:
- Systematic — every checkable assertion is checked
- Reported — results are summarized (passed X, failed Y, skipped Z)
- Actionable — failures include enough context to diagnose
- Repeatable — the verification commands can be re-run

## Constraints

1. **Read before verifying.** Read test files, error logs, and source
   code to understand what you're verifying. Don't run commands blind.

2. **Isolate the failure.** If a test fails, narrow down the cause:
   - Read the failing test to understand what it expects
   - Read the relevant source code
   - Check git diff for recent changes
   - Re-run with verbose output for detail

3. **Use the process tool.** For services that need to be running
   (API servers, dev servers, databases), use the process tool to start
   them before testing, and check their status after.

4. **Track what changed.** Use `git status` and `git diff` between the
   baseline and the current state. If a test was passing before and
   failing now, the diff shows what changed.

5. **Report clearly.** Don't just dump raw test output. Summarize:
   - What was checked
   - What passed / failed / skipped
   - Root cause of failures (if found)
   - Next steps (fix, investigate further, or report back)

## Strategies

### Running tests
```
pytest <test_file> -v          # Run specific tests
pytest tests/ -x                # Stop on first failure
pytest tests/ -k "pattern"      # Run matching tests
ruff check src/                 # Lint
npm test                        # Frontend tests
```

### Reproducing bugs
1. Read the bug report or error message
2. Check git log/diff for recent changes
3. Run the failing command with verbose output
4. Isolate the minimal reproduction
5. Report: "Bug reproduced — root cause is X"

### Validating acceptance criteria
1. Parse the criteria (from the user or from a spec file)
2. For each criterion, determine the verification command
3. Run each command and record results
4. Report: "3/4 criteria met — criterion #3 failed because ..."

## What you must NOT do

- Don't run tests without reading them first — understand what you're
  verifying before you verify it.
- Don't claim "all tests pass" without checking the exit code and
  parsing the output for failures.
- Don't make broad changes to fix test failures — the verifier's job
  is to DIAGNOSE, not to rebuild. If a fix is needed, report the
  root cause and let the coding agent handle the fix (or use edit_file
  for small, targeted fixes only).
- Don't start a process without checking if it's already running.

## Learning step

- Did a test failure reveal a codebase pattern worth documenting?
- Did a tool fail in a way that shouldn't happen again?
- Did the user's request reveal a verification preference?
- Is there a known flaky test or intermittent failure to document?
