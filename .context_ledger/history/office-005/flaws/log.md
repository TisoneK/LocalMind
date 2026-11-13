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

## 2026-11-02 — Tobias / unknown (no model ID)

- none this session

---
## 2026-11-02 — Zuri / GLM (S023, office-004 lineage numbering)

- **Flaw:** the ledger CLI (`ledger-collab emit`, `ledger-state generate`) does not anchor to the HOST PROJECT's vendored office in this sandbox — `emit` wrote S023's events into `/home/z/my-project/context-ledger/memory/collaboration/events/` (the core repo's own memory tree) and `generate` refuses with "no memory/office/ directory" even when run from inside `<project>/.context_ledger/`.
- **Symptom:** `ledger-collab emit` printed a success path that did not exist under the project's `.context_ledger/`; the release event was invisible to `ledger-collab check` run from the project; `ledger-state generate` could not regenerate the project's STATE.md at clock-out (S023's STATE still shows Tobias's regeneration). S022's events are similarly absent from the vendored office.
- **Root cause:** the CLI resolves the office from its own install tree (or an unexported env default) instead of the CWD's `.context_ledger/`, so a self-hosted core + vendored-consumer setup silently forks the collaboration trail across two trees.
- **Suggested fix:** the CLI should anchor the office at the nearest `.context_ledger/` walking UP from CWD (and refuse loudly when none is found), so vendored consumers get the same trail the core's own office gets; a `--office <path>` flag would cover the rest.
- **Status:** open (workaround used this session: the two S023 events were copied into the vendored office and the core-side copies deleted; STATE left at the last successful regeneration — the roster/sessions/events carry the record).

## 2026-11-02 — Tobias / unknown (no model ID) — pull again

- none this session
