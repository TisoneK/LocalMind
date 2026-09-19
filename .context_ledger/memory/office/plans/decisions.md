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

---
## ADR-64: Proactive memory writes are visible by design; a generalized lesson, not the failing instance, is what gets stored (2026-09-18)
- **Status:** accepted
- **Author:** Juma / claude-sonnet-5 (Session 17), shipping B-2026-09-15-14 (ADR-62 gap 1, reflection loop) and resolving P-2026-09-16-36 §2
- **Context:** ADR-62 named the reflection loop as build-order step 1; the research doc (§6) specified its durable output as "atomic lessons in memory" but left one design question open for the owner: should the agent's own autonomous memory writes be silent, or surfaced? Asked directly (AskUserQuestion) with the PA's 2026-09-15 lean stated ("silent learning is unauditable") — the owner picked the visible-log option.
- **Decision:** (1) **Visibility is not optional for autonomous writes.** Any future feature that writes to memory without an explicit user "remember this" (this reflection loop now; B-2026-09-15-15 passive context-awareness next) must surface what it wrote, not just log it internally — a dedicated top-level SSE event + a small UI surface, the same shape as the context-usage-breakdown precedent (S004), not the generic `obs_event` wrapper (which the frontend silently drops unless explicitly matched). (2) **The visible event fires only on a confirmed write.** `_store_fact_if_valid` now returns `bool`; a caller surfacing a write to the user must check it, never assume success from having *attempted* a store — a blocked/volatile-refused/deduped attempt is not a write and must not appear in the log (ADR-18/63's read-back philosophy applied to the log itself, not just to mutation confirmations). (3) **The stored content is the PATTERN, not the instance** — the self-critique's reviewer LLM call is asked for one extra structured field (`LESSON:`) explicitly instructed to abstract away the specific facts of the mistake, reusing the existing critique call rather than adding a second one (keeps the ~6.4s-per-write batching concern from the research doc from compounding with an extra LLM round trip).
- **Consequences:** a `memory_kind` value of `"lesson"` now exists in stored metadata (via a new `kind_override` param on `_store_fact_if_valid`, threaded through instead of overriding `durability_profile` itself, which still runs its VOLATILE gate against the lesson text as normal defense-in-depth). Future proactive-write features inherit the same expectation: check the design doesn't reopen P-2026-09-16-36 §2 as "silent by default" without a fresh owner decision. Also surfaced and fixed in the same session: `_reflect_on_answer`'s intent gate (`REFLECT_INTENTS`) had silently excluded the unified Parent loop's own `Intent.ANALYZE` marker since some earlier refactor, so the self-critique step — and therefore any lesson from it — had never run for a single agent-loop turn; this is a real latency/cost change (one more LLM call after substantive turns) the owner should watch, not a pure bugfix.

## ADR-65: User-context deduction fuses machine signals by trust tier, not majority vote; the conclusion is asserted, persisted once, and injected everywhere the model answers (2026-09-19)
- **Status:** accepted
- **Author:** Kamau / claude-sonnet-5 (Session 18), shipping B-2026-09-15-13 (ADR-62 build order 1-2, research doc §2 Arc A)
- **Context:** the machine already carries the user's country/timezone/language, but the agent hedged across candidates or claimed it could not know (live-proven: baseline answers "I cannot determine your country"). A flat vote over collected signals is wrong on real machines: smoke-testing on the owner's box, the OS geo setting says KE while the locale *format* tag is the Windows default `en-US` — majority/flat logic picks the wrong country. The ADR-63 keyed write path and the S014 durability classifier already exist and had to be reused, not duplicated.
- **Decision:** (1) **Trust tiers, not votes:** the Windows user geo setting > IANA timezone mapping > locale language tag > keyboard layouts; the strongest tier present wins and weaker contradicting signals are noise, with explicit confidence and an honest unknown when signals are absent or genuinely diverge. Locale *format* tags are demoted because Windows ships them at defaults regardless of the user's actual location. (2) **Collectors are best-effort and never raise** — a failing collector contributes nothing rather than failing the boot. (3) **Persist once through the existing keyed path, not a new one:** the boot hook writes the stable part as a "My country: …" fact through `MemoryComposer`, deliberately phrased so the existing STABLE_FACT/boot durability classifier and `subject:location` canonical key apply with zero classifier edits; boot is idempotent (one keyed row, refresh overwrites, no accumulation). (4) **Assert the conclusion on every answering surface** — native-bootstrap system section (full block), per-turn context env line, and the direct-chat funnel's system prompt; live-testing showed the zero-tool conversational path never sees the turn-context block, so a surface the model answers from without the deduction is a bug, not an optimization.
- **Consequences:** `core/user_context.py` is the single fusion point; future signals (ISP, region files, prior turns — the row's full list) extend the tier table rather than adding new votes. Region-implicit requests ("weather at home") can be acted on without asking. The per-surface injection adds a fixed small cost to every prompt; the full block rides only the bootstrap call, one line rides per-turn surfaces. Passive-profile growth (B-2026-09-15-15) builds on this module as its reasoning input.
