# Core Changelog

One entry per released core version, newest first. An agent syncing a
project's `.context_ledger/core/` from an older version reads every entry
between the two versions — migration notes live here.

Semver: breaking changes to the `.context_ledger/` spec or the memory layout
bump MAJOR; new features (roles, pitfalls, templates, schema fields)
bump MINOR; wording and fixes bump PATCH.

---

## 0.21.0 — 2026-09-09

**Backlog is a live queue — open work only.** The backlog previously
held completed items as checked-off tombstones (`- [x]`, "don't remove
the line"), so every session re-read fixed work at startup. Completion
history already has a home: `agents/sessions.md` entries, the commits
themselves, and git history (which preserves any removed line).
`designs/feature-scoped-memory.md` had already flagged checked-off
backlog items as unbounded growth.

- **`tasks/backlog.md` reclassified:** no longer in the append-only set.
  Append new items at the bottom; **delete the line** when the item is
  finished or no longer relevant. Never delete a line whose item is
  still open — a `- [ ]` line vanishing without a matching session
  entry is a dropped handoff.
- Both protocol editions updated (Rule 4 file-kinds digest, Step 15,
  memory-tree comment, what-goes-where table, memory Rules 1, Pitfall
  #22, Pitfall #39). Pitfall #39's additions-only diff check now lists
  `backlog.md` as the explicit exemption.
- Templates updated: `memory/tasks/backlog.md` header rewritten;
  `ledger-README.md` tree; `AGENTS.md` digest rule 6; collaboration
  README durable-files note. Repo-level `README.md` and `MVP.md`
  updated to match.
- No tool changes: `ledger-mem`/`ledger-gates` never mechanically
  enforced backlog append-only (the check was prose-only), so no script
  edits. Existing project ledgers keep their checked-off lines until an
  agent deletes them under the new rule — no migration needed; a
  same-major `ledger-sync update` ships the new spec.

**Identity is never inferred — a model match proves nothing.** At sync
start a fresh session inferred "Zola (S455) is ME" from her roster row's
model-ID string matching its own system prompt's model name, and moved
to treat a dirty main checkout as its own uncommitted closeout. Doubly
wrong: the `cf02f3d0-…` UUID it matched on is the ZCode harness marker
shared by every ZCode session (it appears in the S450/S452 sessions.md
entries under glm-5.3-flash), and the model suffix `qwen3.8-flash` also
matches Nia's row (S454). Model strings can never discriminate agents,
and a fresh context can never prove it is a prior session.

- **New check-in bullet + Pitfall #45 in both editions:** identity is
  *claimed* at registration (fresh name + codename `S<NNN>`), never
  *inferred* from a model/harness-string match — model IDs, version
  suffixes, and harness/session UUIDs are fingerprints shared by every
  session on that harness or model. "That row is me" is justified only
  by continuity within your own live context (the re-check-in rule) or
  the user's word; a matching row is a peer's — leave it and its dirty
  checkout (Pitfall #20) alone.
- Threaded through the kickoff check-in, the AGENTS.md digest, the
  collaboration README ("You are a new arrival until you register"), the
  roster template's Model bullet, and both schemas' roster notes
  (duplicate model values are documented as normal).
- No tool changes: `ledger-mem check` already keys roster uniqueness on
  Name + codename, never on model, so duplicate model values never trip
  it. No migration; a same-major `ledger-sync update` ships the new spec.

**Worktrees are rented, not owned — tear down the topology at closeout.**
Collaboration setup was taught everywhere (check-in/mode bullets, the
collaboration README's workspace topology, the kickoff, the digest) and
teardown nowhere: clock-out, Step 15, and the EXIT checklists covered
the roster row, `current.md`, the logs, and the PAT — never the
workspace an agent created. So worktree directories accumulated one per
agent per session, and stale `git worktree list` registrations met the
next session as unexplained, locked paths.

- **Both editions:** a teardown bullet in the collaboration Isolation
  guidance, a Step 15 clock-out sentence, and a new EXIT / end-of-session
  gates checkbox. After the final `release` and integration: remove your
  product worktree (from a clean tree — unexplained changes stop you,
  Pitfall #20) and delete your product branch (`git branch -d` refuses
  an unmerged branch; `git push origin --delete` if pushed).
  `git worktree list` must be clean of your rows before you go.
- The coordination *branch* is the deliberate exception: it is the
  session's event trail, which later agents fetch to continue the
  session — it is not deleted while the session can resume. The
  coordination *worktree* may be removed by the last agent out
  (re-added in one command next session).
- Threaded through the collaboration README ("Teardown — the topology is
  rented, not owned"), the kickoff, and the AGENTS.md digest. No tool
  changes; a same-major `ledger-sync update` ships the new spec.

## 0.20.0 — 2026-09-09

**Additive roster edits — the peer-clobber fix.** On check-in into a
board holding a live peer's row, the arriving agent (LocalMind S449)
answered to the peer's identity instead of creating its own; when
corrected, its replace-style edit anchored on the table body *containing
the peer's row* — the block swap erased the live peer from the board and
was committed and pushed without a diff review (from `flaws/log.md`,
2026-09-09, via LocalMind flaw 86eeaef6). The check-in rule said "add or
update your row" but never stated the edit discipline that makes that
safe on a shared board.

- **Roster edits are additive — your row only** (both editions, kickoff,
  AGENTS.md digest): a live row you didn't write is a colleague's
  check-in, not sample text. Never take a peer's identity (name taken →
  pick another); never let an edit's `old_string` span or include a
  peer's row — the edit tool replaces blocks, so anchoring on the table
  body erases whoever is on it.
- **Diff-review gate for roster edits:** after any roster edit, `git
  diff` must show exactly your own row changed (`+1` on check-in) —
  review the diff before committing. A two-second diff review is what
  the S449 push lacked.
- No tool changes, schema changes, or memory-layout changes — project
  agents pick the rule up from the vendored rules/kickoff/digest text at
  the next same-major `ledger-sync update`.

## 0.19.0 — 2026-09-08

**Resume after clock-out — the ghost-editor fix.** Clock-out (Step 15)
removed the roster row and Step 17 logged the session as soon as "the
main work looks done," yet Pitfall #30 holds that the session is not over
until the user says so. So when the supervisor followed up after wrap-up,
the agent resumed *after* it had already left the board: it kept editing
under the identity it just retired, never re-registered, and peers saw
edits landing from someone who was not in the office (from
`flaws/log.md`, 2026-09-08 user report).

- **Clock-out now means leaving, not wrapping up.** Vacate the board only
  when you are actually leaving; if you expect a follow-up, keep your row
  live and clock out later. Step 15 and the AGENTS.md digest say so
  explicitly and cross-reference Pitfall #30.
- **New resume rule (both editions, kickoff, digest):** if you already
  clocked out and the user brings more work, you have left and returned —
  **check back in before touching anything.** Re-add your row under the
  **same name and codename `S<N>`** (you are the same session) and push it
  as `chore(ledger): <name> (<codename>) checks back in — <task>`. Never
  edit under a retired identity while your row is gone.
- **One `sessions.md` entry per codename `S<N>`, even across a resume.**
  Extend your existing Step 17 entry (commit range, outcome, open items);
  never append a second `Session N`.
- **`ledger-mem check` gains a duplicate-session audit** (POSIX +
  PowerShell): two `Session N` entries for one codename warn (never fail)
  — a resumed session re-logged instead of extending. Merge them. The
  PowerShell port mirrors the POSIX logic but was not runtime-verified on
  Windows this release (no `pwsh` on the authoring host).

## 0.18.1 — 2026-09-08

**Cross-platform `rename` fix.** The 0.18 `rename` command's entry-point
sweep used `sed -i 's|…|…|g' file`, which only works on GNU sed (Linux,
Git Bash on Windows). On BSD/macOS sed, `-i` consumes the next argument
as a backup suffix and the filename is then parsed as a sed script — so
every sweep errored (`sed: ... invalid command code .`) and the
generated entry points (`README.md`, `kickoff.md`, `.gitattributes`,
`AGENTS.md`, `CLAUDE.md`) were left with stale `.context/` references
after the `git mv` succeeded.

- **Fix.** The sweep now rewrites through a temp file (no `-i`) using
  POSIX-only regex — and drops the GNU-only `\b` word boundary. It runs
  identically on GNU and BSD sed: Linux, macOS, and Windows Git Bash.
  `.context/` is rewritten first; bare `.context` is matched only at a
  non-word/non-slash boundary or end of line, so an existing
  `.context_ledger` is never double-renamed to `.context_ledger_ledger`.
- **Scope.** `rename` (POSIX-sh tool) only; PATCH. No spec, layout,
  memory, or behavioral change on GNU platforms — the sweep now simply
  also works on macOS. The PowerShell port was already correct.
- **Who needs it.** Anyone finishing the 0.18 `.context/` →
  `.context_ledger/` migration on macOS. If you already ran `rename`
  there, the `git mv` worked but the five entry-point files may still
  say `.context/` — re-run `rename` against this core, or fix them by
  hand. Memory files were never touched by the sweep regardless.

## 0.18.0 — 2026-09-08

**Context Ledger.** The package went public and took its real name. The
repo is `TisoneK/context-ledger` (was `TisoneK/.context` — GitHub
redirects the old URL), and every project's two-zone directory is
renamed `.context/` → **`.context_ledger/`**. The tools rename with it:
`context-sync` → **`ledger-sync`**, `context-gates` → **`ledger-gates`**,
`context-collab` → **`ledger-collab`** (+ `ledger-collab-check`),
`context-mem` → **`ledger-mem`**, `context-history` → **`ledger-history`**.
Schemas rename to match: `ledger-schema.md` + `ledger.schema.json`,
`ledger-README.md`.

- **Breaking, shipped as a 0.x MINOR — deliberately.** The directory and
  tool names are part of the spec, so this would be a MAJOR under 1.x
  discipline; while the project is pre-1.0 it ships as a MINOR. Safe
  because the 0.18 tooling detects **both** layouts: a project that
  updates without renaming keeps working, and `rename` is the explicit
  finishing step. Memory files, formats, and the two-zone model are
  unchanged — this is a rename, not a redesign.
- **Migration — three commands, existing project:** from the project
  root, with the package reachable:

  ```bash
  sh .context/core/bin/context-sync update    # same-MAJOR: applies; its self-re-exec
                                              # errors — expected, core 0.18 is in place
  sh .context/core/bin/ledger-sync migrate    # new tool: backfill + relock + verify
  sh .context/core/bin/ledger-sync rename     # git mv .context -> .context_ledger + sweep
  ```

  `rename` `git mv`s `.context/` to `.context_ledger/`, sweeps the
  generated entry points (`README.md`, `kickoff.md`, `.gitattributes`,
  root `AGENTS.md` + `CLAUDE.md`), relocks, and verifies. Requires a
  clean tree. It prints the one manual step: sweep stale `.context/`
  *instruction* references in your memory files (historical log entries
  stay as written — append-only). Commit as `chore(ledger): rename
  .context/ to .context_ledger/ (core 0.18)`.
- **Compat.** Mode detection accepts `.context/` and `.context_ledger/`,
  so `status`/`verify`/`update`/`migrate` all run in a legacy project;
  `rename` finishes the job. Package-side `harvest` reads both layouts
  too. Full recipe: `MIGRATION.md`.
- **Sources.** `update`/`migrate` look for the package clone at
  `../context-ledger` first, then legacy `../context`, then
  `../.context` — or set `LEDGER_PKG`/pass a path as before.
- **Windows.** Every `.cmd` launcher and `.ps1` port carries the new
  names; the `rename` command is ported too.
- **Public repo.** The package repo is now **public** — cloud bootstraps
  no longer need a package PAT (project PATs unchanged). The docs'
  private-repo claims were updated.

---

## 0.17.0 — 2026-09-08

**Check-in is universal — the board shows who is in the office.** The
roster was signed only inside Peer Collaboration Mode, and the solo
decision keyed on `tasks/current.md` being idle — a value that stays
"idle" on the shared branch until the first agent's wrap-up commit. So
every arriving agent saw an empty board, concluded it was alone, and ran
a solo protocol that never signs in and never claims a worktree: N
agents, N parallel solo sessions, unattributable uncommitted changes
(from `flaws/log.md`, 2026-09-08 user report).

- **Check-in moved to Step 3 of every session, solo included:** pick a
  real name, add your row to `memory/agents/roster.md`, and **push it
  immediately, before any product work** (`chore(ledger): <name>
  (<codename>) checks in — <task>`). Presence is real-time, not
  wrap-up-time; a rebase on that push is itself a signal that a peer
  checked in concurrently.
- **The board is on every read order** (both editions, kickoff Step 2,
  AGENTS.md digest, schema reading order) and drives the mode decision:
  **solo = no declared session/issue AND no live roster row you didn't
  write AND `current.md` idle.** A live row you didn't write means a peer
  is here — declare or join a session, take an isolated worktree, emit a
  `note` + `claim`; never run a solo protocol into a peer.
- **Clock-out at Step 15:** remove your row in the closing memory
  commit. The board answers "who is in the office *now*"; who was on
  duty *when* stays in the append-only duty log (`agents/sessions.md`)
  and the roster file's own git history — check-in opens the shift,
  clock-out closes it. Nothing historical is deleted by clocking out.
- **`ledger-mem check` audits board vs duty log** (POSIX + PowerShell):
  a roster row whose `Session N` is already in `agents/sessions.md`
  warns "logged itself done without clocking out". Warn-only, exit 0.
- Collaboration section now opens with "Collaboration is opt-in;
  **presence is not**"; the collaboration-light-path step 0 references
  the Step 3 check-in; dirty-tree STOP / unexpected-changes guidance in
  both editions says to check the roster and events before
  investigating — it may be a teammate's claim, not drift.

**Migration:** none — `roster.md` already exists in every 0.15.0+
project; existing empty boards behave exactly as before until the first
session checks in. Older projects: `ledger-sync migrate` installs
`roster.md`.

**The ports' self-referential help matches the `.cmd` convention.**
`ledger-sync.ps1`'s printed help (what `ledger-sync.cmd` shows with no
arguments) and `ledger-collab.ps1`'s header examples still told Windows
agents to run `pwsh -File .context_ledger/core/bin/...ps1` — which an
execution-policy-locked machine blocks. Both now show the documented
no-setup form (`ledger-sync.cmd <cmd>`). Text-only change, line counts
preserved (the sync help is sliced from the file header); manifest
regenerated.

## 0.16.0 — 2026-09-06

**Sync is one command and fill again.** Each release since 0.9.x added files
or zones that only `update`'s versioned backfill installed — and because that
backfill lived in the *old* script that runs first, migrating an old project
meant running `update` twice, guessing about CRLF, and hand-creating new
zones. This restores the old simplicity.

- **New `ledger-sync migrate` (POSIX + PowerShell + `.cmd`):** the
  one-command bring-current. It updates the core to the newest reachable
  same-MAJOR version, then **backfills every missing zone/file** (`history/`,
  `archive/`, `CLAUDE.md`, `.gitattributes`, `roster.md`, `history.conf`,
  `GROUP`, …), LF-normalizes, relocks, and verifies — then prints the single
  manual step: fill the project facts. Idempotent; safe to re-run; doubles as
  a repair command for a project missing any current file.
- **The backfill is factored out** (`backfill_project`) as the one definition
  of "what a fully-migrated project contains" — adding a new template file to
  that list is all it takes to teach migration about it. Both `update` and
  `migrate` go through it.
- **`update` now fully migrates in one run** (from this version on): after
  the core swap it re-execs the *just-installed* script's `migrate
  --backfill-only`, so the new script — which knows every new file — does the
  backfill. No more "run update twice."
- **The PowerShell `update` caught up:** it had only ever backfilled README /
  `.gitattributes` / `CLAUDE.md`, missing the `history/`, `archive/`,
  `roster.md`, `GROUP`, and `history.conf` a 0.13+ project needs. It now
  installs all of them through the shared backfill.
- **MIGRATION.md rewritten** to lead with the one-command path for any
  0.2.0+ project (with the old-script fallback), keeping the pre-0.2.0
  flat-layout `git mv` steps as a clearly-marked special case that ends in
  the same `migrate`.

**Migration to 0.16.0 itself:** from an older project, `update` once (installs
this script) then `migrate` — or just `migrate` if the vendored script already
has it. From 0.16.0 forward, one `update` (or one `migrate`) is enough.

## 0.15.0 — 2026-09-06

**Agents are named coworkers, not "peers".** Collaboration works, but agents
identified as "peer" or a bare `S427`. Now each agent picks a real name and
the team reads as people in a workplace — with the human as the supervisor.

- **New `agents/roster.md`** (update-in-place, current-group-scoped): a team
  board, one row per person — a chosen human **Name**, a **codename**
  `S<NNN>` (session number), the **model**, and one line on what they're
  doing. An agent adds its row at session start and presents itself by that
  name everywhere ("John (S427)"), in events and when reporting to the
  supervisor.
- **Name and codename are each unique within the group.** `ledger-mem
  check` now validates the roster and flags a duplicate name or codename
  (there is only one John on the team at a time) — the same update-in-place
  discipline as the other registries.
- **The roster rotates with the group.** `ledger-history close` captures
  the closed group's roster into `history/group-<NNN>.md` and resets a fresh
  empty roster for the new group.
- **Docs reframed to the workplace metaphor:** the collaboration README (new
  "Who you are — pick a name" section), both protocol editions (a step 0 in
  the light path), the AGENTS digest, and the schema now say: pick a name,
  present yourself by it, the human is the supervisor. `--agent` takes your
  name, so the chatter feed reads "John: ...".

**Migration from 0.14.x:** `update` installs `agents/roster.md` if absent.
Existing agents just start adding rows; nothing else changes. The `.ps1`
port changes (roster check + roster reset) are ASCII-clean but owe the usual
Windows runtime pass.

## 0.14.0 — 2026-09-06

**Windows verified for real: three latent port bugs fixed, `.cmd`
launchers remove the execution-policy hurdle.** 0.13.1 made the `.ps1`
ports *parse* under Windows PowerShell 5.1; this release makes them *run*.
Every port was executed end-to-end against a bootstrapped fixture project
(registry hygiene, the full three-zone history lifecycle, the
collaboration trail, the gates), which surfaced defects a parse-level fix
cannot catch.

- **`ledger-collab-check.ps1` crashed on every invocation.** It assigned
  the automatic `$args` variable (a no-op under `Set-StrictMode`) and its
  `if`-expression `@()` unwrapped to `$null`, so the argument loop died on
  `$null.Count`. The array is now built by direct assignment. 0.9.1 had
  shipped this file as "Windows-verified"; only its parse had ever been
  exercised.
- **`ledger-history.ps1 close` / `gc` crashed when run without flags.**
  `$RestArgs.Count` on a `$null` `ValueFromRemainingArguments` parameter
  is fatal under strict mode. Both such parameters now default to `@()`
  (`ledger-mem.ps1` hardened the same way).
- **`ledger-history.ps1` never archived anything.** It passed a
  `C:\...` archive path to `tar`, which GNU tar (MSYS, often first on
  PATH) parses as remote *host* `C` ("Cannot connect to C: resolve
  failed"). The roll now runs tar from inside `history/` with a relative
  `-f` path — the exact pattern the POSIX port already used — so bsdtar
  (System32 `tar.exe`) and GNU tar behave identically.
- **`ledger-collab.ps1` rejected its own documented `--re` flag.**
  PowerShell parameter prefix-matching bound `--re` to the `$Rest`
  parameter (re ⊂ Rest), consuming it and derailing binding of every
  later flag ("parameter cannot be found '-session'"). The parameter is
  renamed `$Extra`; `emit assessment --re <id>` and friends work.
- **New `context-*.cmd` launchers**, one per `.ps1` port. A `.cmd` file is
  executed by cmd.exe regardless of the PowerShell execution policy, and
  starts its port with `powershell -NoProfile -ExecutionPolicy Bypass
  -File`. The documented Windows invocation becomes e.g.
  `.context_ledger/core/bin/ledger-mem.cmd check` — no `Set-ExecutionPolicy`
  step. Windows PowerShell 5.1 is targeted deliberately: it ships with
  every Windows 10+ install, while pwsh 7 is an optional add-on. All
  docs (kickoff, both protocol editions, schema, README, QUICKSTART) now
  show the `.cmd` form.

**Migration from 0.13.x:** `update` installs the launchers with the rest
of `core/`; no memory changes and no behavior change for POSIX. Windows
agents should switch to the `.cmd` form; `pwsh -File` keeps working where
the policy allows it.

## 0.13.1 — 2026-09-06

**ASCII-clean the new PowerShell ports.** `ledger-mem.ps1` and
`ledger-history.ps1` (0.10.0–0.13.0) shipped with UTF-8 punctuation
(em-dashes, arrows) in string literals. Windows PowerShell 5.1 decodes the
`.ps1` as ANSI and fails to parse non-ASCII bytes — the same defect 0.9.1
fixed for the other ports. Both files are now ASCII-only, matching the
standing rule. POSIX ports unchanged (sh handles UTF-8). No behavior change;
manifest regenerated.

## 0.13.0 — 2026-09-06

**Session history is grouped and bounded (three-zone lifecycle).**
`agents/sessions.md` was append-only *forever* — session history grew without
bound and sat in the startup read (LocalMind's registry alone spans dozens of
sessions). This introduces session **groups** that rotate through three zones
so `memory/` only ever holds the live group.

- **New zones `history/` and `archive/`** under `.context_ledger/` (created by
  bootstrap and installed by `update` for existing projects). Neither is read
  at session start — the schema and both editions state this. `memory/`
  (live) → `history/` (closed, readable `group-<NNN>.md`) → `archive/` (cold
  `group-<NNN>.tar.gz`) → `gc`.
- **New `ledger-history` + `ledger-history.ps1`:** `status` (current group,
  session count, zone sizes, due?), `close [--milestone L] [--confirm]`
  (consolidate the live group into `history/`, start a fresh group, roll the
  oldest readable group into `archive/`), `gc [--confirm]` (delete oldest
  `archive/` tarballs over the cap, oldest-first, git-recoverable). Destructive
  steps are gated behind `--confirm` and print a dry-run plan first.
- **A "group" is the session-history subtree only** — `agents/sessions.md`,
  `sessions/SUMMARY.md`, `sessions/<date-N>/`. Durable facts (`user/`,
  `system/`, decisions, backlog, flaws, inefficiencies) and collaboration
  events never rotate; they persist in `memory/` with their own hygiene. This
  scoping is deliberate: resetting all of `memory/` per group would break the
  durable-facts spine (ADRs are respected, not relitigated).
- **No implicit carryover.** `close` prints a promotion checklist and refuses
  to execute without `--confirm`: every open thread must already live in its
  durable domain file before the group closes, so the new group starts clean —
  the spec's "no carryover" enforced at the boundary, not by wiping memory.
- **Tunable, weak-agent-safe defaults** in `memory/workflows/history.conf`:
  `group_size=20`, `history_keep=3`, `archive_keep=12`. `agents/sessions.md`
  becomes the *current group's* registry (backward-compatible — rotation only
  begins at the first `close`).

**Migration from 0.12.x:** `update` creates `history/`, `archive/`,
`history.conf`, and `agents/GROUP` if absent, and never clobbers an existing
one. Existing `agents/sessions.md` keeps growing until the first
`ledger-history close`, which starts the rotation. Archives are `.tar.gz` on
both platforms (the `.ps1` uses `tar.exe`, shipped on Windows 10+).

## 0.12.0 — 2026-09-05

**Bound the durable logs (context pruning).** The append-only durable logs
(`flaws/log.md`, `inefficiencies/log.md`) grow forever and sit in the
mandatory startup reading order, so a mature project reads mostly resolved
history every session (LocalMind: flaws 614 lines / 52 entries,
inefficiencies 1172 lines / 108 entries). The session layer already had a
cold-storage story (disposable notes, prunable SUMMARY.md); the durable
layer had none.

- **`ledger-mem prune`:** advises archiving resolved history out of the
  durable logs. It reports each log's size and how many entries are
  explicitly marked `RESOLVED` / `superseded` / fixed — the archive-eligible
  ones — and `--list` names them. It **never moves or deletes anything**;
  archiving stays a deliberate cut-and-paste into a companion `archive.md`
  (which stays in git, grep-able). Conservative by design: **only an
  explicit closed marker makes an entry eligible; age alone never does**, so
  an unresolved flaw is never archived out from under the next agent.
- **The archive convention** is documented in both editions (beside the
  SUMMARY.md prune rule), the schema, and the `flaws/` and `inefficiencies/`
  log templates: move a resolved entry verbatim into `archive.md`; startup
  reads only the active log.

**Migration from 0.11.x:** none — additive advisory + wording. Nothing is
moved automatically; run `ledger-mem prune` when a log feels heavy and
archive the entries it flags.

## 0.11.0 — 2026-09-05

**Keep `.context_ledger` vocabulary out of product code.** The protocol trains
agents to think in ADRs, bug IDs, and session numbers — and that vocabulary
leaks into product artifacts. Across the fleet, product source cites
`.context_ledger`-internal terms in docstrings and comments
(`/** ADR-34 B-8: bounded evidence entry */`, `"""ADR-11 one-time data
copy..."""`) — dangling pointers into a `.context_ledger/` that anyone cloning only
the product repo does not have.

- **`ledger-mem lint`:** a new subcommand (POSIX + PowerShell). It scans the
  **staged** product diff (everything outside `.context_ledger/`) and fails if an
  added line cites an ADR number (`ADR-N`), a bug ID (`B-YYYY-MM-DD-N`),
  `"per ADR"`, or a `.context_ledger/` path. `.context_ledger/` files are exempt — they
  legitimately use the vocabulary. (`Session N` is deliberately *not*
  flagged: apps have a legitimate "session" domain noun.)
- **The one-way-linkage rule.** Memory may reference product code; product
  code must never reference memory. Added as a pitfall in both editions, the
  `AGENTS.md` "two surfaces" rule, and a schema invariant. If the reason for
  a decision matters, state it in plain words in the docstring; the ADR link
  lives in `plans/decisions.md`, which points at the code — never the
  reverse. The pre-commit step runs `ledger-mem lint` for product commits.

**Migration from 0.10.x:** none — additive subcommand + wording. Existing
product code that already cites `.context_ledger` vocabulary will fail
`ledger-mem lint` on the next edit to those lines; rephrase the docstring to
stand alone and move the ADR link into `plans/decisions.md`.

## 0.10.0 — 2026-09-05

**Update-in-place registries stop duplicating.** `system/ai-models.md` and
`system/environments.md` are update-in-place (one entry per key), but the
append-only invariant is stated so loudly that agents apply it here too and
*append* a corrected entry instead of editing the existing one — so a
registry accumulates two rows for one key with conflicting counts (observed
in the fleet: one agent+model registered three times, sessions 8/10/30).

- **`ledger-mem` + `ledger-mem.ps1`:** a new helper. `ledger-mem check`
  flags a duplicated key in the update-in-place registries —
  `ai-models.md` keyed by (Agent, Model), `environments.md` by its
  "Identify by:" line. It is the inverse of the append-only rule: for these
  files, a *second* entry for an existing key is the defect. Different
  models for one agent are separate rows (expected), not duplicates.
- **The distinction is now stated as loudly as append-only.** Both protocol
  editions' top rules, the `AGENTS.md` digest, the `ai-models.md` header,
  and the schema now say: correct an update-in-place entry by *editing* it,
  never by appending a duplicate — the prior value is safe in git history,
  so editing loses nothing. The exit step runs `ledger-mem check`.

**Migration from 0.9.x:** none — additive helper + wording. Existing
registries that already have a duplicated key will fail `ledger-mem check`;
merge the rows/blocks into one (sessions accumulate) and the old values
remain in git history.

## 0.9.1 — 2026-09-05

**Windows verified on Windows.** 0.9.0 shipped the durable LF policy
(`.gitattributes`) and the CRLF manifest-parse fix, but the verifiers still
hashed raw on-disk bytes — so any CRLF copy of the core (a project checked
out under `core.autocrlf=true` before the `.gitattributes` existed, or files
copied outside git, where the attribute never reaches) still failed every
hash and reported CORE INTEGRITY FAILURE. Worse, the advised remediation
(`rollback`) re-restored CRLF bytes on those targets — an unfixable loop —
and on the sh side a CRLF `memory/core.lock` poisoned the version lookup so
rollback died with "no commit in history has core VERSION". This release
was written and validated on Windows (Git Bash + PowerShell 7.6 + Windows
PowerShell 5.1), closing the validation pass 0.9.0 owed.

- **`verify` hashes CR-stripped content** (both sh and PowerShell). One
  manifest stays byte-compatible across LF checkouts and CRLF copies:
  LF-only files hash identically, so `MANIFEST.sha256` values are unchanged
  and 0.9.1 verifiers validate 0.9.0 cores and vice versa. A CRLF copy now
  verifies clean instead of reporting 46 false integrity failures.
- **`update` / `bootstrap` normalize the staged copy to LF in place**
  (sh `normalize_lf`; PowerShell `Convert-ToLf`), so a core vendored or
  updated from a CRLF source is byte-identical to its manifest on disk —
  no renormalize dance needed afterward. `bootstrap` normalizes the memory
  skeleton too.
- **PowerShell `rollback` rewrites the restored core to LF**, so a rollback
  under `core.autocrlf=true` verifies afterward instead of looping.
- **`lock_version` tolerates a CRLF `core.lock`** (sh), fixing the
  rollback dead-end above.
- **PowerShell `update` parity with sh:** installs `.context_ledger/.gitattributes`
  and the root `CLAUDE.md` pointer when absent — and `update` now installs
  them on *every* run, including a no-op, so a 0.8.x project's second
  `update` (after the new core has landed) picks them up (0.9.0 taught
  only the sh script; Windows agents run the `.ps1`).
- **Gate results propagate again.** Two independent bugs silently turned
  every gate failure into a pass. PowerShell: `Run-One`'s log lines went
  through the return pipeline, so `if (-not (Run-One ...))` compared an
  array — and `-not` on a non-empty array is always `$false`. sh:
  `run_explicit` and `run_discovered` reset the caller's `_failed` counter
  (functions have no locals in sh). Gate logs now go to the host stream
  and the sh helpers use distinct failure counters. Also: a cmdlet-only
  gate command no longer inherits a stale `$LASTEXITCODE`, a thrown
  script error fails the gate instead of crashing it, and child `.ps1`
  invocations pre-seed `$LASTEXITCODE` (a child script's `exit N` does
  not reliably set it on every host, and reading it unset trips
  StrictMode).
- **PowerShell argument parsing works again.** Parameters named `$Args`
  collide with the automatic variable of the same name, so every
  `--session/--issue/--paths/...` flag was silently lost in
  `ledger-collab.ps1` (status filters matched everything) and
  `ledger-gates.ps1` (checkpoint and integration scopes no-oped).
  Renamed throughout. A missing collaboration events directory no longer
  crashes `ledger-collab-check.ps1` under StrictMode.
- **`manifest` regenerates identically on Windows.** `sha256sum` under Git
  Bash defaults to the binary-mode separator (`hash *path`), so a
  Windows-regenerated manifest churned all 46 lines vs a mac `shasum`
  regen; `cmd_manifest` now forces the text-mode separator (`-t`). The
  parsers already accept both.

**Migration from 0.9.0:** none — verify both ways, no manifest or memory
changes. Projects still on a CRLF working tree no longer need the 0.9.0
renormalize step for `verify` to pass; the `.gitattributes` LF policy
remains the durable git-level fix and is worth committing anyway.

**Upgrading a 0.8.x project on Windows:** (1) Use a git checkout of this
package as the update source — a fresh clone, or the existing clone pulled
to 0.9.1 and re-smudged (`rm -rf core && git checkout -- core`) if it
predates 0.9.0. The 0.8.x verifier hashes raw bytes, so a CRLF source (a
stale clone or a hand copy) will be refused. (2) Run the update under Git
Bash or PowerShell 7 — the 0.8.x `.ps1` cannot be parsed by Windows
PowerShell 5.1 (its UTF-8 punctuation breaks 5.1's ANSI decoding; the
0.9.1 `.ps1` files are ASCII-clean). (3) Run `update` a second time after
it lands: the first run executes the old script and swaps in 0.9.1, the
second (no-op) run is the one that installs `.context_ledger/.gitattributes` and
the root `CLAUDE.md` pointer. (4) Commit `chore(ledger): update core to
0.9.1`, and `git add --renormalize .` if the project ever committed CRLF
blobs. Once 0.9.1 is in place, `verify` passes on LF and CRLF working
trees alike, so the rollback deadlock cannot recur.

## 0.9.0 — 2026-09-05

**Collaboration that feels like coworkers.** Peer collaboration was
technically working but less effective than single-agent mode: fleet
evidence (LocalMind's 42-event trail — the only trail that ever exercised
it) showed agents paying heavy ceremony for solo work, never once
completing an `agreement`, and colliding on identical paths with no
resolution. The framing primed rivalry ("competing proposals are
expected"), the tooling reported closed claims as active forever and hung
for minutes, and Windows CRLF corrupted the integrity system. This release
turns the "courtroom" into an "office."

- **New `note` event — the office channel.** An informal heads-up to peers:
  a body is all it needs (optional `--to <peer>`, `--re <event|path|commit>`),
  it never gates `check`, and it never has to be resolved. `status` opens
  with a **Recent chatter** feed. Notes give agents the low-stakes
  back-and-forth they lacked, so peer reviews and hand-offs stop being
  smuggled into shared durable files.
- **Cooperative reframing.** The README, both protocol editions, the AGENTS
  digest, the schema, and the kickoff now frame peers as one team with one
  goal. The light path (`note` + `claim`/`release`) is the documented
  default; the `proposal → assessment → agreement` ceremony is the
  escalation for a genuine conflict (same paths, incompatible changes) only.
- **`ledger-collab` tells the truth.** A `release`/`handoff` now closes a
  claim when it cites the claim's event ID **or** simply shares its
  session+issue and overlaps its paths — so a release citing only the commit
  SHA no longer strands its claim as "active forever" (the common,
  weak-agent case).
- **`ledger-collab check` no longer hangs.** Rewritten as a single-pass
  in-memory index instead of re-globbing the events dir and forking
  `sed`+`head` per field. On a 42-event trail it went from > 3.5 minutes
  (killed) to < 0.1 s. Notes are exempt from every gate; release/handoff
  correspondence is checked by the same forgiving claim-linkage.
- **Windows / CRLF root fix.** New package-root `.gitattributes` and a
  shipped `templates/.gitattributes` (installed into `.context_ledger/` by
  `bootstrap` and `update`) force `eol=lf` on the vendored core *and* the
  memory logs — fixing the `ledger-sync verify` false-positive under
  `core.autocrlf=true`, the `sh` manifest-parse death on `\r`-suffixed
  filenames, and the phantom whole-file diffs in append-only logs. `verify`
  also tolerates a CRLF manifest defensively, and the "no sha256sum" error
  now points Windows users at the `.ps1` port.
- **`ledger-gates.ps1` runs again.** Fixed a PowerShell binding crash
  (`Cannot bind parameter because parameter 'PathType' is specified more
  than once` — two `Test-Path` calls chained by `-or` without parenthesizing
  each) that made every gate fail on Windows.
- **No agent starts blind.** Bootstrap (and `update`) now install a root
  `CLAUDE.md` pointer, because Claude Code auto-loads `CLAUDE.md`, not
  `AGENTS.md`, and a session that never reads the digest runs with zero
  `.context_ledger/` discipline (a logged fleet failure). `CLAUDE.md` routes into
  `AGENTS.md` + the kickoff; the bootstrap guidance and `AGENTS.md` header
  now name the other agent entrypoints (Copilot/Cursor/Gemini) that should
  carry the same one-line pointer. Existing `CLAUDE.md` files are never
  overwritten.

**Migration from 0.8.x:** fully compatible — the seven formal event types
keep their exact meaning; `note` is additive. New bootstraps and `update`
install `.context_ledger/.gitattributes`. If a project was already checked out with
CRLF (Windows `core.autocrlf=true`), run once after updating:
`git add --renormalize . && git commit -m "chore(ledger): normalize line endings to LF"`
(or set `core.autocrlf=false` and `git checkout -- .context_ledger`). The `.ps1`
ports could not be executed on the maintainer's Mac (no `pwsh`); they were
updated by mirroring the POSIX behavior and are cross-checked against the
manifest — a Windows validation pass is still owed.

## 0.8.0 — 2026-08-17

**Explicit lifecycle command gates.** Agents now have mechanical,
project-owned gates instead of relying only on prose instructions.

- **`ledger-gates` + `ledger-gates.ps1`:** add `checkpoint`,
  `pre-commit`, `integration`, and `exit` gate commands with consistent
  exit behavior and observable command output.
- **Per-agent-turn checkpoint:** refreshes working-tree and collaboration
  state before the next action, reducing stale-context work.
- **Project command registry:** new `memory/workflows/gates.conf` supports
  explicit commands per lifecycle gate. `mode=hybrid` uses safe conventional
  package.json/Python discovery only when no explicit command is configured;
  `mode=explicit` fails when a required gate has no command.
- **Mandatory transitions:** protocol editions, kickoff, AGENTS digest,
  and schema now require gates before commits, branch integration, and
  session exit. Integration includes `ledger-collab check` when a
  collaboration session/issue is supplied.

**Migration from 0.7.x:** existing projects remain compatible. New
bootstraps receive `gates.conf`; existing projects can initialize it with
`sh .context_ledger/core/bin/ledger-gates init` or the PowerShell equivalent.

## 0.7.0 — 2026-08-17

**Collaboration integration-readiness checks.** The collaboration helper
now provides a mechanical gate before product branches are integrated.

- **`ledger-collab check`:** validates required event metadata, event ID
  uniqueness, resolvable same-session/same-issue references, complete agreements,
  selected options, peer participants, owners, active claim overlaps,
  unresolved proposals/assessments/corrections/handoffs, and product
  commit references on releases.
- **PowerShell parity:** `ledger-collab.ps1 check` delegates to the
  PowerShell validator with the same checks and exit-code contract.
- **Operational split:** `status` remains the live-work view; `check` is
  the integration-readiness gate and fails when the event trail is not
  complete.

**Migration from 0.6.x:** none. Existing event trails remain readable;
projects gain the check helpers on their next core update.

## 0.6.0 — 2026-08-17

**Peer collaboration for concurrent and shared-issue sessions.** The
single-agent workflow remains the default, while agents can now opt into a
shared session/issue and coordinate without a mutable global lock.

- **Isolated workspaces:** collaborating agents use separate clones or git
  worktrees and `collab/<session-id>/<agent-id>` product branches; product
  commits never happen in the same checkout or directly on the shared
  integration branch during collaboration. Events publish to the shared
  event-only `collab/<session-id>/coordination` ref.
- **Immutable event trail:** projects gain `memory/collaboration/`, where
  each claim, proposal, assessment, agreement, correction, handoff, and
  release is a separate event file. Independent files avoid concurrent EOF
  append conflicts and preserve the complete reasoning trail.
- **Evidence-based peer agreement:** overlapping scopes require assessments
  and an agreement selecting the best-supported option and exactly one
  implementation owner. There is no timestamp, priority, or agent-ID
  winner; genuinely tied evidence pauses for the user.
- **Corrections:** an agent can record the observed mistake, evidence, likely
  cause, candidate repairs, and suggested fixer; peers agree on the repair
  and owner before the correction is applied.
- **`core/bin/ledger-collab` + `ledger-collab.ps1`:** POSIX and
  PowerShell helpers for atomic event creation and overlap/status inspection.
- **Schema and protocol:** both editions, kickoff, AGENTS digest, README,
  and schema now distinguish single-agent `tasks/current.md` locking from
  collaboration event coordination.

**Migration from 0.5.x:** none required for existing single-agent
projects. New bootstraps receive `memory/collaboration/README.md`; an
existing project that opts in copies that template into
`.context_ledger/memory/collaboration/` during its first collaboration session.
Core updates never touch memory. Event files are created only when a
project opts into collaboration.

## 0.5.0 — 2026-07-31

**The session-scoped memory release.** Session history is now self-contained
and disposable — separate from durable project knowledge — preventing
`.context_ledger/` bloat while preserving continuity.

- **New `memory/sessions/` module:**
  - `memory/sessions/SUMMARY.md` — compressed session history (~1 line
    per session, prunable). Unlike `agents/sessions.md` (append-only
    forever), entries here may be removed when a session is no longer
    useful. Future agents skim the last ~10 entries at startup for
    compact continuity.
  - `memory/sessions/<date>-N/notes.md` — per-session detailed notes
    (append-only while active, deletable after promotion). Optional — a
    trivial session creates no directory. Holds research, exploration,
    dead ends, and implementation reasoning that would otherwise bloat the
    global logs or the compact summary.
- **Context Promotion (new in Step 17 of both editions):** at session end,
  the agent evaluates session notes and promotes durable facts to their
  persistent domain (`decisions.md`, `backlog.md`, `inefficiencies/log.md`,
  `preferences.md`, `flaws/log.md`). The promotion invariant: **permanent
  context must never depend exclusively on an individual session** — a
  fact that matters beyond the session lives in its domain file, so
  deleting the session directory cannot delete the knowledge.
- **"Session data is disposable" principle:** enshrined in both editions
  (rule 7 of the `.context_ledger/` Rules) and in `memory/sessions/README.md`.
  Session directories may be deleted; SUMMARY.md entries pruned; the
  formal registry (`agents/sessions.md`) is the permanent record.
- **Three-layer model:** session detail (disposable) → session summary
  (prunable) → permanent registry (append-only). Together with the
  durable domain files, this gives a clean lifecycle: new information →
  session notes → summary → evaluate durability → promote or discard.
- **Schema:** new `sessions/` entries in `ledger-schema.md` and
  `ledger.schema.json`; reading order now includes `SUMMARY.md`.
- **Templates:** `memory/sessions/README.md`, `SUMMARY.md`, and `notes.md`
  added under `core/templates/memory/sessions/`.
- **Migration from 0.4.x:** none required. The `sessions/` directory
  appears on first use; existing memory files are valid as-is. The new
  `Notes:` line in `agents/sessions.md` entries and the `SUMMARY.md`
  append are additive — sessions on 0.4.x cores continue to work,
  upgrading when their project pulls 0.5.0.

## 0.4.0 — 2026-07-30

**The Windows release.** The tool no longer assumes a POSIX shell. Windows
agents run PowerShell, not `sh`, so a `sh`-only `ledger-sync` failed at
session startup (`verify`/`status`) with no fallback. This adds a
PowerShell port of the session commands.

- **`core/bin/ledger-sync.ps1` (PowerShell port):** covers the project-mode
  commands an agent hits inside a session — `status`, `verify`, `update`,
  `rollback`, `lock`. Requires PowerShell 5.1+ (`pwsh` or Windows
  PowerShell). Invoke as
  `pwsh -File .context_ledger/core/bin/ledger-sync.ps1 <cmd>`; the `--major`
  update gate is the `-Major` switch. Byte-compatible with the `sh` tool's
  `MANIFEST.sha256` (identical SHA-256 hashes, forward-slash paths), so a
  core verified on one platform verifies on the other.
- **Package-mode commands stay `sh`-only:** `manifest`, `bootstrap`, and
  `harvest` are not ported — the maintainer runs them from a package clone
  on macOS/Linux. The `.ps1` prints a pointer to the `sh` script if asked
  for one of them.
- **Docs:** `sh …/ledger-sync <cmd>` invocations across the kickoff,
  QUICKSTART, and schema now show the PowerShell equivalent for Windows.
- **Migration from 0.3.x:** none. The port is additive; existing projects
  gain `ledger-sync.ps1` on their next `update`. macOS/Linux behavior is
  unchanged.

## 0.3.0 — 2026-07-21

**The harvest release.** Closes the upstream loop the `flaws/` directory
only ever promised: project memory now flows back to the package
mechanically instead of by hand.

- **`ledger-sync harvest` (package mode):** run from a package clone, it
  reads `fleet.md`, reaches every listed project read-only (a sibling
  clone matched by remote URL, else a shallow clone), and collects three
  signals into `inbox/harvest-<date>.md` for triage — open `flaws/`,
  `Upstream: candidate` inefficiencies, and `[core-defect]` overrides. A
  committed ledger (`inbox/.harvested`) hashes each entry so re-runs never
  re-file it. Never writes to the projects.
- **Fleet registry (`fleet.md`, package root):** `bootstrap` now appends
  each new project's `origin` URL, so the package knows its own
  downstream repos. Append-only; idempotent on the URL.
- **Schema fields for harvest opt-in:**
  - `inefficiencies/log.md` gains an optional `**Upstream:** candidate`
    line — marks protocol-level friction for collection; project-local
    friction stays unmarked and unharvested.
  - `overrides/rules.md` bullets are now tagged `[core-defect]` (a local
    patch to a core bug — harvested) or `[project-local]` (legitimate
    project difference — never harvested). Overrides survive core bumps,
    so an untagged core-defect workaround would otherwise stay stranded
    in one project forever.
- **Migration from 0.2.x:** none required. The two template fields are
  additive and opt-in; existing memory files are valid as-is. Maintainers
  gain `fleet.md` + `inbox/` at the package root (bootstrap creates
  `fleet.md` on first use; back-fill older projects by hand).

## 0.2.0 — 2026-07-14

**The vendored-core release.** The protocol no longer lives in a sibling
clone — it travels inside every project as `.context_ledger/core/`, beside the
project's own memory in `.context_ledger/memory/`.

- **Two-zone layout:** `.context_ledger/core/` (package-owned, read-only,
  version-stamped) + `.context_ledger/memory/` (project-owned, writable, never
  synced). Replaces the basename-based structural/data split; `SYNC.md`
  is retired.
- **Memory modules move under `memory/`:** `agents/`, `tasks/`, `plans/`,
  `flaws/`, `inefficiencies/`, `reviews/`, `system/`, `user/`,
  `workflows/`, `secrets/` keep their names and formats — only the path
  prefix changes. `kickoff.md` and `README.md` stay at the `.context_ledger/`
  root as the front door and zone map.
- **New memory modules:** `memory/overrides/rules.md` (project-local
  protocol adjustments, read after the edition) and `memory/core.lock`
  (last-known-good core version, written by `ledger-sync`).
- **Unified schema:** `core/schemas/ledger-schema.md` (+
  `ledger.schema.json`) is now the single authority on every memory
  file's format, write mode, ownership, and fact scope — including the
  per-agent-type vs per-project vs per-machine scoping rules that stop
  cross-agent-type contamination.
- **`core/bin/ledger-sync`:** POSIX-sh tool — `status`, `verify`,
  `update`, `rollback`, `bootstrap`. Startup change detection, checksum
  integrity via `core/MANIFEST.sha256`, git-based rollback to the
  locked version.
- **Weak-agent translation layer:** bootstrap generates a root
  `AGENTS.md` digest (from `core/templates/AGENTS.md`) so agents that
  never read a 900-line edition still learn the zones, the entry point,
  and the binding rules.
- **Cloud sessions need no package access after bootstrap** — the
  protocol is on disk inside the project. Package PATs are a
  bootstrap-only concern.
- **Migration from 0.1.x:** see `MIGRATION.md` in the package repo.
  Summary: create `memory/`, `git mv` the modules into it, vendor
  `core/`, regenerate `kickoff.md`, delete `SYNC.md`.

## 0.1.0 — 2026-07-13 (retroactive)

The sibling-clone era: two protocol editions at the package root,
`context-skeleton/` bootstrapped into projects as a flat `.context_ledger/`,
structural-vs-data sync per `SYNC.md`, package cloned beside every
project as `../context`. Never formally released; version assigned
retroactively as the baseline `MIGRATION.md` migrates from.
