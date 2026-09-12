# Office 001 — accomplishments record (permanent)

- Opened: 2026-07-31
- Closed: 2026-09-12
- Sessions: 447

The frozen office lives at history/office-001/ until it is zipped into
archive/office-001.tar.gz. This record stays in history/ forever — even after
the tarball is garbage-collected, the office is never forgotten. Not read at
session start; deliberate lookback only.

## Accomplished

- **Parent-only architecture.** The multi-agent registry era (ADR-5/6/8)
  converged to one agent: parent-first runtime (ADR-24/25/27/33/34), single
  delegation entry point (ADR-24), then Parent-only scope as the standing
  decision (ADR-47/53) with a warm parent kernel (ADR-52) and ParentSession
  rolling summary + readiness telemetry (ADR-54, ADR-55 program). Live
  multi-agent delegation remains parked compatibility residue; explorer/judge
  are planned as read-only Parent TOOLS, not peers.
- **Verification-first runtime (ADR-18).** "Done" became a checkable contract:
  goal-derived fixed checklists gating completion (the synthesize/evaluate
  stage), an acceptance gate with bounded replans + deterministic honest-stop,
  result grounding/verification, prose-commitment and tool-talk detectors, and
  one measured turn-outcome seam (ACT|ANSWER|INCOMPLETE + a single recovery,
  §40 loop discipline). Paired with a standing LIVE-verification bar
  (`system/live-testing.md`): every agent-behavior change is proven on a real
  provider at the isolated-8765 harness, never by unit tests alone.
- **Latency and token efficiency.** Deterministic trivial/conversational
  fast-paths (ADR-11/26/35/51; the "Hi"→zero-provider-call boundary S206),
  byte-stable cacheable prefix + prompt caching + prompt diet (ADR-39),
  classify-only init, evidence-sufficient schema-free answer calls (ADR-61 —
  a real-weather task 184.8s→14.1s live), thinking-aware timeouts (S31-33),
  and a provider-stall watchdog (S471 `e32e08a1`: stall names the provider at
  5s, switch-model offer at 30s, truthful fall-through after the first byte).
- **A bounded tool surface.** Tiered lean schemas with on-demand
  `describe_tool` (ADR-40, live-verified on real providers), tools as bounded
  helpers (ADR-43), one search front door (`system_search`, S400), the
  `dir_explorer` Explorer tool + UI alias (S462), racing web-search tiers
  (DDG/Bing/SearXNG), and the browser as a first-class capability — the
  steer-don't-hide rule (S430 revert: never gate a capability out of the
  roster on an environment probe).
- **The Thinker program (ADR-42 module).** From silent analyst (ADR-36/38) to
  visible decision-grade reasoning with a no-machinery prose contract
  (ADR-59), concurrent zero-latency post-tool consults (ADR-60), and the
  pre-tool consult fix (S343) — decision reasoning now visible per turn.
- **Memory and providers.** Ollama embeddings + vector facts, the Remember
  cue extractor (S455), the worker-report context-leak fix (S469), and a
  documented provider map (zen/bankofai/zai/cerebras/gemini + B.AI per
  ADR-55; free-tier quota shapes, promo-flip behavior, 429-storm realities).
- **Frontend.** Realtime-alive SSE timeline + Agent Workspace panels (ADR-27/
  30/34), per-turn artifact persistence so history survives reloads (S266),
  full-fidelity export v3 (S431), diff/table/code cards, app-wide panel
  theming (S399), and thinking-block markdown (S472).
- **The protocol itself.** This office ran `.context_ledger` from core 0.5.0
  through 1.0.5 — including the 1.0.0 office-architecture migration, Windows
  gate teeth (1.0.3/1.0.4), and the re-armed bookkeeping gate (S472) — and
  it closes with this first-ever `ledger-history close`.
- **Suite health.** From a 23-failure Windows baseline to the date-bomb fix +
  ~3,100-passing full suite (S472), with known flaky families tracked in the
  backlog rather than hidden.

## Decisions still in force

The full text of every ADR lives in `history/office-001/plans/decisions.md`
(note the two same-day number collisions inside it: ADR-54 and ADR-58 each
appear twice). The binding set for the next office:

