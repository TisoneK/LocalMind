# Workflow: Safety (check before acting — universal rule)

> Applies to EVERY tool that creates, writes, modifies, or deletes
> something. This is the universal "check state before acting" rule —
> not a per-tool fix. Every tool invocation must verify the target's
> actual state before acting on it, and adapt the plan based on what's
> found. Never act on an assumed or expected state.

## What "done" looks like

Every tool invocation that creates, writes, modifies, or deletes:
- Checked the target's actual state BEFORE acting (not after)
- Adapted the plan based on what was found (not what was assumed)
- Reported what was found + what was done (not just what was done)

## The universal rule

**Before ANY tool invocation that creates, writes, modifies, or deletes
something, you MUST first check whether the target already exists or has
content. Your action must depend on what you find — never on what you
assumed or expected.**

**And before creating anything, check that the creation was asked for.
Files and folders are deliverables, not proof of work: when the task is
to read, summarize, or answer a question about content the user
provided, create NOTHING — the faithful, complete answer IS the
receipt.**

This is a constraint, not a script. You decide the specific check and
the specific action. The constraint is: don't act blind.

## How it applies per tool

### Shell (mkdir, rm, cp, mv, etc.)
- Before `mkdir <path>`: check if `<path>` already exists (dir_explorer
  operation=stat — one bounded read-only call; shell `ls`/`dir` also works).
  - If it doesn't exist → create it.
  - If it exists AND is empty → proceed (or skip, it's already there).
  - If it exists AND is non-empty AND unrelated to your task → do NOT
    dump your work into it. Create a subdirectory instead (e.g.
    `mkdir <path>/hello_world`) and tell the user why.
  - If it exists AND is non-empty AND clearly meant for this task →
    proceed, but tell the user the directory wasn't empty.
- Before `rm <path>`: check if `<path>` exists and what's in it. Never
  delete a directory you haven't listed first.
- Before `cp`/`mv` to a destination: check if the destination exists
  and whether it would overwrite something.

### File tools (file_write, edit_file, file_task)
- CREATE vs MODIFY first: if the user asks you to CREATE a file (a path
  they named, content they described) and nothing suggests it already
  exists, the create IS the check — call `file_write` directly. Do NOT
  probe with file_task/shell first; that burns a round-trip on an
  unambiguous create. The runtime verifies every file_write and reports
  the result; if the target unexpectedly existed, the verification
  output tells you and you adapt from there.
- If the target plausibly ALREADY exists (the user says "update",
  "fix", "add to", or references an existing file) or the request is
  ambiguous → READ it first (file_task), understand what's there, and
  decide: overwrite (with confirmation), append, or write to a
  different path. Never blind-overwrite a file you haven't seen.
- Before `edit_file <path>`: ALWAYS read the file first (this is
  already in coding.md constraint #1, but it's the same principle).
- Before `file_task <path>`: check if the file exists (dir_explorer
  operation=stat, or shell list_files). If it doesn't, say so — don't
  fabricate contents.

### Code execution (code_exec)
- Before executing code that writes to disk: the code should check
  state first (os.path.exists, etc.) — same principle, inside the code.
- Before executing code that modifies shared state (DB, env, registry):
  check the current state first.

### Web tools (web_search, web_fetch, browse)
- Before feeding raw results into the next step: check the SIZE and
  SHAPE of what came back. If web_search returned 5000 tokens of raw
  HTML, that's too large to dump into the model — summarize or chunk
  first. (This is the "check before acting" principle applied to the
  model's context window: check the size before assuming it fits.)
- Before claiming a search answered the question: check that the
  results actually contain the specific data (temperature, price, etc.).
  If snippets are too thin, use web_fetch — don't fabricate.

### Memory tools (memory_op)
- Before storing a fact: check if a similar or conflicting fact already
  exists. If it does, update or note the conflict — don't create a
  duplicate.
- Before recalling: the memory tool handles this, but the principle
  applies: don't assume a fact exists without checking.

## What you must NOT do

- **Don't create what wasn't asked for.** Files and folders are
  deliverables, not proof of work — and an artifact you invented to
  satisfy a checklist is pollution, not evidence. When the task is to
  read, summarize, compare, or answer a question about content the user
  provided, the correct output is the answer itself: create NOTHING on
  the filesystem. A create (file or folder) is legitimate only when the
  user's request names it or unambiguously implies it ("write X to
  notes.txt", "update the config"). If you catch yourself making an
  artifact to "prove" you worked — stop; the receipt for an analysis
  turn is a faithful answer.
- **Don't act blind.** If you're about to create/write/modify/delete
  something and you haven't checked its current state, STOP and check
  first.
- **Don't barrel forward after a "file already exists" or "directory
  not empty" result.** That's the check working as intended — adapt
  your plan, don't ignore the finding.
- **Don't dump work into a non-empty unrelated directory.** If the
  target has existing content that's clearly not yours, scope your
  work into a subdirectory instead.
- **Don't blind-overwrite files.** Read first, then decide.
- **Don't assume the world is in the state you expect.** Verify, then
  act on what's actually true.

## Why this exists

The user asked "Create hello world repo in C:\Users\tison\...\ProjectPhill".
The model:
1. Ran `mkdir ProjectPhill` — FAILED because the directory already existed
   (it contained unrelated files: info.txt, a PDF).
2. Ran `dir ProjectPhill` to check contents — found the unrelated files.
3. Ran `git --version` to check git was available.
4. Hit the iteration limit (was 3, now 8) before reaching the actual work
   (git init, file_write, git commit).

Two process bugs:
- It ran `mkdir` BEFORE checking if the directory existed. The check
  (`dir`) came after the failed `mkdir`. That's backwards — check state
  first, then act on what you find.
- It should have recognized the non-empty directory and created a
  `hello_world/` subdirectory inside it, not barreled forward with
  plans to init a git repo alongside the user's existing files.

Both bugs are the same root cause: the plan assumed a clean, empty
target directory. The model never checked that assumption before acting.
This workflow exists to make "check before acting" a universal rule,
not a per-tool fix discovered one bug at a time.

## Learning step

- Did you find the target in an unexpected state? (write to
  `.context/flaws/log.md` if it reveals a tool/adapter bug, or
  `.context/memory/inefficiencies/log.md` if it reveals an env quirk)
- Did the user's request reveal a preference for how to handle
  non-empty targets? (write to `.context/user/preferences.md`)
- Did a check-before-acting decision prevent a mistake? (worth noting
  in `.context/flaws/log.md` as evidence the constraint works)
