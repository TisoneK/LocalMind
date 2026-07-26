# Workflow: Coding (file edits, commands, verification)

> For requests that involve writing code, editing files, running
> commands, or building/verifying changes. This is LocalMind's
> primary use case on a developer's machine.

## What "done" looks like

The requested change is:
- Written to the correct file(s)
- Syntactically valid (no broken code)
- Verified — either by running tests, type-checking, or at minimum
  confirming the file was written correctly
- Explained briefly — what changed and why, not a wall of code

## Constraints

1. **Read before writing.** Always read the file you're about to edit
   so you understand the existing structure, conventions, and context.
   Never blind-write.

2. **Verify after writing.** If you wrote code, run the appropriate
   verification: `pytest`, `ruff check`, `tsc`, `eslint`, or at
   minimum `cat` the file to confirm it was written. Don't claim
   success without verification.

3. **Use the workspace state.** The engine injects `git status` and
   `git diff` into your context every turn (ADR-5). USE IT — check
   what changed, catch errors, verify your edits landed correctly.

4. **Follow existing conventions.** Match the codebase's style —
   naming, formatting, import order, test patterns. Don't impose
   a different style.

5. **Small, verifiable changes.** Prefer multiple small edits with
   verification over one large edit. If something breaks, small
   changes are easier to debug.

## What you must NOT do

- Don't blind-write files without reading them first.
- Don't claim success without verifying the change landed.
- Don't ignore test failures — surface them, don't hide them.
- Don't make destructive changes (deletions, overwrites) without
  explicit confirmation from the user.

## Learning step

- Did this edit reveal a codebase convention worth remembering?
  (write to `.context/codebase/architecture.md`)
- Did a tool fail in a way that shouldn't happen again? (write to
  `.context/flaws/log.md`)
- Did the user's request reveal a coding preference? (write to
  `.context/user/preferences.md`)
- Is there a bug or known issue in the codebase that future sessions
  should know about? (write to `.context/codebase/known_bugs.md`)
