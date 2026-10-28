# Current Task (overwrite each session)

Holds exactly one task — the one being worked on right now. Set it at
session start (protocol Step 3), clear it at session end (Step 15). If
you find a stale in-progress entry here, a prior session died mid-task —
its roster row (if left behind) says who was here; check the session
entry and backlog before starting.

<!-- TEMPLATE — replace everything below this comment:
- **Session:** YYYY-MM-DD — <agent> / <model>
- **Task:** <what is being worked on right now>
- **Status:** in-progress | done | blocked (<blocker>)
-->

- **Session:** 2026-10-28 — Amani / GLM (Z.ai) (S006) — part 8
- **Feature:** identity context injection (roadmap §U item 2, `docs/reference-harness-gap-inventory.md`)
- **Task:** build §U item 2 — the model is told who and where the user is before it acts: user-stated name and place plus machine-reported time with its zone as guaranteed injected facts, each labeled with what it is and where it came from; facts the user never stated are declared absent with clarify-don't-guess guidance, never inferred from tool results (fixes F1 at the root — the 12:45 place guess was luck, not a guarantee). Unconditional on every chat path; must compose with the existing user-context fusion (machine deductions stay labeled as deductions, never as the user's statement) and the staged-prompt budget/stability tests.
- **Status:** in-progress — checked in; claimed paths; recon of the injection surface starting
