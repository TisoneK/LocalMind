# .context/ — Agent Memory for This Repo

This directory is the project's institutional memory for AI agents. It is
**committed to git** and travels with the repo: every agent, on every
machine, with any model, pulls the same context — who worked on what, on
which system, what's open, what's decided, and what went wrong before.

The repo's docs (`README`, `docs/`) describe the **product**.
This directory describes the **process**.

## Structure

```text
.context/
├── README.md            # this file — structure + rules
├── system/
│   ├── environments.md  # machines/sandboxes agents have run on (OS, toolchain versions, quirks)
│   └── ai-models.md     # registry: which agents + models have worked on this repo
├── user/
│   ├── identity.md      # who the user is (name, git identity, role on the project)
│   └── preferences.md   # how the user likes things done (commit style, tone, review depth)
├── workflows/
│   └── active.md        # workflow currently in force (protocol edition, scope, push policy)
├── agents/
│   └── sessions.md      # append-only log — one entry per agent session
├── reviews/
│   └── YYYY-MM-DD-review.md  # session review reports (see reviews/README.md)
├── tasks/
│   ├── current.md       # the task being worked on right now (one at a time, overwrite)
│   └── backlog.md       # append-only open items for future sessions
├── plans/
│   └── decisions.md     # append-only ADR-style architectural decisions
├── inefficiencies/
│   └── log.md           # append-only problems agents faced — mandatory honesty
└── secrets/             # LOCAL-ONLY — self-gitignored, never tracked, never travels
    ├── .gitignore       # ignores everything here except itself + the README
    └── <slug>           # one secret per file: line 1 = value, lines 2+ = notes
```

Every file agents write to carries its entry template in an HTML
comment — at the top of the file itself, or in its directory's README
(`reviews/`, `secrets/`). Read the template before writing; don't
invent formats.

## Rules (for agents and humans)

1. **Read before you work.** Agents read this directory at session start
   (sessions → current task → backlog → inefficiencies → decisions) and
   update it at session end.
2. **Append-only logs are append-only.** `agents/sessions.md`,
   `inefficiencies/log.md`, `tasks/backlog.md`, and `plans/decisions.md`
   never lose entries. Corrections are appended, never edited in.
3. **Overwrite files are current-state only.** `tasks/current.md`,
   `workflows/active.md`, and the `system/` + `user/` files describe *now*;
   update them in place. History lives in the append-only logs.
4. **No secrets in tracked files — ever.** This directory is committed
   to git. Env var *names* and where secrets live are fine in shared
   files; values belong only in `secrets/`, whose own `.gitignore` keeps
   everything but its README out of git (rules in `secrets/README.md`).
5. **Commit with `chore(context):`.** Context updates are process, not
   product — keep them out of the changelog. One exception: review
   reports in `reviews/` commit as `docs(review):` — they're a
   deliverable, not bookkeeping.
6. **Inefficiency logging is mandatory.** Every session appends what
   slowed it down, honestly. That log is how the next session gets faster.
7. **Verify before trusting.** Entries reflect what was true when written.
   If the codebase disagrees, the codebase wins — append a correction.

## File modes at a glance

| File | Mode |
|---|---|
| `agents/sessions.md` | append-only |
| `inefficiencies/log.md` | append-only |
| `tasks/backlog.md` | append-only |
| `plans/decisions.md` | append-only |
| `reviews/YYYY-MM-DD-review.md` | new file per session |
| `tasks/current.md` | overwrite |
| `workflows/active.md` | overwrite |
| `system/environments.md` | update in place |
| `system/ai-models.md` | update in place |
| `user/identity.md` | update in place |
| `user/preferences.md` | update in place |
| `secrets/<slug>` | local-only — never committed, never travels |
