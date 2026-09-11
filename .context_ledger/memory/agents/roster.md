# Team Roster (current group — update in place)

The people working this group, and as whom. Think of it as a workplace: you
are a coworker on a team, the human is your supervisor, and this is the board
by the door that says who's in and what they're on.

**Pick a real name you like when you start** — any human name (John, Ada,
Kwame, Mei, …) — and add your row. Present yourself by that name from then
on: in collaboration events, in your session log, when you report to the
supervisor. "John (S427)", never "peer" or a bare ID.

Your **name and your codename are each unique within this group**. If a name
is already taken, pick another — there is only one John on the team at a
time. The name is how the team and the supervisor refer to you; the codename
is your stable session tag.

- **Name** — a human name you choose.
- **Codename** — your session tag `S<NNN>` (N = your session number).
- **Model** — the model you're running.
- **Doing** — one line: your role / persona / what you're on right now.

<!-- TEMPLATE — one row per person in this group:
| <Name> | S<NNN> | <model id> | <what you're doing> |
-->

| Name | Codename | Model | Doing |
|------|----------|-------|-------|
| Elena | S464 | deepseek-v4-flash | Closing the exit gate: three more dir_explorer wiring leftovers surfaced by `ci-check` |
| Zuri | S465 | glm-5.3-flash | Benchmark live run — model override + efficiency metrics for the suite, live test subset on Windows |

<!-- Clock-out 2026-09-10: Elena (S464) — dir_explorer live-tested on
bankofai/qwen3.8-flash (the protocol's PRIMARY provider): 3/3 new-capability
picks PASS + system_search/shell non-regression PASS; the carried content-search
question ANSWERED (no explorer bleed, so the LONG_TAIL fallback is not needed)
and the explorer-tool feature line COMPLETED. The failing grep_search
expectation turned out to be a PRE-EXISTING wiring gap — grep_search sits in no
model-facing tier at all → B-2026-09-10-8. Two fixes shipped: the phantom
grep_search pointer dropped from the dir_explorer description, and the stale
CORE tool-count pin corrected. The harness gained a per-adapter model pin
(bankofai's configured default deepseek-v4-flash is delisted). Solo light path:
claim f769fae7 → release 8604b14b, check green, all claims resolved. Session
logged, current idle. Board empty = nobody in the office. -->
>>>>>>> 3cbac1db (chore(ledger): Zuri (S465) checks in — benchmark live run (suite metrics + live subset))

<!-- Clock-out 2026-09-10: Njeri (S462) — explorer-tool SHIPPED:
dir_explorer {list,tree,stat} + wiring + 22 tests (9d85df0f), Explorer UI
alias (de3ae4b3), live harness (df29d81d/64206dc6); weak-model gate PASS
on zai (3/3 picks + system_search/shell non-regression), grep_search
verdict carried B-2026-09-10-7 (zen down / bankofai quota empty). Solo
light path closed: claim c00bfe9e → release 28a18e4c (first release
249781fc published malformed — permanent check noise, flaw re-logged).
Session logged, current idle. Board empty = nobody in the office. -->

<!-- Clock-out 2026-09-10: Juma (S463) — B-2026-09-10-2 closed: duplicate
B-2026-09-09-8 renumbered (server-death item to B-2026-09-09-9, landed-first
rule), B-2 line deleted, session logged, claim released, collab check green.
Board shows Njeri (S462) still in the office — implementation in progress. -->

<!-- Clock-out 2026-09-10: Thabo (S461) — protocol sync to core 0.22.0
landed (migration 40aa398c; entry points refreshed — collab README caught
up two releases; closeout dry run zero tombstones; first solo JSON
claim→release emitted, check green). Session logged, current idle. Board
empty = nobody in the office. -->

<!-- Clock-out 2026-09-10: Theo (S460) — backlog tombstone sweep complete
(250 done lines + 9 stale pointers deleted, 7 [x]->[~], B-2 half, B-3
teardown; B-2026-09-10-1/-3 closed and their lines deleted), session
logged, claim released. Board empty = nobody in the office. -->

<!-- Clock-out 2026-09-10: Amara (S459) — Explorer tool design finalized
(dir_explorer {list,tree,stat}; 0ec563bd), owner decisions applied, session
logged, current idle. Implementation session owns the feature manifest next. -->

<!-- Clock-out 2026-09-10: Kofi (S458) — protocol sync complete (core 0.21.0
applied, a969390e; entry points refreshed; logs appended). Board empty =
nobody in the office. -->

<!-- Board audit 2026-09-09 (Iris S457 check-in): Ravi's (S456) row removed —
owner confirmed it stale. S456 was a context-sync session on a different
machine (Windows ZCode), logged complete in sessions.md, no live work here on
macOS. Iris worked solo. -->
<!-- Clock-out 2026-09-09: Iris (S457) — P0 Step 4 slice 2 shipped (350d19a),
session logged, current idle. Board empty = nobody in the office. -->

`ledger-mem check` flags a duplicate name or codename. This roster is the
**current group's** only — it resets when the group closes
(`ledger-history close`), and the closed group's roster is kept in
`.context_ledger/history/`. Update your own row (don't append a second); when your
work changes, edit the "Doing" cell.

<!-- Clock-outs 2026-09-08 (S442 board audit, context-mem check): the
S430–S441 rows were removed — all nine sessions have completed entries in
agents/sessions.md and no live work; who was on duty stays in sessions.md
and this file's git history. Nadia (S442) clocked out at closeout the same
day. Board empty = nobody is in the office. -->
