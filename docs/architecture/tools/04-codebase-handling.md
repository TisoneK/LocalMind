# 04 — Codebase Handling

## Default assumption

When a user hands LocalMind a folder containing a codebase, it is treated
as a **Git repository by default** — even if the user doesn't say so.

Rationale: most developers work in repos. A folder named `localmind/` with
source files inside implies repo conventions. Treating it as a plain folder
and ignoring structure, `.gitignore`, or commit readiness would produce
outputs the user can't use directly.

Override: if the user explicitly says "treat this as a plain folder", or the
folder has no recognisable repo structure (no `.git/`, no common config files),
fall back to plain-folder behaviour.

## Safe-write pattern for code

LocalMind follows the same safe-write pattern that IDEs use (VS Code, Vim,
IntelliJ):

```
1. Copy original → ~/LocalMind/<project>_temp/
2. Apply all changes to the temp copy
3. Verify temp (no broken imports, syntax errors where detectable)
4. Present diff/summary to the user
5. Replace original only on user confirmation
6. Clean up temp
```

This protects against:
- Corruption if the write is interrupted
- Partial overwrites
- Silent changes the user didn't review

## No silent renames or restructuring

LocalMind **never** renames, moves, or restructures files or folders without
explicit instruction from the user. This applies to:

- File names
- Directory names
- Import paths
- Package structure
- Config file locations

Rationale: renaming breaks imports, configs, CI pipelines, and the user's
mental model of their own project. Even a "helpful" rename is destructive
if the user didn't ask for it.

## Code vs document file handling

Code files follow different rules than document files (see `03-file-handling.md`):

| | Code files | Document files |
|---|---|---|
| Timestamp rename | Never | Always (unless user named the output) |
| Original preserved | Via temp copy + confirmation | Via timestamp rename |
| Safe-write pattern | Yes (temp → diff → confirm → swap) | No (scratch → copy-back) |
| Treated as repo | Yes, if folder looks like a codebase | No |

## Repo-aware output

When working on a codebase, outputs should be pull-ready:

- Changes are coherent and scoped to the task
- No unrelated files modified
- Diff/summary presented before any write-back
- Integration notes included (what changed, why, what to test)

## What "pull-ready" means

An output package is pull-ready when:
1. It can be applied to the repo without manual fixup
2. It does not break existing tests or imports
3. It is scoped to exactly what was asked — no extra changes
4. It includes a short explanation of what changed and why

## Temp directory naming

Temp copies live in `~/LocalMind/<project-name>_temp/`. If a temp directory
already exists from a previous run (e.g. a crash), LocalMind surfaces a
warning and asks the user whether to resume or start fresh — it never
silently overwrites an existing temp copy.

## Implementation status

| Behaviour | Status |
|---|---|
| Repo-default assumption | Documented — enforcement in orchestrator/planner prompt pending |
| No silent renames | Enforced in `file_writer.py` (`resolve_write_path` + no-rename-for-code rule) |
| Safe-write temp pattern | Documented — implementation in `tools/file_writer/safe_write.py` planned (see `02-tool-decomposition.md`) |
| Diff/summary before confirm | Planned — part of `tools/file_writer/diff.py` |
| Pull-ready packaging | Partial — orchestrator produces structured output; formal packaging step planned |
