# Flaws Log (append-only — flows to the protocol package)

Friction caused by the `.context_ledger/` system or the protocol itself. See
`README.md` in this directory for the split between `flaws/` and
`inefficiencies/`.

Append-only, but compactable — the log never grows without bound:

- **Resolved entries move verbatim** to cold storage: once an entry is
  explicitly marked `RESOLVED` / `superseded` / fixed, cut it unchanged
  into `archive.md` in this directory so startup reads only the live
  entries. Age alone never makes an entry eligible — an unresolved flaw
  stays here as a live trap.
- **Repeats roll up:** when 3+ entries describe the same recurring
  protocol trap, append ONE consolidated `Recurring` entry — the pattern,
  how many times, the current workaround — and move the individual
  entries verbatim into `archive.md`. The live log keeps the pattern, not
  the repeats.

`ledger-mem prune` reports log sizes, archive-eligible entries (`--list`
names them), and roll-up candidates.

<!-- TEMPLATE — copy below the last entry:
---
## YYYY-MM-DD — <agent> / <model> (Session N)

- **Flaw:** <what in the protocol or .context_ledger/ system didn't work>
- **Symptom:** <what happened to the agent — the observable friction>
- **Root cause:** <why the protocol/.context_ledger/ let this happen>
- **Suggested fix:** <concrete change to the package — a step, a pitfall,
  a template, a rule>
- **Status:** open | fixed in package <commit-sha or date>
-->

---
## 2026-09-21 — re-seeded at the office-002 close (carried, not observed here) — four still-open protocol traps

These four were open when office-002 closed; they are traps in the
protocol itself, not facts about the past, so they carry live. Detail and
evidence: `history/office-002/flaws/log.md`.

- **Flaw 1 — the gates have no teeth on a bare Windows PATH.** Every gate
  step in `workflows/gates.conf` runs through `sh -c`, and on a Windows box
  without a POSIX shell the step does not hard-fail — a red leg (a lint
  error, a failing test) can pass silently and let a session clock out on a
  red tree. It has already masked a real exit-gate failure at least once.
- **Flaw 2 — a pathless `git commit` sweeps a peer's staged files into your
  commit.** With two sessions in one checkout, `git commit -m` (no
  pathspec) commits whatever the shared index holds, so a peer's
  in-flight closeout rides into an unrelated commit; it has happened twice.
  The standing workaround is the explicit-adds rule in
  `memory/overrides/rules.md` — add only the paths you touched, never
  `git add -A`, never `git commit -a`. Root cause: nothing checks *what* is
  staged against the committing session's own claim.
- **Flaw 3 — a collab `claim` event silently accepted a truncated paths
  list.** The emitted event looked normal while covering fewer paths than
  the session believed, so its scope was invisible to peers. Candidate
  hardening: `ledger-collab emit claim` should echo the parsed paths back
  (and refuse an empty or obviously truncated list).
- **Flaw 4 — the deferral-to-claimant pattern has no fallback.** When a
  session finds a gate-blocking problem inside a peer's live surface it
  emits a `note` and leaves it; if that peer then clocks out without
  clearing it, the item is orphaned until a later session trips over it —
  which is exactly what happened. Suggested fix: a `release`/clock-out that
  deletes a backlog row should be gated on the exit gate passing for the
  released scope, or `ledger-collab check` should surface unresolved
  `note`-deferrals against the claim's own paths before the release closes
  it.
- **Status:** open (owners: the next core-maintainer pass for 1 and 3; the
  project's own gate runner for 2 and 4).

---
## 2026-09-21 — Mosi / deepseek-flash (ZCode, S001) — the fresh office inherits executable bits from the core templates

- **Flaw:** `ledger-history close` opens the new office from
  `core/templates/memory/office/`, and eight of those template files ship mode
  0755 (`agents/sessions.md`, `tasks/backlog.md`, `tasks/current.md`,
  `plans/decisions.md`, `flaws/log.md`, `flaws/README.md`,
  `inefficiencies/log.md`, `reviews/README.md`), so every close introduces a
  spurious `100644 → 100755` mode change on plain markdown notes.
- **Symptom:** the closing commit's diff carries eight mode-only changes, and
  every later edit to those files shows mode churn in the diff; the rest of the
  repository's memory files are 0644, so the office files look executable for no
  reason.
- **Root cause:** the template tree's own file modes were never normalized when
  it was packaged into core (only the office templates are affected —
  `agents/roster.md` and the `sessions/` files are 0644).
- **Suggested fix:** normalize the template tree to 0644 in the package, or have
  `ledger-history close` copy content and set 0644 explicitly.
- **Status:** open (owner: the next core-maintainer pass); the mode churn in
  this repo was corrected in the same commit that logged this.

---
## 2026-10-26 — Dara / deepseek-flash (S003) — resuming a stalled peer has no ledger path, and the Windows baseline is incomplete

- **Flaw 1 — the protocol has no way to resume a session that died mid-task
  under another agent's codename.** The owner restarted a session that had
  run out of provider funds and told the resuming agent to assume the
  original identity and *not* check in. The protocol only knows fresh
  check-ins and clock-outs: without a check-in the roster shows no live row
  while the work continues, and `ledger-mem check` flags a second entry for
  an existing session number as "a resumed session re-logged". The resumed
  agent is therefore either invisible on the board or a duplicate.
- **Flaw 2 — the pytest baseline is not platform-complete.** Three tests
  (`test_tilde_display_normalizes_home_and_nested_paths`,
  `test_pip_install_goes_to_localmind_folder_by_default`,
  `test_the_shell_tool_really_runs_in_the_chosen_shell`) hardcode POSIX
  paths/shells and fail on Windows, but none is in
  `scripts/pytest-baseline.txt`. Every Windows session's exit gate reports
  them as new regressions for code it never touched, and the baseline's own
  rule — "never add entries; new failures are regressions" — forbids the
  cheap fix at the gate. Proving they are pre-existing costs a full suite
  run on a clean-HEAD worktree (≈14 minutes here).
- **Root cause:** (1) the workflow assumes one agent ↔ one session ↔ one
  live row, with no adoption handoff; (2) the baseline was recorded on the
  machine where the suite was authored, and no gate step distinguishes "new
  on this OS" from "new in this diff".
- **Suggested fix:** (1) an explicit `resume`/`adopt` mode that keeps the
  original codename and appends to the original session entry instead of
  demanding a new check-in; (2) make the platform-dependent tests
  platform-aware (done for these three — they now assert against `os.sep` /
  the offered-shell list) or generate the baseline per OS at gate time.
- **Status:** the three tests are fixed in this session; the two protocol
  questions (adoption, per-OS baseline) remain open for a core pass.
