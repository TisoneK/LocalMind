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

`context-mem check` flags a duplicate name or codename. This roster is the
**current group's** only — it resets when the group closes
(`context-history close`), and the closed group's roster is kept in
`.context/history/`. Update your own row (don't append a second); when your
work changes, edit the "Doing" cell.

| Ada | S430 | glm-5.3-flash | core sync 0.16.0 -> 0.16.1 patch (same Ada as S429; supervisor: rename me here if you like) |
| Kwame | S431 | glm-5.3-flash | FIX phase on session localmind-chat-hygiene (owner resumed my deleted run): claimed -3 export v3 + -6 markdown previews + -7 Agent-Workspace copy (yielded -2 implementation to Mei; backend additive pass rebases after her merge) |
| Mei | S433 | glm-5.3-flash | closed B-2026-09-06-2 (commit ad4e3fc): deterministic epilogs now persist the user message; released + merged to main |
