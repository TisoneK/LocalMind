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

- **Session:** 2026-10-27 — Amani / GLM (Z.ai) (S006) — part 7
- **Feature:** provider-failure honesty & the provider-death completion path (roadmap §U item 1, `docs/reference-harness-gap-inventory.md`)
- **Task:** build §U item 1: named error codes surfaced verbatim; retryability honored in the UX (never "try again" when retryable=false; never "switch to a larger model" for a balance failure); provider always named (never "unknown"); failover attempted before dying; and the new rule — when synthesis dies with evidence in hand, the harness delivers what the evidence supports or says so honestly. Must compose with the S471 watchdog (no stall-shaming healthy streams) and preserve the ADR-34 event order.
- **Status:** done — shipped part 7; full suites green; live repro PASS. Next: §U item 2 (identity context injection).
