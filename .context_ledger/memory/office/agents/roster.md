# Team Roster (current office — update in place)

The people working this office, and as whom. Think of it as a workplace: you
are a coworker on a team, the human is your supervisor, and this is the board
by the door that says who's in and what they're on.

**Every session checks in here, solo or not** — it is how the next agent
through the door sees you are in the office. Push the check-in (its own
`chore(ledger):` commit) before any product work; if the push forces a
rebase, a peer checked in concurrently — re-read the board.

**Pick a real name you like when you start** — any human name (John, Ada,
Kwame, Mei, …) — and add your row. Present yourself by that name from then
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

<!-- TEMPLATE — one row per person in this office:
| <Name> | S<NNN> | <model id> | <what you're doing> |
-->

| Name | Codename | Model | Doing |
|------|----------|-------|-------|

**Clock out when your session ends**: remove your row in the closing
`chore(ledger):` commit. The board shows who is in the office *now*;
who was on duty *when* lives in the system log, not here — your
append-only entry in `agents/sessions.md`, plus this file's own git
history (the check-in commit opens your shift, the clock-out commit
closes it). A row left behind sends the next agent hunting for a peer
who has left. `ledger-mem check` flags a duplicate name or codename,
and warns when a session entry was logged while your row still claimed
the office. This roster belongs to the **current office** only — it is
never reset or trimmed: when the office fills up, `ledger-history close`
freezes this whole directory verbatim into `.context_ledger/history/`
(every shift preserved), and the next office starts with an empty board.
The permanent record `history/office-<NNN>.md` keeps each office's duty
summary forever. Update your own row (don't append a
second); when your work changes, edit the "Doing" cell.
