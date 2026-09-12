# Session 1 — backlog re-row, first office close, new-office re-seed (Amani, 2026-09-12)

Part 1 of this session (the protocol sync to core 1.0.5) is the frozen
office-001 report `history/office-001/reviews/2026-09-12-review-s473.md`.
Sessions count per office (1-20 here), and the live office itself is
unnumbered — an office receives its `history/office-<NNN>` number only when
it freezes. The same continuous session executed the close, so this report
is Session 1's record; the pre-close half keeps office-001's numbering in
the frozen history only.

## What happened

The office was full (447 sessions against a size of 20), and the supervisor
set three tasks: format the backlog in the new core 1.0.5 style, execute the
first-ever `ledger-history close`, and keep a copy of the backlog in the new
office. All three landed, in that order — so the frozen history and the
permanent record both hold the backlog in its new shape, and the new office
opened with the full queue carried over.

## The backlog re-row

The 645-line checkbox file became three priority tables holding 69 open
items — 13 High, 31 Medium, 25 Low — one row per item, each with a stable ID
and a Summary cell that carries everything needed to pick the work up without
chat history. Existing IDs were kept verbatim; the three legacy items that
never had IDs received `B-2026-07-11-1` (Anthropic streaming live-verify),
`B-2026-07-11-2` (monolith decomposition), and `B-2026-08-31-1` (the
context-quality pass). Six rows were deleted because the file itself recorded
them finished — B-2026-08-30-3 (reverted at the owner's direction; its
residual steering is folded into B-2026-09-10-5), B-2026-09-04-1
(RESOLVED `6d4b45e`), B-2026-09-06-2 (RESOLVED `ad4e3fc`, the file's one
checked tombstone), B-2026-09-06-3 (RESOLVED `5a7d3f4`+`cad31f1`),
B-2026-09-06-6 and B-2026-09-06-7 (RESOLVED `5a7d3f4`). The per-session
"update" headers, the 2026-09-02 sweep write-up, and one historical diagnosis
block (verified fixed by S343/346/347) were dropped as narrative; every
deletion is recoverable in git history and now also in the frozen office copy.

## The close

`ledger-history close --confirm` executed cleanly: `history/office-001/`
holds all 447 sessions of the 2026-07-31 → 2026-09-12 office verbatim, and
`history/office-001.md` is its permanent record — what the office built
(parent-only architecture, the verification-first runtime, the latency/token
program including the S471 watchdog, the Thinker program, the bounded tool
surface), the decisions still in force (with the do-not-regress guardrails
carried verbatim), and the open threads. Nothing was zipped to archive; this
was the first close. The dry-run plan matched the execution exactly.

## The re-seed

The new office received, and nothing more: the backlog in full (owner
directive — nothing culled at the re-seed; the next office may prune rows
that no longer matter, with the provenance note saying so), a compact index
of the decisions still in force in `plans/decisions.md` (full ADR text stays
in the frozen office and git), the two still-open protocol asks in the flaws
log (the collab integration step and the roster table-shape lint), one
genuine inefficiency entry, the check-in row, and the session record. Three
things were deliberately NOT carried: the S471 Tier-1 import items (the
owner has not asked to file them — they are named in the permanent record
and the standing Target), the legacy double-entry WARNs (moot on a fresh
log), and Omari's (S472) stale roster row (it froze with office-001; the new
board starts empty, and a returning session re-checks in fresh).

## Shape of the work (derived view — analysis, not stored in the backlog)

69 items → 12 workstreams. This is a planning aid rendered here; the rows
themselves remain the only home of the work.

| Workstream | Items | Estimated Effort |
|------------|-------|------------------|
| 1. Tokens & latency (B-17-8/-9/-11/-12, B-16-8, B-30-8) | 6 | Large |
| 2. Bounded observation contract (B-16-6 + B-17-9's choke-point cap) | 2 | Large |
| 3. Intent routing & steering (B-16-9, B-17-12, B-25-12, B-15-12, B-15-10) | 5 | Large |
| 4. Answer honesty & attribution (B-18-6, B-19-1, B-20-10, B-09-11-2) | 4 | Medium-large |
| 5. Thinker tuning (B-09-06-8, B-09-06-9) | 2 | Medium |
| 6. Code block display (B-23-20 + B-25-10, dedupe; + B-17-4) | 3 | Medium |
| 7. Browser real-CLI verification (B-09-10-5, B-30-12) | 2 | Medium |
| 8. Fast-path context & workspace artifacts (B-25-7, B-09-07-1) | 2 | Medium |
| 9. Search front door (B-09-10-8 owner pick → B-25-2 builds on it) | 2 | Decision-blocked |
| 10. Provider/platform robustness (B-11-1, B-04-2, B-06-10, B-09-09-9; B-06-1 + B-29-1 owner-held) | 6 | Medium |
| 11. Test-suite stability (B-09-09-7 → B-05-4 → B-09-09-1, in that order; + B-06-5) | 4 | Medium |
| 12. Small frontend/tools/memory items (B-08-1, B-10-6, B-23-23, B-12-4, B-20-5/-8/-9/-12, B-25-3/-5, B-09-05-1/-2/-3, B-09-09-8, B-07-11-1/-2, B-07-31-10, B-08-09-12, B-23-30, B-16-5) | 18 | Small each |

Leverage notes: workstream 1 touches every agent turn (highest payoff per
unit risk, and ADR-40 live-verify gates each cut); workstream 11 currently
blocks trustworthy exit-gate baselines, so it should precede any suite-wide
change; workstream 9 is blocked on the owner's grep_search pick; three rows
are "done, pending sign-off" (B-24-13, B-24-14, B-25-6) and leave the queue
the moment the owner approves them.

## Verification

Pre-commit gates passed before every commit (tsc, ruff, conflict-markers,
backlog-dup check). The re-rowed backlog was script-verified: 69 rows, zero
duplicate IDs, zero stray checkbox lines, and exactly three raw pipes per
row (the pipe-escape check that caught one real defect also produced two
false flags before it was written correctly — logged in the inefficiencies
log, together with the truncated multi-heredoc command that briefly corrupted
the session entry, repaired before any commit). The exit gate (full ci-check
+ bookkeeping against this office's logs) ran before the closing commit. No
product code was touched, so the live-testing bar does not apply.

## Open items

None new. The queue is the 69-row backlog plus the owner-decision items named
in the permanent record: the grep_search expose-vs-retire pick, the frontend
vitest determinism pass, whether to file the S471 Tier-1 import items, and
the three pending visual sign-offs.
