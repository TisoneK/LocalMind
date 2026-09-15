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
