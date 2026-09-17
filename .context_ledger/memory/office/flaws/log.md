# Flaws Log (append-only — flows to the protocol package)

Friction caused by the `.context_ledger/` system or the protocol itself. See
`README.md` in this directory for the split between `flaws/` and
`inefficiencies/`.

Append-only, but prunable to cold storage: once an entry is explicitly
marked `RESOLVED` / `superseded` / fixed, move it **verbatim** into
`archive.md` in this directory so startup reads only the live entries.
`ledger-mem prune` reports which entries are archive-eligible (`--list`
names them); age alone never makes an entry eligible — an unresolved flaw
stays here as a live trap.

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
## 2026-09-12 — Amani / glm-5.3-flash (S1) — office-001 close: two protocol asks carried live (re-seeded from the frozen flaws log)

- **Observed:** at the first `ledger-history close` (447 sessions,
  2026-07-31 → 2026-09-12), two flaws in the frozen log were still OPEN and
  would otherwise have vanished with the office. Re-seeded here so the next
  sessions see them:
  1. (Omari/S472) The collab topology defines no integration step for when the
     main checkout is a peer's workspace — git refuses the same branch in two
     worktrees and the isolation rule forbids touching the peer's tree. The
     working derivation: `git fetch` → rebase your branch onto origin/main →
     `git push origin <branch>` → `git push origin <branch>:main` (refspec
     fast-forward of the remote only). The ask: state this in the edition or
     the project override.
  2. (Buffy/S472) The roster has no mechanical table-shape guard: a check-in
     insertion that consumes the wrong newline still mangles the table while
     "following the rule". The ask: `ledger-mem check` (or the pre-commit
     registry) should lint the roster — check-in diff must read `1 0` on
     `git diff --numstat`, every row must carry the header's pipe count, and
     a row containing a second name/codename group is a hard fail.
- **Suggested fix:** both are package/edition wording or checker additions;
  owners are the next core maintainer pass.
- **Status:** open (carried; not re-verified this session beyond the original
  entries — read the full context in `history/office-001/flaws/log.md`).

---
## 2026-09-14 — Njeri / qwen3.8-flash (S003) — clean-session silence vs the bookkeeping gate's staleness teeth

- **Flaw:** core 1.1.0's log compaction says "a clean session appends nothing" to the friction logs (both editions + schema), but this project's configured exit gate (`scripts/check-bookkeeping.sh`, itself an S296-era fix for bookkeeping drift) FAILS when the friction logs' newest date trails `sessions.md` — so a genuinely clean session is mechanically forced to append exactly what the compaction rule calls noise.
- **Symptom:** S003's exit gate failed once on `STALE: inefficiencies/log.md ... flaws/log.md`; the checker's own hint ("an explicit '## date — none this session' counts") reconciles them only for the session that discovers it.
- **Root cause:** the compaction rule and the staleness checker encode different definitions of "current" — one is content (only real friction earns a block), the other is a date watermark. Neither references the other.
- **Suggested fix:** the package should state the reconciliation: either the editions note that projects whose bookkeeping gate watermarks by date require the explicit one-line clean entry (compaction's "appends nothing" means "no friction block", the watermark line still counts), or `check-bookkeeping.sh`'s shipped guidance should move into the schema so projects inherit the same reading.
- **Status:** open

---
## 2026-09-15 — Zuri / qwen3.8-flash (S004)

- **Status:** none this session — no protocol/`.context_ledger` friction (the one-line clean entry is the bookkeeping-gate watermark, per the flaw logged 2026-09-14).

---
## 2026-09-15 — Imani / qwen3.8-flash (S008) — the gates' `sh` commands have no teeth on a bare Windows PATH

- **Observed:** every `sh scripts/...` line in gates.conf fails under the
  `ledger-gates.cmd` launcher with "The term 'sh' is not recognized" on a
  stock PowerShell 5.1 session (Git ships `sh.exe` in
  `C:\Program Files\Git\bin` but that directory is not on PATH by default;
  only `Git\cmd` is). The universal `git diff --cached --check` step
  passes, so a first read of the output can mistake the rest for real
  failures of the code under test.
- **Fix applied in-session:** prepend the Git bin before any gate run
  (PowerShell: set the PATH variable to Git's bin directory followed by the
  existing value) — all steps then run and report honestly.
- **Status:** open — the project's `.cmd` launchers (or gates.conf's own
  comments) should state the PATH prerequisite so every Windows session
  doesn't rediscover it. Candidate: the launcher prepends Git's bin itself
  when it locates it via `where git`.

