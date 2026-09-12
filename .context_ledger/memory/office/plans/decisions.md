# Architectural Decisions (append-only, ADR-style)

Decisions already made — future agents respect these rather than
relitigating them. To reverse one, append a new ADR that supersedes it.

<!-- TEMPLATE — copy below the last entry:
---
## ADR-N: <short title> (YYYY-MM-DD)
- **Status:** accepted | superseded by ADR-M
- **Context:** <what forced the decision>
- **Decision:** <what was decided>
- **Consequences:** <trade-offs accepted; what future agents must respect>
-->

---

## Carried from office-001 (closed 2026-09-12) — decisions still in force

- **Index:** the full ADR text (ADR-1 through ADR-61; note two same-day number
  collisions inside the frozen file — ADR-54 and ADR-58 each appear twice) is
  frozen verbatim at `history/office-001/plans/decisions.md` and preserved in
  git history. Do not relitigate; to reverse one, append a superseding ADR here.
- **Binding guardrail set (from `memory/workflows/active.md`, carried verbatim):**
  the ADR-34 event order; the `Hi`→zero-provider-call boundary (S206); the
  Session 31-33 fixes that thinking-aware timeouts build on; ADR-40 (live-verify
  tool SELECTION on a flash-tier model + cerebras before any further schema cut);
  ADR-41 (z.ai thinking ON — never re-add a thinking-disable for GLM; timeout
  scaling is the lever); the S471 watchdog fall-through (once a first byte lands
  the heartbeat returns to the truthful prior branches — never stall-shame a
  healthy stream); the Parent-only scope (ADR-53).
- **Core to this office's work:** ADR-18 verification-first; ADR-37 one path,
  no narration layer (Direct Mode removal = open item B-2026-08-15-10, a
  pending product call); ADR-46 execute opt-in, never fail-open; ADR-38
  evidence-first; ADR-57 loop discipline (do NOT reintroduce serial every-tool
  consults — S420; do not await in-flight consults at turn end); ADR-59
  no-machinery Thinker prose; ADR-60 concurrent consults; ADR-61
  evidence-sufficient answer-only calls (never gate loop optimizations on the
  `intent` parameter — it is constant on the parent path); ADR-40 tiered
  schemas + describe_tool; ADR-43 bounded tools; ADR-14 single front door +
  thin dispatcher; ADR-52/54/55 ParentSession; ADR-39 prompt caching; ADR-10
  capability families additive; ADR-6 developer agents preserved; ADR-1
  dark-only; ADR-2 SSRF redirect re-validation; ADR-28 first SSE event is
  transport acknowledgement.
- **Working agreements:** the live-testing bar is MANDATORY for loop/tool/
  adapter changes (`system/live-testing.md`; report live-verified vs
  unit-tested vs assumed); cure the disease, not single prompts; model-agnostic
  + env-agnostic fixes — "there is no weak model" (neutral terms only); push to
  main after each commit; two-surface commit prefixes, never mixed; solo
  sessions run the light path (claim → work → release); roster check-in every
  session; never port 8000 (the user's app runs there) — isolated 8765 +
  LOCALMIND_HOME only; no secrets in tracked files, ever.
- The permanent summary of what the previous office accomplished:
  `history/office-001.md`.
