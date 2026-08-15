# Current Task

- **Session:** 237 — **IN PROGRESS** (Claude Code / claude-opus-4-8, local, macOS)
- **Feature:** Thinker — live diagnosis + fix (ADR-36/37)
- **Why me:** I have the zen key working locally, so I can RUN the provider
  and observe the real Thinker behavior (ADR-36 says live-model validation
  is mandatory; prior sessions couldn't run it). User: "it didn't fix
  anything — fix the Thinker." B-5 (depth) is committed+validated by Buffy
  but the real flow still isn't right.
- **Plan:** live-trace the 3 tiers (hi / what can you do / list dev folder),
  observe where the Thinker assessment does/doesn't surface + tier-2
  over-triggering execute, then fix based on observed behavior + re-validate.
- **Coordination:** Buffy may also be on the Thinker — git clean + no prior
  lock when I started. Reconcile on push.
