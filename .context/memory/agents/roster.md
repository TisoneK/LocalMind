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
| Kwame | S431 | glm-5.3-flash | fix phase RELEASED (-3/-6/-7 shipped + ruff-zero + 14-failure clearance, merged 02b42e0); IDLE — awaiting next assignment |
| Mei | S434 | glm-5.3-flash | (same Mei as S433) closed B-2026-09-06-4 (live-verified) + rider -11 conflict-marker gate; released, merging to main |
| Noah | S436 | glm-5.3-flash | S436a right-click menus + S436b export copy-to-clipboard LANDED (fbffcac/e89c3dc/3403e61); live-verified; session closed |
| Amina | S437 | glm-5.3-flash | store hygiene: pytest LOCALMIND_HOME isolation shipped (conftest isolation half of the chat-store pollution item); residue delete-list staged for owner sign-off; released |
| Zuri | S438 | glm-5.3-flash | B-2026-08-30-8 over-thinker: evidence-sufficient answer-only call shipped (live-verified 184.8s→14.1s weather turn); released |
| Sena | S439 | glm-5.3-flash | backlog truth-sweep shipped; CORRECTION: collab-protocol self-correction recorded (event 20260908T022624Z, flaws entry) |
| Tavi | S440 | glm-5.3-flash | collab-init per owner directive (3 agents live): shared session localmind-live-2026-09-08 declared; backlog duplicate-drift verification + guard gate + closeout |
