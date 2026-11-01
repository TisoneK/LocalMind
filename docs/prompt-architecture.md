# The prompt architecture — what the model sees, what it costs, what it caches

Every component of the prompt system documents three facts: **what the model
sees** (the exact surface, no ambiguity), **the token effect** (what it costs
per call, and on which calls), and **the cache effect** (what it does to the
provider's prefix cache). These triads are the documentation discipline for
the prompt package (`backend/src/core/agent/prompt/`): a component whose
cache effect you cannot state is a component that can silently bust the
cache. This file is that discipline, kept current with the code — the code
is authoritative where they disagree, and the discrepancy is a bug in this
file.

The two bands, one sentence each:

- **STATIC** (order slots < 1000) — the byte-stable, cacheable prefix.
  Identical across turns and intents, or the provider cache misses on every
  call. Per-turn content can never be registered here (the registry refuses
  it at construction).
- **TURN** (order slots ≥ 1000) — the trailing per-turn context message.
  Byte-identical within a turn (so the tail also caches across a turn's
  iterations), expected to change between turns. The user's objective leads
  it; per-turn context and guidance follow in allocated slots.

Within a band, sections render sorted by `(order, name)` — ordering is a
machine-assigned slot, never prose-adjacency luck. Duplicate names, unknown
references, empty text, and per-turn values in the STATIC band all fail
loudly (`PromptStructureError`) before any model call is built.

---

## The parent (native-bootstrap) execution prompt — STATIC band

Assembled by `build_parent_static_registry` (`sections/parent.py`). Rendered
once per turn for the first model call; later calls in the same turn are
staged (see below).

| Section (order) | What the model sees | Token effect | Cache effect |
|---|---|---|---|
| `identity` (10) | One paragraph: who LocalMind is, what kinds of requests it handles. | ~60 tok, every call. | Byte-stable — the head of the cached prefix, process-lifetime. |
| `conversation_or_action` (110) | The conversation-vs-action decision: answer from knowledge when possible, use the tool API when something is needed outside, never fabricate a result. | ~120 tok, every call. | Byte-stable. Points at "the tool list below" — the section it references must survive every cut (it does; see the relevance budget). |
| `act_not_announce` (120) | Be concise, answer then stop, act instead of announcing, end the turn when the objective is met. | ~50 tok, every call. | Byte-stable. |
| `multi_part_completion` (130) | "X and Y" means both: never concede a requested part, never punt it to a next pass. | ~60 tok, every call. | Byte-stable. |
| `safety_grounding` (140) | Check current state before writes/edits/deletes; ground every answer in what tools returned; no XML tool calls, no exposed reasoning. | ~40 tok, every call. | Byte-stable. A rule, not context — survives every cut (staged cuts and the relevance budget both keep it). |
| `agent_playbook` (210, conditional) | The parent agent's contract (only when a caller supplies one). | 0 or ~300 tok. | Byte-stable per caller — registered only when non-empty, so its absence is a shorter prefix, not a changed one. |
| `system_facts` (220, conditional) | The boot-cached machine summary + shell-choice note, with "answer from it, don't call sysinfo" guidance. | ~100 tok when present. | Boot-cached per process — byte-stable across calls; changes only on restart. |
| `user_context_deduced` (230, conditional) | The boot-cached fused user context (region, locale, environment as known at boot). | ~60 tok when present. | Same boot-cache discipline as system_facts. |
| `user_identity_stated` (240, conditional) | The user-STATED identity facts, labeled, with the clarify-don't-guess contract for unstated ones. | ~50 tok when present. | Boot-cached; byte-stable. |
| `tool_index` (400) | One line per tool: name + purpose, scoped to exactly the defs the native `tools` param carries (plus `describe_tool`). | ~200–400 tok, scales with the tool surface. | Byte-stable per turn and across turns with the same tool scope. LEADS the guidance layer so the conversational relevance budget can cut what follows while the capability spine stays. |
| `style_examples` (410) | Five request→reply shape examples, including the file/web/shell policy lines. | ~130 tok. | Byte-stable. **Dropped on conversational turns** (relevance budget) and on later calls that already hold a tool result (staged cut). |
| `selection_hints` (420) | Request-kind → tool mapping (current info → web, files → search, commands → shell…). | ~50 tok. | Byte-stable. Dropped by the same two cuts as style_examples. |
| `on_demand_loading` (430) | Which tools load with full schemas vs. which need `describe_tool` first. | ~50 tok. | Byte-stable. Dropped by the same two cuts; additionally dropped on answer-only calls (no tools offered). |

## The trailing turn-context message — TURN band

Assembled per turn (`sections/turn.py`), rendered after the STATIC prompt as
its own message. Byte-identical within the turn, so iterations 2..n cache
against iteration 1's tail.

| Section (order) | What the model sees | Token effect | Cache effect |
|---|---|---|---|
| `current_intent` (1010) | What this turn is for — the classified intent, leading the band (User Objective Primacy). | ~20 tok, once per turn. | Stable within the turn; expected to change between turns (it is the turn's headline). |
| `environment` (1050) | The current environment block (platform, cwd, time) — per-turn by design. | ~150 tok. | Stable within the turn; changes between turns by design — this is why it lives in the TURN band, never in the STATIC prefix. |
| `memory_facts` (1060) | The retrieved memory weave for this turn. | 0–~200 tok. | Same per-turn discipline. |
| `intent_history` (1065) | The recent intent trail (follow-up accuracy). | ~20 tok. | Per-turn. |
| `workspace_state` (1070) / `todo_state` (1080) / `goal_route` (1090) / `task_state` (1100) / `transcript_focus` (1110) | Workspace snapshot, open checklist, durable-goal route, task-type policy, the transcript pointer. | ~0–150 tok each, only when non-empty. | Per-turn; conditional sections are simply not registered when empty. |
| `skill_fragment` (1160) / `expert_persona` (1170) / `execution_plan` (1190) / `routing_hint` (1200) | Intent-scoped skill guidance, persona framing, the plan, the caller's routing hint. | ~0–500 tok combined. | Per-turn; the loop records each named section it actually sent in the injected-context ledger. |

## Later calls in a turn — the staged input selection

`staging.py`. A call that already holds a tool result does not need the
guidance for choosing its FIRST tool.

| Selector | What the model sees | Token effect | Cache effect |
|---|---|---|---|
| `staged_static_content(with_tools=True)` | The STATIC band minus style_examples, tool_index, selection_hints. Every RULE stays. | ~−350 tok vs. the full render, on later calls only. | Deliberate mid-turn divergence from the first call's prefix: the cut trades some prefix-cache length for tokens. One-way (first call full → later calls staged), so each call still caches against its own predecessor. |
| `staged_static_content(with_tools=False)` | Additionally drops on_demand_loading (an answer-only call cannot load tools). | ~−400 tok. | Same one-way discipline. |
| `staged_system_prompt` (legacy) | The head-string cutter for non-registry surfaces; returns the input untouched when the section heads are absent. | — | No-op on registry-built prompts by contract (pinned by test). |

## The per-turn relevance budget (conversational turns)

`budget.py`. A conversational turn (classified `chat`) does not choose
tools, so the tool-choosing guidance is dead weight — a greeting must not
carry file/web/shell policies.

| Selector | What the model sees | Token effect | Cache effect |
|---|---|---|---|
| `render_static_budgeted(SOCIAL)` | The STATIC band minus the tool-choosing SUFFIX: style_examples, selection_hints, on_demand_loading. The capability index (`tool_index`), every constraint, and every context section stay — the conversation-or-action constraint points at the tool list, so the referenced section survives. | ~−230 tok on the first call of a conversational loop turn. | **A hard, structural constraint**: the dropped set must be a contiguous SUFFIX of the render order — every budgeted render is a byte-PREFIX of the canonical render. A shorter prefix cache-hits against a longer cached one, and the canonical render cache-hits again on the next full turn. A middle cut (drop an early section, keep a later one) would fork the cacheable prefix into two mutually-unprefixable variants — the budget raises `PromptStructureError` instead. Unclassified turns default to FULL: the budget cuts only what the classification is confident does not matter. |
| `relevance_budget` (trace event) | Horizon, dropped section names, static char count — on the durable record for every turn, full or cut. | — | The budget's decision is measurable per turn from the trace, per the observability investigation's ground-truth requirement. |

A misrouted conversational turn that ends up calling a tool regains the full
guidance on its next call: the staged selection renders the full membership
minus the staged excludes.

## The auxiliary-call contract (checkpoint summaries)

`auxiliary.py`. Auxiliary calls spend a model call to produce material the
turn then relies on; an unusable output must never land.

| Component | What the model sees | Token effect | Cache effect |
|---|---|---|---|
| `build_summary_call_prompt` | The EXACT output skeleton — three named sections, in order, `(none)` for empty — plus the verbatim-preservation classes (paths, commands, identifiers, numbers, the user's own wording for a constraint) and no-commentary/no-tools rules. The task-aware policy's focus line rides after the skeleton. | ~200 tok, on compression events only (history over 75% of budget). | One-shot auxiliary call with its own prompt — never shares the turn's cached prefix (it would couple the checkpoint to the conversation's exact bytes). |
| `validate_summary_output` | — (not model-visible; the caller-side gate). | — | — |

Fail-closed: empty output and a missing required section (the signature of
an output-limit cut) both skip compression — the original history stays
intact, never half-replaced.

## The tool schemas and the history

Not in the package, but part of every call's token and cache accounting:

| Component | What the model sees | Token effect | Cache effect |
|---|---|---|---|
| Native `tools` param | The call's callable tool schemas, composed per call: scoped CORE tools + `describe_tool` + any long-tail tools loaded this run. | ~0.5–2K tok depending on scope. | Stable unless the tool surface actually changes within the turn (loaded tools stay loaded — the set only grows, deterministically). |
| Conversation history | Prior turns, tool results (bounded heads + retrieval pointers for large outputs), summary checkpoints. | The dominant per-call cost on long sessions. | Append-mostly; a summary checkpoint REPLACES the oldest slice (the one deliberately destructive boundary in the prefix — the replacement is validated fail-closed per the auxiliary contract). |

## The trace: measuring the triads instead of trusting them

Every turn's durable trace (`turn_traces` store) records, per model call:
payload size + hash (never contents), submit → first-byte → done timings,
and the provider's reported usage — alongside the `relevance_budget` event,
the `context_assembly` sizes, and the injected-items ledger. The
`performance` block on history/export carries the first-token wait and the
final call's decode window, and the tokens-per-second value names its own
denominator. When this file and a live trace disagree, the trace wins.
