Protocol floor (re-injected by ledger-guard every turn - it survives context compaction):
- Check in on the roster BEFORE the deep read; keep your row's Status/detail current; clock out (remove your row) only when actually leaving.
- Before each next action: `ledger-gates checkpoint`. Before each commit: stage, then `ledger-gates run pre-commit`; the git hook refuses a commit whose staged tree has no fresh pass.
- Never read a gate through `| tail`/`| head` or in an `&&` chain behind a pipe - read the verdict line. A red gate is a stop, not noise.
- Two surfaces: commit project files and `.context_ledger/` memory separately; never `git add -A` across both. Never write under `.context_ledger/core/`.
- Append-only logs (sessions.md, flaws/log.md, decisions.md): re-read the file tail first, append, never edit a past entry.
- Corrections, flaws and decisions are recorded when they happen, not when asked. Keep `office/tasks/current.md` true.
- Identity: your check-in commit registers your codename; every commit gets a `Ledger-Session:` trailer. If several agents are live in this checkout, prefix commits with `LEDGER_SESSION=S<NNN>`. Push-check (pre-push + CI) rejects mixed-surface commits and edited append-only logs.
- No secret values in tracked files. Commit AND push; a user reminder to push is a logged failure.
