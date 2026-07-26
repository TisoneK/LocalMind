# Workflow: Error Recovery (when a step fails)

> For when a tool call, model call, or generation step fails. This is
> the workflow that prevents silent hangs and swallowed exceptions —
> the root cause of nearly every bug found in Sessions 21–27.

## What "done" looks like

The user sees one of:
- A successful retry (the error was transient)
- A partial result with an explanation of what failed and what succeeded
- A clear error message explaining what went wrong and what they can do

The user NEVER sees:
- A silent hang ("Thinking..." forever with no output)
- A dead UI with no indication of failure
- A swallowed exception that falls through to an unrelated code path

## Constraints

1. **Fail loudly, not silently.** If a tool or model call fails, surface
   the error to the user — don't catch it and fall through to a default
   path that produces an unrelated response.

2. **Retry once for transient failures.** If the error is a timeout,
   connection reset, or rate limit, retry once. If it fails again,
   surface the error. Don't retry indefinitely.

3. **Degrade gracefully.** If a step fails but partial results exist,
   deliver the partial results with an explanation — "I found 3 of 5
   sources; here's what I have" is better than silence.

4. **Never hang.** Every step must have a timeout. If the timeout fires,
   surface an error message — don't let the UI sit dead.

5. **Log the failure for learning.** Every error that reaches the user
   should also be written to `.context/flaws/log.md` so the system
   learns what went wrong and can avoid it next time.

## What you must NOT do

- Don't catch exceptions with `pass` or empty `except` blocks.
- Don't fall through to an unrelated code path when a step fails.
- Don't retry more than once for the same error.
- Don't leave the UI in a "Thinking..." state indefinitely.
- Don't hide errors from the user — they need to know what happened.

## Learning step (mandatory for this workflow)

- Write the failure to `.context/flaws/log.md` — what failed, why,
  and what was learned. This is the feedback loop: if the same failure
  happens twice, the flaw log wasn't consulted or the fix wasn't
  applied.
- If the failure reveals a systematic issue (e.g., "this provider
  always returns too many results"), write a workflow constraint to
  prevent it next time.
