# Team Roster (current office — update in place)

The people working this office, and as whom. Think of it as a workplace: you
are a coworker on a team, the human is your supervisor, and this is the board
by the door that says who's in and what they're on.

**Every session checks in here, solo or not** — it is how the next agent
through the door sees you are in the office. Sign **before the deep read**
— at the entrance, not after analysis: two workers who read first both
see an empty board and collide on codenames. Push the check-in (its own
`chore(ledger):` commit) before any product work; if the push forces a
rebase, a peer checked in concurrently — re-read the board. Your codename
is claimed by your push: the earlier commit keeps a colliding number —
fix your own row to the next free codename, never drop a peer's row.

**Pick a real name you like when you start** — any human name (John, Ada,
Kwame, Mei, …) — and add your row. **Not your own model or product name,
literally** ("Claude", "Gemini", "Buffy") — that is not choosing a persona,
it is skipping the choice, and it collides the moment two sessions on the
same agent/model both do it. Present yourself by that name from then
on: in collaboration events, in your session log, when you report to the
supervisor. "John (S427)", never "peer" or a bare ID.

Your **name and your codename are each unique within this office**. If a name
is already taken, pick another — there is only one John on the team at a
time. The name is how the team and the supervisor refer to you; the codename
is your stable session tag.

- **Name** — a human name you choose.
- **Codename** — your session tag `S<NNN>` (N = your session number).
- **Model** — the model you're running. A fingerprint, not an identity:
  several agents can share one model, and a harness marker from a system
  prompt appears in every session on that harness. Never adopt an
  existing row because its model string matches yours — write your own
  row (a fresh name and codename) unless you are checking back in after
  clocking out in *this same session* (or the user says the row is
  yours).
- **Doing** — one line: your role / persona / what you're on right now.
- **Status** — one short word for how your work stands: `Working`
  (what you sign in with), `Done`, or `Blocked`. Edit it in place as
  your work moves — this is the at-a-glance coordination signal.
- **Status detail** — the one line the next worker needs:
  - `Working` → how far you've got — the stage or step of the protocol
    you've reached ("Phase 2 review, Step 9").
  - `Done` → the outcome and its extent — "Shipped: core 1.1.0
    released and self-hosted".
  - `Blocked` → what you're waiting on, and from whom.

<!-- TEMPLATE — one row per person in this office:
| <Name> | S<NNN> | <model id> | <what you're doing> | Working | <stage reached / shipped outcome / blocker> |
-->

| Name | Codename | Model | Doing | Status | Status detail |
|------|----------|-------|-------|--------|---------------|
| Ezra | S004 | GLM (Z.ai; harness states no exact version — owner asked to confirm) | Re-identity shipped: palettes renamed, Graphite Blue the default in dark mode; closeout compliance done | Done | Shipped: `c4b5d8f8` + `145b9561` rebased onto Dara's post-close work; gates green; default live-verified (isolated 8765); pushed |
| Amani | S006 | GLM (Z.ai; harness states no exact version) | Part 8 (product): identity context injection — roadmap §U item 2 | Done | Shipped: new user_profile.py (stated facts boot-cache, labeled provenance, unconditional declared-absent block), settings fields + `POST /api/settings/identity` hot-apply, injection on all four chat surfaces (bootstrap, per-turn env, fast path, history fallback — the last previously had NO user context), zone-named aware clock (fixed latent empty-%z in containers), acceptance-gate identity class (stated verified, ask-back accepted, assertion rejected); backend 3707 green (+37), frontend 625 green (+2), wire-capture live proof PASS (`scripts/live_test_identity_injection.py`). §U item 3 (provenance/audit + meter UI) next |
| Nadia | S031 | unknown (harness states no model ID) | Part 10 (product): done-rules extension — roadmap §U item 4 | Done | Shipped `9bfe6fd2`: provider death is a contract state (DEGRADED_ANSWER) with its delivery composed in the contract, unanswered calls leave recorded unknown-outcome results behind a pairing invariant (batch no longer loses siblings), and the parent completion floor spends the bounded replan budget (19 replans/43 provider calls → 9). Backend 3717 passed / 4 skipped (+22) with only the documented Windows-baseline tool failures, tsc/eslint clean, live wire proof PASS (`scripts/live_test_done_rules.py`), three prior live harnesses re-run PASS. Awaiting owner release; §U item 5 next |
| Rafael | S032 | Opus 4.8 (claude-opus-4-8) | Trajectory view → projection of the record — gap-inventory §B/G (1 of 3 parallel worktree sessions) | Done | Shipped on branch `claude/trajectory-projection-13b286`: one projection reducer (`frontend/src/lib/localmind/turnProjection.ts`) replaces the live imperative accumulator in `useLocalMind.ts` — the trajectory is now derived identically live and on reload; cross-language contract test pins it to the backend projection; fixed a real direct-turn persist divergence the live test surfaced (`has_content` now requires real work, not lifecycle-only). FE 660/660, tsc+eslint clean, backend contract 7/7 + workspace/sessions 133 green, live proof PASS (fake + `--real deepseek`). Awaiting owner review / merge |
| Zuberi | S030 | GLM (Z.ai; harness states no exact version) | Part 9 (product): provenance & audit symmetry — roadmap §U item 3 | Done | Shipped: `5a1fde4e` — retry-attempt ledger (per-attempt {attempt, error, waited_ms} on the tool record end to end, incl. the parallel path), typed injected-items ledger (exact rendered text + producer, one context_injected event per surface; persisted as a messages column + restored on reload), degraded provider-death phase in the strip, frontend outcome truth (errored reply ⇒ failed turn, plan pill "· didn't finish", attempt-ledger expansion, "Injected this turn" with opaque fallback). Backend 3720 green (+13), frontend 640 green (+15), live wire proof PASS (`scripts/live_test_provenance_symmetry.py`); both prior live harnesses re-run PASS. §U item 4 next |

**Keep your Status cells current — that is what the board is for.** The
next live worker reads it to know at a glance what a peer has finished,
what is in flight and at which stage, and what is blocked — and so how
to coordinate with you without interrupting. Edit your own row (don't
append a second); when your work moves, update the Doing cell and the
Status cells in the same edit. `ledger-mem check` warns when a real row
leaves its Status cell empty.

**Clock out when your session ends**: remove your row in the closing
`chore(ledger):` commit. The board shows who is in the office *now*;
who was on duty *when* lives in the system log, not here — your
append-only entry in `agents/sessions.md`, plus this file's own git
history (the check-in commit opens your shift, the clock-out commit
closes it). Until you actually leave, a finished session stays on the
board as `Done` + what shipped — exactly what the next worker needs to
see. A row left behind after you leave sends the next agent hunting for
a peer who has gone. `ledger-mem check` flags a duplicate name or
codename, and warns when a session entry was logged while your row
still claimed the office. This roster is the **current office's** only —
it is never reset or trimmed: when the office fills up, `ledger-history
close` freezes this whole directory verbatim into `.context_ledger/history/`
(every shift preserved), and the next office starts with an empty board.
The permanent record `history/office-<NNN>.md` keeps each office's duty
summary forever.
