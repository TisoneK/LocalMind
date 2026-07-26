# Protocol Overrides (update in place — project-owned)

Project-local adjustments to the protocol. Sessions read this file
right after loading their edition; where an override and the edition
conflict, **the override wins** — except the two rules nothing can
override: secret handling and append-only guarantees.

Overrides are standing, project-shaped deltas — not session
instructions (those die with the session) and not user preferences
(those live in `../user/preferences.md`). Core updates never touch
this file: customizations here survive every core version bump.

<!-- TEMPLATE — one bullet per override, with provenance:
- **<what the protocol says>** → **<what THIS project does instead>** —
  <why> (set by <user/agent>, YYYY-MM-DD)

Example:
- **Push to main after each commit** → **push to the `develop` branch;
  main is release-only** — repo uses git-flow (set by user, 2026-07-14)
-->

- **No `memory/features/` module exists in core 0.2.0** → **LocalMind adopts the 0.3.0 feature-scoped memory design as a project-level preview.** `memory/features/ledger.md` (append-only, one line per feature ever), `memory/features/<slug>/manifest.md` (update-in-place), `memory/features/<slug>/notes.md` (append-only while alive), and `memory/features/archive/` (cold storage) are in force now, ahead of core. The `tasks/current.md` template gains a `Feature: <slug> | none` line. Reading order gains, after `tasks/current.md`: skim `features/ledger.md`, then read the active feature's manifest + notes (only the feature named in `tasks/current.md`). Exit checklist gains: update the active feature's manifest; on merge/abandon, complete the ledger line. **The ledger rule applies in full** — a feature directory may be archived or deleted only after its ledger line records the outcome. The append-only guarantee on the ledger itself is one of the two rules nothing can override. When core 0.3.0 ships, this override becomes redundant and may be removed. (set by Super Z / GLM-5.2, Session 13, 2026-07-26; design spec: `TisoneK/.context` `designs/feature-scoped-memory.md`)

- **`memory/tasks/current.md` template in core 0.2.0 has no `Feature:` line** → **LocalMind's `tasks/current.md` includes `Feature: <slug> | none` ahead of core.** Hotfix- and chore-sized sessions use `Feature: none` and touch no feature directory — they write the global logs exactly as in 0.2.0. Multi-session work gets a feature. (set by Super Z / GLM-5.2, Session 13, 2026-07-26)

- **ADR template in core 0.2.0 has no `Author:` line** → **LocalMind's ADRs include `- **Author:** <agent> / <model> (Session N)` ahead of core.** Per the 0.3.0 design's "folded-in small fix" — every other template carries the author line, ADRs were the one record type without it. (set by Super Z / GLM-5.2, Session 13, 2026-07-26)