- **Do-NOT-regress guardrails (verbatim from `memory/workflows/active.md`):**
  the ADR-34 event order; the `Hi`→zero-provider-call boundary (S206); the
  Session 31-33 fixes that thinking-aware timeouts build on; ADR-40's
  guardrail (live-verify tool SELECTION on a flash-tier model + cerebras
  before any further schema cut); ADR-41 (z.ai thinking ON — never re-add a
  thinking-disable for GLM; timeout scaling is the lever); the S471 watchdog
  fall-through (once a first byte lands the heartbeat returns to the truthful
  prior branches — never stall-shame a healthy stream); the Parent-only scope.
- **Architecture:** ADR-53 Parent-only; ADR-46 execute opt-in, never
  fail-open; ADR-38 evidence-first; ADR-37 one path, no narration layer
  (Direct Mode removal = open item B-2026-08-15-10, a pending product call);
  ADR-14 single front door + thin dispatcher; ADR-6/10 preserve developer
  agents, expand capability families additively; ADR-28 first SSE event is
  transport acknowledgement; ADR-1 dark-only; ADR-2 SSRF redirect
  re-validation; ADR-44 Ollama context-window detection; ADR-56 vision
  (agent runtime + intelligence harness).
- **Loop discipline:** ADR-18 verification-first; ADR-57 slices (do NOT
  reintroduce serial every-tool consults — S420; do not await in-flight
  consults at turn end); ADR-59 no machinery language in Thinker prose;
  ADR-61 never gate loop optimizations on the `intent` parameter (constant
  on the parent path).
- **Working agreements:** the live-testing bar is MANDATORY for loop/tool/
  adapter changes (report live-verified vs unit-tested vs assumed); cure the
  disease, not single prompts; model-agnostic + env-agnostic fixes — "there
  is no weak model" (neutral terms only); push to main after each commit;
  two-surface commit prefixes (`chore(ledger):` / `docs(review):` / product
  prefixes, never mixed); solo sessions run the light path (claim → work →
  release); roster check-in every session; never port 8000 (the user's app
  runs there), isolated 8765 + LOCALMIND_HOME only; no secrets in tracked
  files, ever.

## Open threads

- **Backlog — full carryover to the new office's backlog.md (owner directive,
  2026-09-12):** 69 rows re-rowed into priority tables — 13 High / 31 Medium /
  25 Low, stable IDs, three legacy items newly minted (`B-2026-07-11-1`,
  `B-2026-07-11-2`, `B-2026-08-31-1`). Rows deleted during the re-row because
  the file itself recorded them finished (all verified in git history):
  B-2026-08-30-3 (reverted; residual steering folded into B-2026-09-10-5),
  B-2026-09-04-1 (RESOLVED `6d4b45e`), B-2026-09-06-2 (RESOLVED `ad4e3fc`),
  B-2026-09-06-3 (RESOLVED `5a7d3f4`+`cad31f1`), B-2026-09-06-6 and
  B-2026-09-06-7 (RESOLVED `5a7d3f4`).
- **The ZCode-import resilience program (S471, standing Target in
  `workflows/active.md`):** (1) MCP client support; (2) read-only Explorer
  subagent as a Parent TOOL; (3) fresh-eyes acceptance judge; (4) plugin-style
  skill packaging. Deliberately NOT imported: live multi-agent delegation
  (ADR-53). Not yet backlog rows — owner's call to file them.
- **Owner decisions pending:** grep_search — (a) expose vs (b) retire
  (S472 assessment recommends retire-keep-machinery; implementation awaits
  the pick); frontend vitest determinism pass (non-deterministic 7-9-fail
  family documented by S472); per-model health memory / stall-aware fallback
  levers (S471 report Part 1).
- **Open protocol asks re-seeded into the new office's flaws log:** the
  collab integration step when the main checkout is a peer's (Omari/S472) and
  the roster table-shape lint (Buffy/S472).
- **Resolved by this close:** the office-full notice (446→closed at 447) and
  the legacy sessions.md double-entry WARNs; Omari's (S472) stale roster row
  froze into office-001 — the new board starts empty, and a returning Omari
  re-checks-in fresh.
