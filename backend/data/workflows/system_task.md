# Workflow: System Task (OS-level actions)

> For OS-level actions where safety and confirmation matter more than
> speed: file deletions, package installs, process management, system
> configuration changes.

## What "done" looks like

The requested system action is:
- Executed safely (no unintended side effects)
- Verified (the action had the expected effect)
- Reported clearly (what changed, what to expect next)

## Constraints

1. **Confirm before destructive actions.** If the action could cause
   data loss (rm, format, DROP TABLE, overwrite), ask for explicit
   confirmation before executing. Don't assume the user meant it.

2. **Show what will happen before it happens.** For destructive or
   irreversible actions, show the command/operation and ask "proceed?"
   before running it.

3. **Verify the effect.** After a system action, verify it worked —
   `ls` after `mkdir`, `cat` after `write`, `which` after `install`.
   Don't claim success without verification.

4. **Respect the safety gate.** The engine's `safety_gate.py` detects
   destructive patterns (rm -rf, sudo, DROP TABLE, etc.). When it
   flags an action, the user MUST confirm before execution. Never
   bypass the safety gate.

5. **Log system changes.** Write significant system changes to
   `.context/system/environment.md` so future sessions know the
   environment has changed (e.g., "installed node 22", "created
   ~/.config/localmind/").

## What you must NOT do

- Don't execute destructive commands without confirmation.
- Don't bypass the safety gate.
- Don't claim a system action succeeded without verifying.
- Don't make system changes the user didn't ask for (no "helpful"
  side effects).

## Learning step

- Did this action change the user's environment? (update
  `.context/system/environment.md`)
- Did the action fail in a way that reveals an environment constraint?
  (write to `.context/flaws/log.md`)
- Did the user's request reveal a system preference? (write to
  `.context/user/preferences.md`)
