# External harness deep study — the owner-provided reference, from source (2026-11-01)

Session: Sefu (S010). Extends `2026-10-31-dsh-architecture-study.md` (S009) from a
first-pass sketch to the exhaustive study the owner asked for: "how the prompt was
engineered and what we are doing wrong or missing; how its thinker was built; how the
agent processes its request from the beginning to the end; more you will figure out
while you're there." Same standing ruling as S009: this is a REFERENCE-ONLY study of
design principles. No borrowed vocabulary, names, or structures enter LocalMind
artifacts; every adoption is re-expressed in LocalMind's own terms at implementation
time. Reference file/package paths below are evidence anchors, not a vocabulary to copy.

Provenance: cloned from source at HEAD `ce7073d5` (2026-10-30), MIT, TypeScript
pnpm monorepo, 58 packages + Python SDK launcher. Docs are generated from code
(docs/architecture.md, agent-lifecycle.md, tool-execution-pipeline.md, glossary.md;
per-package READMEs with a fixed "What the model sees / Token effect / KV Cache
effect" contract section). Everything below was read from source, with anchors.

## 1. End-to-end: how a request is processed, beginning to end

The lifecycle (docs/architecture.md §Turn flow, docs/agent-lifecycle.md — both
curated against code):

1. **Intake.** All input lands in ONE durable inbox; message classes are distinct
   types, not a flattened "user" bucket: a new user prompt, mid-turn steering, and
   injected context are separate inbox lanes AND carry typed metadata on the message
   itself (`MessageSourceMap`, `packages/llm/llm/src/message.ts:25-136` — `user`,
   `model`, `tool`, `system-prompt` kinds, plugin-extensible by declaration merging).
   Injected context "waits for a waking message" — it never starts a turn by itself.
2. **Claim.** Turn opens (`turn/start`); the driver claims pending next-step input
   plus at most one queued prompt. Between steps it claims only next-step input.
3. **Pre-step gate (the free one).** The `agent/pre-step` waterfall can rewrite or
   REJECT the claimed batch before a single model call is spent: "a rejected or
   empty first claim closes a durable turn without a step"
   (agent-loop README §Turn and step flow). Routing decisions cost zero tokens.
4. **Assembly.** One `assemble()` per proposed step merges: fixed identity opener
   (order −1000), persona prefix (0), first-party guidance, environment sections
   (10000+), persona suffix (10200), dynamic runtime contexts, resolved variables,
   and the step's visible tool schemas (packages/core/system-prompt/src/index.ts).
   Sections are static; contexts are DIFFED dynamic facts (sent only on change, with
   supersede/clear markers); variables resolve with strict failure on unknown
   references. Assembly happens BEFORE the pre-step listeners run, so a listener can
   still reject or rewrite the whole step.
5. **Call preparation.** `prepareCall()` validates the route and binds the adapter:
   provider, model, reasoning effort (adapter-declared levels per route), tool
   schemas. Cancellation during preparation commits nothing. A request "header"
   (envelope: config + tools, NOT prompt text) is logged only when it CHANGES;
   unchanged steps, retries, and later turns in the same series inherit it —
   deliberate byte-identical prefix discipline for provider KV cache.
6. **Admission and reconciliation.** The rendered system prompt is reconciled into
   history as `system/message` nodes: a capable route appends a changed prompt
   AFTER the cached history ("in-history" update) so the prefix through history
   stays reusable; an incapable route consolidates at the first system node via
   logged per-node replacements. Accepted users are appended once. Then the request
   is DERIVED FROM THE LOG (`deriveMessages()`) and frozen — the log is the single
   source of what the model sees ("Model-visible means logged",
   docs/architecture.md:128).
7. **Streaming.** One model call streams chunks; every chunk frame is transient;
   the complete stream settles durably as ONE `assistant/message` (with the exact
   compact timed stream embedded, plus usage: input/output/cache/reasoning tokens
   on the message itself) or, on failure, as an `assistant/attempt` settlement that
   adds NO model history. A cancelled stream finalizes the text already delivered
   (an `interrupted: true` anchor) so the next request contains what the user saw.
8. **Tool phase.** Tool calls classify into exclusive barriers vs a bounded rolling
   pool (default 10 parallel). Pipeline per call, in order: `tool/call` logged
   BEFORE execution → pre-execute (hooks, permission, one-shot approval — absent or
   unanswerable approval DENIES) → monotonic guards (deny/abstain; deny hides the
   tool from prompt AND execution indistinguishably) → execute (timeout wrapper
   arms the tool's declared `timeoutMs`, maps expiry to a structured TOOL_TIMEOUT
   result) → project prepared content → post-execute (accept/block/replace/add
   context) → normalized snapshot → final `tool/result` (docs/tool-execution-pipeline.md).
9. **Loop decision — evidence, not a counter.** After each step: zero tool calls in
   the assistant message → turn completes (agent.ts:586-587, read first-hand); a
   tool may also declare its result conclusive. Tool results may carry
   `additionalContexts`, which are spliced into the next-step inbox (labeled, never
   plain user prose) and land in the next admitted request. If input or tools owe
   more, the next step claims and continues the SAME turn.
10. **Failure settlements, not silence.** A failed step closes with a synthetic
    error result for EVERY unanswered tool call — `TOOL_OUTCOME_UNKNOWN` (retry
    only if read-only/idempotent; otherwise check external state or ask) or
    `TOOL_NOT_STARTED` (agent-loop README §Failure and cancellation). Cancellation
    settles undispatched calls as `ABORTED_BEFORE_DISPATCH`. Later requests always
    see paired call/result history; nothing dangles.
11. **Retry is policy, not instinct.** Transport-level retries live in a per-route
    retry policy (packages/llm/llm/src/retry-policy.ts): mode `normal` retries only
    a configured set of transient failure codes up to maxRetries (default 5), with
    exponential backoff 500ms→10s and ±10% jitter, honoring provider Retry-After
    up to the cap; mode `always` retries everything until success/cancel/disposal.
    A retry re-prepares the call and reconciles the SAME rendered assembly — it
    never re-runs assembly, pre-step, or user admission (agent.ts:444-458,543-563).
    Terminal request failures enter `agent/request-error`, where a listener may
    return retry (compaction uses exactly this for context overflow); otherwise the
    original error is authoritative and ends the turn.
12. **Turn close.** A serial `agent/turn-stopping` checkpoint (the ONLY sanctioned
    place for a turn-budget policy — the loop has NO built-in turn budget), then
    `turn/end` with a typed cancel cause. Everything above is durable session
    events; live `agent/*` events are coordination-only and never model-visible.

## 2. Prompt engineering — how it is engineered, and what we do wrong or missing

How the reference engineers prompts (all verified from source):

- **Four separate assembly inputs with different lifecycles**: static sections,
  diffed dynamic contexts, interpolable variables, provider-owned tool schemas
  (system-prompt/src/index.ts — `section()` :485, `context()` :520, `tools()` :552,
  `variable()` :568). Mixing them is a type error, not a habit.
- **Deterministic, centrally allocated order slots** (SECTION_ORDERS :136-172,
  CONTEXT_ORDERS :177-186; equal orders break by name). Ordering is machine
  independence, not prose-adjacency luck. Duplicate names throw at registration.
- **Strict failure over silent malformation**: unknown variable references,
  registered-but-valueless references, malformed complete-prompt groups, a
  `toolOrder` without exactly one rest entry — all throw BEFORE any model request
  ("a malformed prompt is worse than a loud failure", README §Assembly).
- **Cache-awareness is a first-class design constraint**, documented per component:
  every README carries "What the model sees / Token effect / KV Cache effect"
  triads. Concrete mechanics: envelope headers logged only on change and inherited
  otherwise; in-history system-prompt appends on capable routes; tool-schema sets
  stable unless actually changed; dynamic contexts re-sent only when their rendered
  text changed; compaction prunes tool results BEFORE summarizing; the summarizer
  call replays the conversation's own prefix and appends its directive as the final
  user message so the auxiliary call rides the warm KV prefix (summarizer.ts:26-31).
- **Injected context is always labeled and never user-voiced**: every injected
  message carries a typed `MessageSource` (`form: 'notice'`, producer kind —
  repeat-tool-reminder/src/index.ts:60-64). An unlabeled context would render as a
  user prompt in derived history — the codebase treats that as a defect class with
  a name.
- **Advisory enrichment, never veto**: the repeat-tool guard counts identical
  consecutive calls (canonicalized deep-key-sorted args so key order can't dodge
  detection), and at thresholds [3,5,8] injects an escalating reminder — gentle
  first, then structured (tool / count / args preview capped at 500 chars) — that
  rides ALONGSIDE whatever decision the pipeline made, including a block. It never
  suppresses, never re-runs, never re-prompts the turn (index.ts:216-231).
- **Loop discipline lives in the model's world, not in a judge**: the turn ends
  when the model emits no tool calls; loops are broken by an advisory nudge; there
  is NO acceptance gate re-prompting clean answers, NO reply-pending judge on
  zero-tool turns. Self-correction machinery (gates/judges) simply does not exist
  at the turn level; correctness comes from labeled context, evidence-based
  termination, and recovery settlements.
- **Structured-output prompts are templates with an exact skeleton and rules**:
  the compaction instruction demands EXACTLY a named-section Markdown structure,
  "(none)" for empty sections (never drop one), verbatim preservation of paths/
  commands/error strings/identifiers/numbers/signatures, faithful capture of user
  corrections, no meta-commentary, no tool use, and a prior-checkpoint merge rule
  (summarizer.ts:32-67). Fail-closed: a max-tokens summary is an ERROR (an
  incomplete checkpoint never lands), image output is rejected, empty output throws.
- **Mode gates are tools + approvals, not prose**: plan mode is entered/left by a
  tool whose result the human approves via a one-shot card; mode transitions apply
  from the NEXT step; the user's mode switch reaches the model as one labeled
  notice line, not as fake user speech (plan-mode/src/index.ts).

What we are doing wrong or missing, mapped concretely (feeds
B-2026-10-31-25; all in LocalMind terms):

| # | Gap in LocalMind today | Reference practice | Evidence |
|---|---|---|---|
| G1 | Runtime-injected context historically rode in as plain user-role text (the S009 demand-card bug was this class). No typed provenance on injected messages. | Every injected message carries a typed, producer-stamped source so derived history can never render it as the user's voice. | message.ts:110-136; repeat-tool-reminder:60-64 |
| G2 | Our per-turn relevance budget (B-25) must not reorder per turn or it destroys provider prefix caching (we already saw 99% cached prompts working FOR us). | Cache discipline is a documented constraint per component; dynamic facts are diffed, envelopes inherited, prompt updates appended in-history on capable routes. | agent-loop README §KV Cache effect; summarizer.ts:26-31 |
| G3 | Prompt assembly grows by accretion (capability note + todos + memories concatenated per path). No deterministic order registry, no strict failure on unknown references. | Named sections with allocated order slots, scope shadowing, fail-loud assembly. | system-prompt/src/index.ts:136-186,347-384 |
| G4 | Our gates/judges can spend a replan call on an already-clean answer (the false-PENDING greeting replan, S009). | Termination by evidence only; advisory nudges ride along; zero re-prompt machinery at the turn level. | agent.ts:586-587; repeat-tool-reminder:216-231 |
| G5 | No structured template discipline for our auxiliary calls (summary/checkpoint-type prompts would be ad hoc). | Exact skeleton + never-drop + verbatim-preservation + fail-closed truncation. | summarizer.ts:32-67,196-211 |
| G6 | Unanswered tool calls after a failure are not systematically settled with outcome-typed recovery results. | Every unanswered call gets a synthetic result with a code and idempotency-conditional retry language. | agent-loop README §Failure and cancellation |
| G7 | Model-request derivability from the durable record is partial (we have per-section breakdown telemetry; the request itself is not reconstructed from the record). | "Model-visible means logged": every request is derived from the event ledger; retries/reload/replay read the same history. | architecture.md:128; session deriveMessages |
| G8 | No per-component token/cache documentation discipline. | Every package README carries the What-sees / Token / KV-cache triads. | all package READMEs |

## 3. The thinker — how reasoning is actually built

The reference has NO separate thinker module, consultant model, or second reasoning
pass. The "thinker" is the model itself, and the harness's job is to carry reasoning
faithfully and control its cost:

- **Reasoning is a first-class content block**: `ReasoningBlock` (type `reasoning`)
  is distinct from visible text in the message vocabulary
  (packages/llm/llm/src/types.ts:74-76,146); it streams as a dedicated
  `reasoning-delta` chunk (:499); usage carries `reasoningTokens` (:195). The UI and
  the record always know which text was reasoning and which was the answer — the
  two can never contaminate each other.
- **Reasoning effort is a per-route, adapter-declared control**: each model route
  exposes its selectable efforts least→greatest plus a default
  (`LlmModelReasoningInfo`, types.ts:413-431,459-460); the agent config can pin one
  (`reasoningEffort`, agent-loop README §Configure); the selection is snapshotted
  per step, logged in the request header, and a mid-session change is recorded in
  the session rather than silently applied. Omitted effort = adapter default.
- **Effort is the lever, not suppression**: there is no "thinking off" switch for
  capable routes — cost control is choosing the effort level (and maxTokens per
  request), consistent with our own ADR-41 default.
- **Planning is plan mode**: a durable mode with a model-facing presentation tool
  and a human approval card; the plan is a Markdown artifact with a `#` title;
  "keep planning" returns feedback to the model; approval exits the mode and the
  work starts from the next step. Planning never happens in a hidden second model.
- **Self-correction is guards, not a re-thinker**: the repeat-call guard's
  escalating labeled reminders are the entire "reflection" mechanism at the loop
  level; failed transport requests retry by policy; context overflow recovers via
  compaction (prune then summarize) inside the open step. Nothing re-asks the model
  to grade its own clean answer.

For LocalMind this reframes our Thinker consults: the reference's answer to "who
thinks before acting" is — the model, once, with well-assembled context, visible
reasoning, and labeled nudges when it loops. Any LocalMind second-pass machinery
must justify itself against that baseline (our pre-tool consult was already deferred
to the first real tool call for exactly this cost reason).

## 4. Supporting machinery inventory (the "more you will figure out" list)

- **Plugin kernel (Cordis)**: everything is a plugin contributing services, typed
  events, and reversible effects; profiles = ordered bundle stacks, patches replace
  config rows by id; `--dump-config` prints the live tree. Composition, not
  inheritance. (docs/architecture.md §Cordis, §Profiles and bundles)
- **Capability seams**: a swappable capability = Service Definition + Providers +
  Consumers (glossary.md §capability-seam). One provider swap moves the whole
  execution world (fs + shell + PTY + LSP together onto a remote sandbox).
- **Scope model**: per-agent scoped registration with most-specific-wins name
  shadowing (a child's persona shadows `deployment:persona-prefix` —
  child-agent.ts:210-214); restrictions filter the global tool set by intersection;
  a filtered-away tool is absent from prompt AND refuses execution indistinguishably
  from nonexistent. Two flat levels; lineage is data, never visibility.
- **Subagents**: one delegation service, named providers (in-process spawn, fork,
  external runtimes); the tool returns a child session id immediately and the parent
  gets a completion notice on settlement; capacity slots (default 8, no queuing —
  reject at admission); depth policy default 1; delivery to parent vs awaiting
  caller; structured result staging closes input, rejection reopens it; discovery
  via parent-owned catalog projection. (packages/subagent/subagent/README.md)
- **Goals**: one durable completion objective per session with a revisioned
  phase (active/paused/blocked/complete), a round cap, and a separately-armed
  activation permission that never survives resume without human re-authorization
  (glossary.md §goal).
- **Background work**: jobs service + `job_*` model tools; schedules wake the
  inbox (notices never start turns alone — a waking message does).
- **Todos**: one model-facing whole-list-replacement tool; fail-loud validation
  (empty/duplicate/extra fields rejected); returns new counts as the result text.
- **Session log**: append-only, generation-named JSONL (never renamed), one-step
  migrations, unknown event types refused unless marked ignorable; projections are
  folds; forks seed from a turn boundary. (architecture.md §Session log)
- **Timeout policy**: tools declare `timeoutMs`; the wrapper arms the deadline,
  scopes its own signal so a nested outer timer isn't misread, and substitutes a
  structured TOOL_TIMEOUT result. (guard/timeout-policy/src/index.ts)
- **Retry policy**: per-route, code-set-based, backoff+jitter, honors
  Retry-After. (§1 item 11 above)
- **Attribution**: usage and content travel together on the assistant message —
  accounting cannot drift from content (types.ts; complements our turn-stage map).
- **Docs discipline**: generated catalogs (config, tools, events, persistence) +
  curated docs + per-package README contract triads; postmortems and decision notes
  live in-tree (.agents/notes/...). Office analog: our reviews + ADRs + sessions.
- **Benchmarks/safety**: BENCHMARK.md is a thin runner guide; SAFETY.md exists as a
  top-level document — the harness treats abuse policy as a shipped artifact.

## 5. What NOT to adopt (extends the S009 cautions)

- The plugin kernel is total: patterns lift, code does not. We already have a
  kernel; adopting its shape would be a rewrite, not a port.
- Scale artifacts: 58 packages, generated catalogs, dual-language docs — none of
  that is a principle. Adopt invariants, not structure.
- The log-as-truth invariant is expensive halfway (S009 note stands): scope any
  adoption to a whole surface or don't start.
- No turn budget is built in — that is a POLICY slot, and our loop may well want a
  budget; if we add one, it goes at a turn-close checkpoint, never mid-step.
- Developer preview: treat as reference, never pin to its internal APIs.
- Per the owner's ruling: zero borrowed vocabulary — the table in §2 and the
  machinery list in §4 are study notes; anything we build gets LocalMind names.

## 6. Adoption queue (first increments, in order)

1. **Labeled injected context (G1)** — give every runtime-injected model-visible
   message a structured producer stamp so injected text can never masquerade as the
   user; audit all injection sites in the loop and runtime. Smallest surface,
   highest regression value (it is the exact bug class S009 fixed blind).
2. **Recovery settlements for unanswered tool calls (G6)** — outcome-typed
   synthetic results on failed/cancelled steps, with idempotency-conditional retry
   language, so later requests always see paired call/result history.
3. **Cache-discipline review of the B-25 relevance budget (G2)** — the budget must
   select and order content with prefix stability as a hard constraint; diff
   dynamic facts; never reorder stable sections per turn.
4. **Order-slot registry + strict assembly (G3)** — named, owned, ordered prompt
   pieces with fail-loud unknown references.
5. **Structured-template discipline for auxiliary calls (G5)** — adopt the
   skeleton+rules+fail-closed pattern for any summarization/checkpoint-style call
   we add.
6. **Request derivability (G7)** — long-horizon: derive what the model saw from
   the persisted record, whole surfaces at a time.

Items 1-2 are candidate next builds; items 3-5 belong to the B-2026-10-31-25
program; item 6 is a standing architectural direction, not a one-session task.

— Sefu (S010), 2026-11-01
