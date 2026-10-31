# DSH architecture study — verified from source (2026-10-31)

Session: Nora (S009). The external analysis recommended DeepSeek Harness
("DSH", https://github.com/deepseek-ai/deepseek-harness) as an architectural
reference for prompt construction, context building and execution
observability. Per the owner's standing ruling, this is a STUDY of design
principles only — no DSH vocabulary, names, or structures are to be carried
into LocalMind artifacts; what we adopt gets expressed in LocalMind's own
terms at implementation time.

## Verification

The repository is real and was studied from source, not documentation alone:
shallow-cloned at HEAD `ce7073d5` (last commit 2026-10-30), MIT licensed
("Copyright (c) 2026 DeepSeek"), TypeScript pnpm monorepo — 58 packages under
`packages/` (root `@deepseek-ai/dsh-root` v0.2.2-alpha.2) plus a thin Python
SDK whose only job is launching the Node CLI. Self-described developer
preview with promised breaking changes. The companion community project
"DSH Context Taxonomy" is also real:
https://github.com/ArtificialNotImbecile/dsh-context-taxonomy (MIT, plugin
that renders per-model-call context composition in six categories: system /
conversation / current-prompt / tools / options / unclassified).

## Observed principles (with source anchors)

### Prompt architecture (`packages/core/system-prompt/src/index.ts`)
- One service models FOUR distinct registration kinds: static sections,
  dynamic contexts, tool schemas, and variables — each returning an exact
  disposer (`section()` :485, `context()` :520, `tools()` :552,
  `variable()` :568).
- Centrally allocated numeric order slots (`SECTION_ORDERS` :136-172,
  `CONTEXT_ORDERS` :177-186) with a deterministic name tie-break — ordering
  is machine-independent, not prose-adjacency luck.
- Assembly is scope-filtered: a global layer plus a chain of scoped layers;
  scoped registrations shadow globals by name (`assemble` :621-696), so a
  per-agent prompt contribution replaces rather than duplicates.
- Duplicate section/context/variable names throw at registration; strict
  variable interpolation throws on unknown/undefined references and never
  re-scans substituted values (:347-384).
- Tool schemas are a first-class assembly output: deep-cloned per assembly,
  orderable, and flaggable for deferred loading (:649-654).

### Context construction (`packages/core/session/src/index.ts`,
`packages/core/agent-loop/src/runtime-context.ts`)
- "Model-visible means logged": every model request is derivable from the
  durable event ledger (`deriveMessages` walks an ordered surface of
  message-producing events, :981-1020). The architecture doc states the
  invariant at `docs/architecture.md:128`.
- Input classes are first-class: a new user turn vs mid-turn steering vs
  injected context are separate inbox queues AND tagged in message metadata
  (`source`), never flattened into one "user" bucket.
- Dynamic context is diffed, not re-sent: a runtime-context snapshot is
  emitted only when its rendered text changed, with an explicit
  supersede/clear marker (:157-168). Prompt-prefix stability is preserved
  deliberately for cache friendliness (:57-116).
- Token usage travels ON the assistant message (input/output/cache/
  reasoning), so accounting and content cannot drift apart
  (`session/src/types.ts:341-357`). There is NO built-in per-category
  meter in core — that is exactly what the community Context Taxonomy
  plugin adds.

### Agent orchestration (`packages/core/agent-loop/src/agent.ts`)
- Turn = 0+ steps; step = one model call + its tools. The loop terminates
  by EVIDENCE: no tool calls in the assistant message → completed (:586-587);
  a tool can conclude the turn explicitly (`concludesTurn()`).
- A rejected pre-step or empty first claim closes the turn without
  spending a model call (:353-359).
- Retries are policy-driven via an overridable hook, not hardcoded; a
  retry re-prepares the call but does not re-run prompt assembly or
  pre-step (:543-563, :444-458).
- Failure containment is durable: a failed step gets logged settlements
  (attempt records, recovered tool results) so the log never has dangling
  tool calls (:363-389).

### Trajectory / observability
- The trajectory IS the session log: an append-only, typed, versioned
  event ledger (~85 known event types, unknown types refused unless marked
  ignorable). Per-event wall-clock time on every record; failed/retried
  attempts retained as non-model-visible attempt events.
- Persistence is generation-named JSONL (never renamed), with one-step
  migrations; projections (inbox, model selection) are folds over the log.
- The official UI trajectory view and an OTLP export (redaction before
  report) are both pure readers of the same ledger.

### What keeps prompts small
- Deferred tool loading: tools flagged at registration are withheld from
  the provider until a durable activation event; removals disable without
  discarding history.
- Per-scope tool restriction (allow/deny intersected per agent), so a scope
  sees a small tool subset.
- Compaction as a logged, priced transaction (threshold 0.8 of window, a
  verbatim tail, reserved headroom, shadowed token counts recorded per
  elided range).
- Cadence-gated injection (e.g. a clock snapshot skipped within its refresh
  interval).

## Adaptable principles (for the backlog row's implementer)

1. Split static instruction sections from dynamic runtime context —
   different lifecycles; re-admit dynamic context only on change.
2. Give every prompt piece a name, an order slot and an owner scope;
   deterministic ordering; scoped shadowing instead of ad-hoc overrides.
3. Derive every model request from the durable record, so retries, reload,
   replay and debugging read the same history.
4. Tag input classes explicitly (new turn / steering / injected context)
   in both the inbox and the record.
5. Send only what changed: diff dynamic context and tool sets against the
   last request.
6. Terminate the loop by evidence, not a counter; retries by overridable
   policy, not baked-in logic.
7. Fail durably — every failed attempt and missing tool result leaves a
   logged settlement.
8. Budget per route: compaction threshold + verbatim tail + recorded
   shadowed token counts, so elided context stays auditable.

## Migration cautions

- The plugin/service runtime is total: patterns lift, code does not. There
  is no Python agent loop to reuse (the Python SDK merely launches the Node
  CLI).
- Developer preview: treat as a reference, never pin to its internal APIs.
- The log-as-truth invariant is expensive to adopt halfway — partial
  adoption (logging some requests, deriving others ad hoc) recreates the
  drift the design exists to prevent. Scope any adoption to a whole surface.
- MIT licensed — no legal risk. Scale mismatch (58 packages) is not
  something to replicate; adopt the invariants, not the structure.
