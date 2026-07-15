# User Preferences (update in place)

How the user likes things done **on this project**. Seeded from
Pre-Flight at bootstrap; grows as sessions reveal preferences —
corrections the user gives, patterns they approve, things they state
outright. This file exists so the user never has to give the same
correction twice.

## Learning rules

1. **Record preferences, not instructions.** A preference is standing:
   it would apply to future sessions ("plain-language changelog
   entries"). An instruction is one-off ("skip the tests this once") —
   it dies with the session and does not belong here.
2. **Every bullet carries provenance** — how and when it was learned:
   `(pre-flight)`, `(stated, YYYY-MM-DD)`, `(correction, YYYY-MM-DD)`,
   `(approved pattern, YYYY-MM-DD)`. An explicit statement or correction
   outranks an inferred pattern.
3. **Current-state file.** When the user changes their mind, update the
   bullet in place and refresh its provenance — don't keep the stale
   version. History lives in the session log, not here.
4. **A session instruction beats a recorded preference for that
   session.** Follow the instruction; afterwards, if it looked like a
   standing change of mind, update this file.
5. **Committed to git — keep it professional.** Working-style facts
   only. Never personal details, never opinions about people, never
   credentials.

## Workflow

- Push to main directly after each commit; one logical change per commit (pre-flight)
- Conventional Commits with scope: `fix(security):`, `feat(api):`, `docs:`, `chore(context):` (approved pattern, 2026-07-11)
- Pull before pushing — other agents or the user may have pushed (approved pattern, 2026-07-11)
- Set local git config (`user.name`, `user.email`) before the first commit on cloud/sandbox — identity must match `memory/user/identity.md`; the sandbox default identity is never the user's (correction, 2026-07-15 — Sessions 9–10 shipped commits as `Z User <z@container>`, fixed in Session 11 by rebasing with `--reset-author`)

## Communication

- Plain-language changelog entries (grandmother test); technical detail in review reports, not the changelog (approved pattern, 2026-07-11)
- Reports go in `.context/memory/reviews/` (was `docs/report/` — migrated 2026-07-11; path updated to `memory/reviews/` on 2026-07-15 core 0.2.0 migration) (correction, 2026-07-11; updated 2026-07-15)
- Chat summary at session end: one paragraph + commits + findings + open items (approved pattern, 2026-07-11)

## Code style

- Comment the why, not the what (approved pattern, 2026-07-11)
- DRY — use shared helpers, don't reinvent (e.g., `human_size` extracted to `core/utils.py`) (approved pattern, 2026-07-11)
- Follow existing architecture and conventions unless there's a compelling reason to improve them (approved pattern, 2026-07-11)

## Review depth

- Fix safe issues (typos, doc mismatches, missing validation, dark-mode gaps, type annotations, DRY refactors, accessibility, SSRF hardening) (pre-flight)
- Flag architectural changes (provider config consolidation, module decomposition, theming strategy) for approval — document in backlog, don't implement (pre-flight)
- Deep-scan: when you find a bug, grep for the same pattern across the whole codebase and fix all instances in one commit (approved pattern, 2026-07-11)

## Risk & approvals

- Never bump a major version without flagging it (approved pattern, 2026-07-11)
- Security fixes can be applied directly if safe (regression test included); flag risky security rewrites (approved pattern, 2026-07-11)
- PAT goes in chat, never in uploaded files — the upload pipeline redacts secrets (correction, 2026-07-11)
- Rotate the PAT after each cloud-agent session (approved pattern, 2026-07-11)
