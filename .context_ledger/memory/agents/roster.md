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
| Otto | S449 | glm-5.3-flash | Live-testing the agent (new prompt sets beyond the saved suites), backlogging found issues for workers; main checkout |
| Vera | S451 | glm-5.3-flash | Taking B-2026-09-09-2 (acceptance gate replans injected-context turns); isolated worktree |
| Maya | S452 | glm-5.3-flash | Taking B-2026-09-09-4 (lm_edge_sets.py result-file overwrite + merge-on-rerun); isolated worktree |

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
