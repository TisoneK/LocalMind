# Current Task

**Status:** IDLE — Session 380 closed **B-2026-08-23-32** (user's pick): file diffs now emit for ANY write path (file_write included), shell writes steered to be last-resort.

## Session 380 outcome

- **File diff for any write (`008995c`):** the DiffBlock / FilePreviewDialog Diff mode previously only filled from `edit_file` metadata hunks. Now the agent loop snapshots the file's pre-write content before dispatch and, after a successful `file_write`, computes unified-diff hunks from snapshot + landed content and emits the same `file_diff` obs event — wired into the single-tool file_write branch AND the batch `_dispatch_single` path. New files → all-added; overwrites → exact change; unchanged → no event.
- **Prompt steering:** "shell writing to a file is the LAST RESORT — prefer file_write/edit_file; redirection only when they can't express the change." Budgets bumped +200–300/execute intent (justified).
- **Open decision:** part 3 "store stats?" — LEFT OPEN, ask the user before recording write stats. Shell-redirection diff detection scoped out (shell tool can't say which file a command rewrote).
- **Verification:** backend 2490 passed / 2 skipped; frontend useLocalMind + FilePreviewDialog suites green.
- **Next:** continue the backlog one item at a time. Top candidates: **B-2026-08-23-8** (goal-driven agent), **-33** (op permissions), **-34** (chat modes), **-35** (never-rude declines), or the quick UI wins (-21 time formatting, -22 token short-form, -26 ⋮ panel overflow). Pre-existing untracked trace residue at `backend/Dev/` + `backend/scratch/` left untouched.