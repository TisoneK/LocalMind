# Review — 2026-09-16 — Chemi / Qwen3.8 Flash (S013) — Backlog triage to the core 1.2.0 cap

## Task

Supervisor directive to Chemi (S013), checked in pre-9:00: triage the office
backlog against the core 1.2.0 cap (warn-only) — split knowledge into
`tasks/parking-lot.md`, prune done/stale rows, keep ≤ 20 actionable rows.

## What shipped

Commits: `f3bdb530` (resume: scope claim + current task), `3a009e02` (the
triage), plus the closing bookkeeping commit. Zero product files touched —
the live-testing bar does not apply.

- **`tasks/backlog.md`:** 84 rows → **20 actionable rows** (5 High / 8 Medium /
  7 Low), written from Chemi's own 15:03 draft (`scratch/backlog-new-s013.md`,
  found mid-resume) verbatim, LF-normalized. Her provenance paragraph was
  corrected to the shipped reality: P-2026-09-16-1…-59 (not -61), five
  whole-row deletions (not four-plus-phantom-P-56), merged pair at
  P-2026-09-16-26.
- **`tasks/parking-lot.md`:** **59 rows** parked — 6 advisory/awaiting-owner
  under *Open questions* (B-2026-08-23-23/-30, B-2026-08-29-1, B-2026-09-06-1,
  B-2026-09-10-8, B-2026-09-15-12), 53 under *Deferred work* — each keeping
  its original B- ID **in-row** via a provenance tail
  (`(parked 2026-09-16 by Chemi/S013; was B-…)`), so the dozens of
  cross-references between rows stay resolvable. B-2026-08-25-2 +
  B-2026-08-25-10 merged into one row (P-26) per the draft's "one merged pair".
- **Deleted as done/stale, on the file's own recorded evidence** (the Session 1
  re-row precedent): B-2026-08-24-13, B-2026-08-24-14, B-2026-08-25-6 (all
  "DONE … done, pending user visual sign-off"); B-2026-08-24-8 (standing
  practice, codified in the verification bar — not a task);
  B-2026-08-30-8 (over-thinker half shipped `bd0641d`; the remaining
  "remember \<url\>" detector gap is noted in the backlog's provenance
  paragraph rather than parked as a phantom row).

## Verification

- Triage executed by a script written to disk (office lesson: no inline
  heredocs), which asserted before writing: parked bodies **byte-identical**
  to the pre-triage originals modulo the ID cell + provenance tail; zero
  `| B-` leaks into either output; P-census exactly P-…-1..59; backlog
  keep-set exactly the draft's 20; raw-pipe shape 3 per row (escaped-pipe
  safe, raw-pipe counting per the 2026-09-12 lesson).
- `ledger-mem check` green — the backlog-cap warning (84 rows, standing since
  Session 11) is **cleared** (20 ≤ cap).
- Pre-commit gate green (conflict-markers, backlog-duplicates; tsc/ruff not
  applicable to a markdown-only diff).
- Two defects were caught and fixed **before** anything shipped: a parser that
  could not validate a single-line row at EOF, and an aliasing bug that built
  orphan duplicate lines into the parking lot (working tree rebuilt from git
  HEAD; the clean rerun verified 0 errors).

## Session notes

- Resume continuity: the roster row + scratch draft established this as the
  same session (supervisor's word), so no second check-in identity was taken;
  the claim event and this entry extend S013.
- The session's Bash tool dropped a heredoc code-fence marker and doubled one
  `\u` escape mid-session — both pre-existing Windows-box traps, now logged
  first-hand in the inefficiencies log.
