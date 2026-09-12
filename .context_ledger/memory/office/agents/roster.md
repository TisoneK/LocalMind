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
| Kojo | S471 | glm-5.3-flash | Diagnosing owner-reported glm-5.3-flash >60s silent thinking in chat (bankofai) vs qwen3.8-flash |
| Omari | S472 | glm-5.3-flash | Frontend: thinking-block UI does not format the LLM's thought (peer Kojo S471 owns the backend side) |
| Buffy | S472 | deepseek-v4-flash | B-2026-09-10-8: assess grep_search (no model-facing tier) — expose vs retire, recommend with evidence |

<!-- Clock-out 2026-09-11: Buffy (S472) — B-2026-09-10-4 CLOSED: the date-bomb
family (3 tests) now derives its grounded/fabricated date answers from the
clock, and a new TestDateIndependence pin walks the checker's `now` seam over
every weekday plus the month/year boundaries (product a3988fc; backlog line
deleted). Verified: 3 failed -> 86 passed on the two files; full suite 3106
passed / 2 skipped / 0 failed; the real parent gate driven under 13 frozen
clocks (backend/scratch/s472-date-probe.py). This was the sole pytest red on
every exit gate since S458, so the office's exit gate is clear of it. Second
find, FIXED on discovery in the same session: the exit gate's
check-bookkeeping.sh had been a silent no-op since the 1.0.0 office migration
(stale pre-migration path -> "no dated session entries yet — skipping" ->
PASSED over a 6,770-line sessions.md); product 3658cfd takes the office root
as an input with hard failures (rc=2 missing argument/dir, rc=1 missing log),
registry 6fa762f passes it, flaw logged with the class-level ask. Exit gate
re-run GREEN end-to-end (ci-check PASSED; bookkeeping now actually evaluating).
Collab: session localmind-datebomb-fix-20260911 — notes 57a5cef1/3974c14c,
claims 1c0dd283/33252d65, releases 7e0ce5e0/44d6c7e5; check green, no open
claims; tasks/current.md untouched (Kojo's live S471 task). Board: Kojo (S471)
stays — a peer is in the office. Session number: S472 was taken CONCURRENTLY by
Omari (Windows checkout) — the protocol's concurrent-number rule applies (tell
sessions apart by agent + timestamp), so the two S472 entries in sessions.md
are distinct sessions, not a duplicate. -->

<!-- Clock-out 2026-09-11: Jabari (S470) — context sync complete: core 1.0.2 → 1.0.4
(via S469's pull + same-MAJOR update from the tison-side package clone; core.lock
churn-free). THE S467/S468 Windows gate-teeth flaw VERIFIED FIXED on the vendored
core: two real-repo red exit-gate runs (documented 22 baseline + 3 tracked date
bombs) end "ledger-gates: exit gate failed" + wrapper rc=2 with NO GATE PASSED
line; flaws log carries the closure (904cefc8). Interim read-stdout rule retires
on cores ≥ 1.0.3. Exit gate run BEFORE this closing commit per the S462
sequencing: sole red = the tracked date-bomb trio. Board empty = nobody in the
office. -->

<!-- Clock-out 2026-09-11: Zawadi (S469) — B-2026-08-25-4 fixed and live-verified
(78fadbcc fix + 14 tests, bb9555b1 changelog, b6203c2a review/release/backlog):
the internal worker-report append was re-entering the model's context via the
history feeds and the model mimicked it into answers; one strip helper beside
the format owner now guards every model-facing history feed + emission
boundary, fallback preserved. Live before/after on bankofai/qwen3.8-flash:
pre-fix readback reproduced the report from context, post-fix never. Suite =
baseline + tracked date-bomb trio. Claim fdedccf3 released; worktree/junction
torn down, venv verified. Board empty = nobody in the office. -->


<!-- Clock-out 2026-09-11: Amir (S468) — protocol sync to core 1.0.2 landed
(5ef36cb5; templates unchanged, entry points left as S467 regenerated them).
Gate-teeth flaw RE-VERIFIED OPEN on 1.0.2 (1.0.1 fix closes the piped-consumer
case only; Run-One child stdout still masks the verdict — probe + real
pre-commit + this session's exit gate all demonstrate FAILED (N) → GATE
PASSED + rc=0). Second finding fixed: gates.conf dup-check line was dead
(silently red since the 1.0.0 migration) — re-pointed to the office backlog
(5d959367), green. Inefficiency logged: my own invalid non-repo scratch probe
briefly produced a false closure, rewritten pre-commit. Exit gate (before this
closing commit): verify OK, diff-check + bookkeeping green; ci-check's sole
red = the tracked B-2026-09-10-4 date-bomb trio. Board empty = nobody in the
office. -->

<!-- Clock-out 2026-09-11 (second): Asha (S467) — core 1.0.0 adopted with
owner go-ahead: update + office migration clean (fbe59fa2/ddc9843b), entry
points regenerated (58690ba0), bookkeeping b249b366. Exit gate re-run BEFORE
this closing commit per the S462 sequencing: sole red = the tracked
B-2026-09-10-4 date-bomb trio; gate rc untrusted (flaw re-verified open in
1.0.0). Board empty = nobody in the office. -->

<!-- Clock-out 2026-09-11: Asha (S467) — context sync complete: main ==
origin, core OK 0.22.0, registries refreshed, session record + flaw landed
(8d4e9060). Exit gate re-run BEFORE this closing commit per the S462
sequencing: sole red is the tracked B-2026-09-10-4 date-bomb trio; gate rc
untrusted (flaw logged this session — Windows port swallows stdout-emitting
failures). Board empty = nobody in the office. -->

<!-- Clock-out 2026-09-11 (final): Njeri (S462) — re-checked in for the
exit-gate leftovers; all four were landed first by Elena (S464) and my
superseded local commit dropped via rebase --skip. Verified merged tree
(45 pass / 1 skip targeted; full ci-check = documented baseline + the
tracked date-bomb family only); tsc/eslint/core-verify/bookkeeping green.
Flaw logged: protocol does not sequence clock-out after the exit gate.
Feature explorer-tool COMPLETE. Board: empty = nobody in the office. -->

<!-- Clock-out 2026-09-11: Zuri (S465) — benchmark suite extended + live run:
per-adapter model pin + --adapter/--model + multi-turn + usage capture + new
MEMC/KIT/REC categories (b02c3525/71ab798e); 13 tests live on
bankofai/qwen3.8-flash — 9 PASS / 4 PARTIAL / 0 FAIL (PARTIALs: 3× CAT1
thinking-exposure on the weak model, CAT15-1 provider stream error mid-turn
with the fallback contract held). Finding B-2026-09-11-1 (done event carries
no provider_usage). Flaw: rebase --continue bypassed the marker gate (stray
marker fixed 86050a4d). Worktree torn down, branch merged, claim released.
Board empty = nobody in the office. -->

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
