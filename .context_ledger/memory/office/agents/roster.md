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
- **Codename** — your session tag. Use the structured form
  **`OF<oo>SS<ss>`**: office number + session number
  (e.g. `OF01SS07` = office 1, session 7). The office number is how many
  offices have been frozen into `.context_ledger/history/` plus one (the
  current office); the session number is the next free one (the board's
  highest plus one, cross-checked against the last `Session N` in
  `agents/sessions.md`). This makes a codename unique across offices and the
  whole fleet, not just within this board. Legacy office-local `S<NNN>`
  codenames are still valid and still read everywhere — don't rewrite old
  rows — but new sessions take the structured form.
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
| <Name> | OF<oo>SS<ss> | <model id> | <what you're doing> | Working | <stage reached / shipped outcome / blocker> |
-->

| Name | Codename | Model | Doing | Status | Status detail |
|------|----------|-------|-------|--------|---------------|
| Tobias | S001 | unknown (harness states no model ID) | Pull the latest main and verify the Planner lane | Working | Checked in; Planner lane pulled at 8dbac565, verification next |

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
| Zuri | S023 | GLM (Z.ai sandbox) | The owner's 2026-11-02 "How are things" export: the task list is still tool-echo (`syn-0`), the output is messy — fix all | Done | Shipped (this commit): the Planner lane — the runtime now draws the real `{todo, outcome}` plan by model on every task turn (fail-open lane, thinking-off@12s; social/open-question/goal/sequence turns step aside), plan_outcomes seed the panel contracts AND the acceptance gate's criteria, plan_objective renders as the UNDERSTANDING context; B-2026-11-02-2's adaptive revision (gate-replan diff → `retired` status carrying the discovery + `todo_revised {added, retired, kept}`, once per turn, closed rows never churn) + the objective-fidelity lane (FAITHFUL/DRIFTED, post_answer_lanes, one nudge, never blocks); the Thinker's fenced JSON rehearsal is stripped from the visible reasoning across chunk boundaries. 4,060 backend tests (13 new), e2e 132, frontend 678 + tsc, ruff clean; NEW live harness ALL PASS + 11 standing harnesses clean + eval 13/13. Five count-routed harness fakes migrated to content-routing (the lane adds one call before the loop). |

