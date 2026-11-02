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
## 2026-10-31 — Kofi / unknown (harness states no model ID)
- **Flaw:** Two live sessions sharing one checkout collide on the ledger surface: a peer's `chore(ledger)` commit swept this session's uncommitted review report and parking-lot row (its `git add .context_ledger/` staged both sessions' edits), so work-in-progress was committed under the wrong session — and the same index sweep can capture in-flight product changes.
- **Symptom:** This session's `office/reviews/2026-10-31-review.md` and parking-lot entry appeared in a peer's check-in commit (`c199cbd1`) they did not author; the peer's next staged product files sat in the shared index while this session was about to commit.
- **Root cause:** The kickoff's check-in flow writes to the shared main checkout before mode is decided ("decide the mode from evidence, not from an empty board"), and `ledger-guard` attributes by count of live sessions but cannot tell whose staged files are whose. Nothing forces the second arriving session into a worktree, and a broad `git add .context_ledger/` is the documented way to stage memory.
- **Suggested fix:** (a) Once the roster shows a second live row, have `ledger-guard` refuse a ledger commit whose diff includes files another live session has touched in its own check-in window, or (b) make the kickoff require an isolated worktree/branch for the later arrival before its first ledger write, and (c) have `ledger-mem`/`ledger-guard` print which session each staged path belongs to at commit time.
- **Status:** open

---
## 2026-11-01 — Zuri / GLM (Z.ai sandbox) (Session 11)
- **Flaw:** The check-in sequence's own tooling generates local ledger modifications BEFORE the sync step can complete: `ledger-sync verify` rewrites `memory/core.lock` (drops/reshuffles the `source_*` block) and `ledger-state generate` rewrites `memory/office/STATE.md`, so a fresh-session `git pull --ff-only` then aborts with "Please commit your changes or stash them before you merge."
- **Symptom:** First pull of the session refused on two files this session itself had just caused to be modified; upstream had moved (S009/S010 had landed since the last office), so proceeding required recognising that the local mods were self-generated and safe to restore.
- **Root cause:** The kickoff orders Phase 1 (sync + verify + guard install) before Phase 2 (check-in), but `verify` and the guard are not read-only — they mutate tracked ledger files even when nothing is stale. A recycled sandbox (no repo, fresh clone) always hits this: verify rewrites the lock because the source block differs from the vendored state.
- **Suggested fix:** Make `ledger-sync verify` idempotent-silent when the lock already matches the installed core (only write when content actually changes), and/or have the kickoff's Phase 1 note: "if `git pull --ff-only` aborts right after verify on `core.lock`/`STATE.md` and `git diff` shows only verify/regen artefacts, restore those two files and re-pull."
- **Status:** open
