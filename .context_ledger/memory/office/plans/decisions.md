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

---
## ADR-62: Thinking-first build order; the Parent is the foundation sub-agents inherit (2026-09-15)
- **Status:** accepted
- **Author:** Neema / qwen3.8-flash (Session 6), recording the owner's directive from his LocalMind v0.5 chat transcript 2026-09-15 11:19–12:20 (full analysis: `office/plans/2026-09-15-self-improvement-transcript-research.md`)
- **Context:** the owner stress-tested the shipping app in conversation (trending-topics → location deduction → memory cleanup) and turned the post-mortem into a roadmap: the agent's failures were all *reasoning* failures (hedge where signals converged, runtime guessing, narrated-not-taken actions, reflexive agreement, volatile facts persisted), and he intends the product to reach a maturity point where HE stops editing product code and the agent's own reflection/gap-detection loop generates its backlog.
- **Decision:** build order is **Perception → Deduction → Self-check → Reflection → Planning** (the thinking infrastructure), **then** general skills, **domain expertise last** — because sub-agents inherit the Parent's thinking, and an immature Parent scaled through sub-agents multiplies the same mistake categories. Six architectural gaps must be solved before skill volume grows: (1) reflection loop, (2) signal-fusion layer, (3) gap-detection mechanism, (4) ACTIVE memory (pre-action recall, not afterthought), (5) skill composition/chaining, (6) confidence calibration. "The architecture is the product; the skills are just content." Future improvements should therefore be *minimal skills and lessons* plugging into this frame — a signal that a change requires restructuring a skill to inherit these capabilities is a signal the architecture gap is not closed.
- **Consequences:** new feature proposals (MCP surface, Explorer tool, judge, skill packaging from the standing Target) stay welcome but must not outrank the thinking-infrastructure rows; acceptance for this program = the owner's five operational conditions for self-improvement (notice own failures in real time; codify lessons automatically; evaluate own rules; build skills on detected gaps; know and admit what it doesn't know). The anti-pattern list from the research doc §7 (runtime guessing where signals exist, hedging against convergence, narrating instead of acting, agreeing reflexively with user OR self, claiming success without state read-back, persisting volatile facts, walls-of-text memory, trading correctness for speed or caps, bolting skills on weak thinking) is treated as do-not-regress guidance for loop/prompt work.

---
## ADR-63: Memory durability is decided in the write path; identity makes a fact one row; mutations answer from a read-back (2026-09-17)
- **Status:** accepted
- **Author:** Buffy / model unknown (Session 14), implementing ADR-62's L2 remedy with the owner's transcript evidence
- **Context:** ADR-62 named the typed memory schema (preference / stable fact / volatile) as build-order step 1 and the research doc settled the mechanism order (read-back-after-mutation → write-path stripping + keyed upsert → boot refresh). The live failure it addresses is concrete: the machine's IP and ISP were stored as durable defaults, the same fact accumulated near-copies (worst on the plain-text path, which cannot embed and appended a row per write), and cleanup reported success while the row was still there — including a case where every delete was failing silently because the store had no vector table.
- **Decision:** three rules live in the write path, in code, not in prompt prose. (1) **Durability gate** — `VOLATILE` content (IP/MAC/IPv6 literals, ISP/carrier, live machine readings, explicit "right now" framing) is refused with the reason in plain words, in the explicit memory tool *and* the autonomous extraction paths; `STABLE_FACT` carries `memory_freshness` (`static`/`boot`) and `memory_confidence` so a stored copy is a refreshable cache, not a claim of permanent truth. (2) **Keyed identity** — `canonical_key()` names a fact (single-valued subject, else leading content words) and that key is hashed into the row id, so re-statements replace one row; a keyed write supersedes near-identical unkeyed rows, and the degraded plain-text path writes the same keyed id instead of a fresh uuid. (3) **Read-back** — a store/forget confirmation is built from the state after the mutation; a write that cannot be read back is reported as unverified, and deletion resolves id, unique id prefix, re-worded content, or key. An id printed in the list is an id that can be acted on.
- **Consequences:** memory confirmations may now say "that didn't reach memory" or "it's still there" instead of a cheerful acknowledgement — the honest failure is the feature. The key heuristic is deliberately conservative (a subject key or the leading words): it collapses re-statements, and paraphrase collapse with the embedder down is NOT guaranteed (the semantic dedup lives in the vector path). `memory_kind` / `memory_freshness` / `memory_confidence` are the metadata names future work (boot refresh, injection, calibration) must read. Reads and deletes remain outside the deterministic route that handles writes — the model still chooses whether to call the tool for those, which is the next gap. Related: ADR-18 verification-first now applies to the memory store, not only to files.