---
## 2026-09-15 — Baraka / qwen3.8-flash (S005) — the shared index is a cross-session trap in a live-peer checkout; no gate checks WHAT is staged

- **Flaw:** One session deep in a long edit (a 449-file manual sweep) committed with
  `git commit -m` (no pathspec) while a CONCURRENT session's closeout files sat STAGED
  in the shared index — the commit swept them in (product commit b49d16d1 carried
  another session's roster removal, sessions.md entry, watermarks, review file,
  backlog row). All content survived and pushed; attribution + the two-surface rule
  broke. The `pre-commit` gate passed: `git diff --cached --check` validates
  whitespace only — nothing checks that the staged set belongs to the committer or
  that both surfaces never coexist in one commit.
- **Symptom:** mixed-surface commit on main with another session's closeout.
- **Root cause:** office state goes stale within minutes when peers are live in the
  same checkout (exactly the S421 class; the standing rule to re-checkpoint before
  each action was skipped across a long streak of same-file edits).
- **Workaround applied this session:** correction note on the event trail (names the
  peer + the swept paths, tells them not to re-commit); commit moves to an isolated
  worktree for the rest of the sweep; `git diff --cached --stat` reviewed before
  every commit from here on.
- **Prevent next time:** the package's pre-commit should hard-fail a staged set that
  mixes `.context_ledger/` with product paths (one check: `git diff --cached
  --name-only` intersects both sets → fail with "commit the surfaces separately"),
  and warn when staged paths match another live roster row's claimed scope.
- **Status:** open (owners: next core maintainer pass)

---
## 2026-09-15 — Tega / qwen3.8-flash (S009) — a collab claim event silently accepted a truncated paths list

- **Observed:** my claim event (20260915T130934Z-Tega-3755ab45) described a
  seven-file scope in its body but its structured `paths` list carried
  exactly one entry — `backend/src/api/routes/sessions.py`. The emit
  accepted it without complaint, so for the session's whole middle stretch
  the office's machine-readable view of who holds which files under-reported
  my claim (a peer reading only paths would not have known I was inside
  models.py/db.py/client.ts).
- **Root cause:** the emit was built by a PowerShell one-liner whose quoting
  swallowed the comma-separated list after the first element; the tool
  validates that `paths` parses, not that it covers the body.
- **Fix applied in-session:** a correction event (47d644c9) records the full
  shipped scope before the release.
- **Status:** open — candidate hardening: `ledger-collab emit claim` should
  warn when a claim's paths list is empty or covers a suspiciously small
  fraction of the paths mentioned in its own body (a substring scan of the
  body for path-shaped tokens is enough), so the truncation fails loud at
  the door instead of mid-collision.

---
## 2026-09-16 — Zawadi / Qwen3.8 Flash (Session 12) — check-in pushed after the supervisor had to ask

- **Flaw:** the check-in-first rule (AGENTS.md rule 5, kickoff Step 2) was
  followed in the wrong order: I read the office files and ran the full
  worktree audit before committing and pushing my roster row. The
  supervisor had to ask "Have you checked in!!!!!" before the row went up.
- **Symptom:** for several minutes the board showed peers (S005, and
  Chemi arriving concurrently) with no S012 row — and the race actually
  bit: Chemi and I both took S012 because neither board showed us at the
  moment we read it. It self-resolved (Chemi renumbered to S013), but a
  silent collision is exactly what rule 5 exists to prevent.
- **Root cause:** the startup read list is long and the audit work was
  already in the user's request, so "gather context first" pulled me past
  "the push claims the codename". The protocol says the startup read
  comes AFTER the row is pushed; my order inverted it with no mechanical
  nudge to catch it.
- **Suggested fix:** the kickoff Step 2 order is already explicit — the
  gap is sequencing for agents that batch reads: make the roster+sessions
  two-file read the FIRST tool calls of the session and block all other
  reads/searches/commands until the check-in commit is pushed. A
  `ledger-gates checkpoint` that fails when HEAD's roster lacks a row for
  the session doing the checking would catch it mechanically.
- **Status:** open

---

## 2026-09-16 — Chemi / Qwen3.8 Flash (S013)

- **Status:** none this session — no protocol-level friction (one-line clean entry per the 2026-09-14 bookkeeping-watermark reconciliation; the heredoc/aliasing traps were tool- and code-level, logged in inefficiencies).
