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
│   └── log.md           # append-only project-level friction (code, env, deps)
├── flaws/
│   ├── README.md        # what goes here vs inefficiencies/ — the two-surfaces rule
│   └── log.md           # append-only workflow/protocol friction — flows to the package repo
└── secrets/             # LOCAL-ONLY — self-gitignored, never tracked, never travels
    ├── .gitignore       # ignores everything here except itself + the README
    └── <slug>           # one secret per file: line 1 = value, lines 2+ = notes
```

Every file agents write to carries its entry template in an HTML
comment — at the top of the file itself, or in its directory's README
(`reviews/`, `secrets/`). Read the template before writing; don't
invent formats.

## Two surfaces — know which one you're on

Every repo managed by this protocol has **two surfaces**. An agent
edits one or the other — never both in the same commit — and must know
which one it's on at all times.

1. **The project** — product code, docs, tests, config. Commits use
   normal prefixes (`fix:`, `feat:`, `docs:`). Friction with the project
   (its code, toolchain, environment, dependencies) goes in
   `inefficiencies/log.md`.
2. **`.context/`** — this directory. Agent memory. Commits use
   `chore(context):`. Friction **with the `.context/` system or the
   protocol itself** (a rule that's ambiguous, a step that's missing, a
   template that's confusing) goes in `flaws/log.md`.

If you're editing a file under `.context/`, you're in **memory mode**.
If you're editing anything else, you're in **project mode**. The
protocol's 19 steps apply to both, but the commit prefix and the
friction-logging destination differ. When in doubt: "Am I editing the
project's product, or am I editing the agent's memory of the project?"

## Rules (for agents and humans)

1. **Read before you work.** Agents read this directory at session start
   (sessions → current task → backlog → flaws → inefficiencies → decisions)
   and update it at session end.
2. **Append-only logs are append-only.** `agents/sessions.md`,
   `inefficiencies/log.md`, `flaws/log.md`, `tasks/backlog.md`, and
   `plans/decisions.md` never lose entries. Corrections are appended,
   never edited in. **Exception — exact duplicates:** byte-identical
   entries (same session ID, same date, same content) may be removed to
   deduplicate. When you remove a duplicate, leave a one-line note in
   its place: `Removed duplicate Session N entry (byte-identical to the
   entry above).` This keeps the log clean without erasing history.
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
6. **Friction logging is mandatory — and split by surface.** Project
   friction goes in `inefficiencies/log.md`; workflow/protocol friction
   goes in `flaws/log.md`. Both logs are append-only and honest. See
   `flaws/README.md` for the split rule.
7. **Flaws flow to the package.** `flaws/log.md` is the source of truth
   inside this project. Periodically — or when a pattern repeats — the
   flaws here are back-ported to the protocol package at `TisoneK/.context`.
   When a flaw is fixed in the package, append a "Fixed in package" line
   to the entry here; don't delete the original.
8. **Verify before trusting.** Entries reflect what was true when written.
   If the codebase disagrees, the codebase wins — append a correction.

## File modes at a glance

| File | Mode |
|---|---|
| `agents/sessions.md` | append-only |
| `inefficiencies/log.md` | append-only (project friction) |
| `flaws/log.md` | append-only (workflow/protocol friction) |
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
