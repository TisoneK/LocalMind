---
name: git-workflows
description: Git best practices for working in this repo — clean commits, protocol-safe .context updates.
---

# Git workflows

## Commit discipline

- **One logical change per commit.** Split product code and `.context/`
  memory into separate commits: product code uses normal prefixes
  (`feat(tools):`, `fix(agent):`), `.context/` uses `chore(context):`.
- Commit messages follow Conventional Commits: `type(scope): summary` +
  optional body. Reference the backlog id in the summary
  (e.g. `feat(tools): delegate_parallel — parallel delegation fan-out`).
- Before committing: `git status --short` to confirm exactly what's staged;
  never `git add -A` blindly into a commit you can't describe.

## Protocol-safe memory edits

- `.context/memory/` append-only files (`agents/sessions.md`,
  `tasks/backlog.md`, `plans/decisions.md`, `flaws/log.md`,
  `inefficiencies/log.md`) are append-only: add at the bottom, never edit or
  delete past entries.
- Never commit secrets. Values go only in `.context/memory/secrets/`
  (self-gitignored).
- After committing product code + `.context`, sync with
  `git pull --ff-only && git push` and confirm the tree is clean.

## Branch hygiene

- Work on `main` for these sessions (the project is a solo local-first repo).
- `git log --oneline -3` before a push to confirm what's going out.
