# LocalMind vs Codebuff — Deep Architectural Comparison

> Companion to `kickoff.md`. Side-by-side analysis across nine architectural
> dimensions. Every claim is cited to either a LocalMind file path
> (`repos/LocalMind/...`) or a Codebuff file path
> (`repos/open-codebuff/...`). When a system lacks a feature, that is stated
> explicitly rather than glossed.

---

## 0. At-a-Glance Summary

| Dimension | LocalMind | Codebuff |
|---|---|---|
| Primary surface | Electron + React desktop + FastAPI + Typer CLI | React/Ink CLI + `@codebuff/sdk` + Freebuff npm variant |
| Language | Python 3.10+ (backend), TypeScript (frontend) | TypeScript (Bun monorepo) |
| Default model | Ollama local model (e.g. `llama3.1:8b`) | OpenRouter-routed cloud models (Opus, Gemini, MiniMax, DeepSeek, GLM…) |
| Agent count | 8 (browser, coding, research, direct, verifier, reviewer, debugger, analyst) | ~12 built-in store agents + unlimited user agents |
| Tool calling | Native Ollama/OpenAI function calling | Custom XML tag streaming parser (`<codebuff_tool_call>…`) |
| Agent definition | Directory with `agent.py`, `tools.py`, `context_builder.py`, `is_done.py`, `playbook.md` | Single TS object implementing `AgentDefinition` (prompts + `handleSteps` generator) |
| Orchestration | `ThinkingDispatcher` → `AgentOrchestrator` (optional plan+confidence) → `BaseAgent.run()` → `AgentLoop` | `loopAgentSteps` (`run-agent-step.ts:667`) — single loop, programmatic steps via `handleSteps` generator |
| Parallelization | Sequential handoff delegation only (`delegate` tool, `parallelizable=False`) | `spawn_agents` parallel fan-out via `Promise.allSettled` + best-of-N selector |
| Isolation | Per-run `contextvars` (`AgentRunContext`, `_current_depth`), immutable `DelegationInstructionPacket` | Fresh `AgentState` per child (parent ID + ancestor run IDs), shared `fileContext` by reference |
| Memory | Persistent sqlite-vec vector store + nomic-embed-text embeddings | Ephemeral `messageHistory` array + `context-pruner` agent rewrites it under pressure |
| Sandboxing | None for code execution; "trusted user only" | None for terminal commands; "user's full env" |
| Self-modifying context | No (parent context is read-only during delegation) | Yes (`spawn_agent_inline` overwrites parent's `messageHistory`) |
| Recursion cap | `MAX_DELEGATION_DEPTH = 2` (`tools/delegate.py:74`) | `MAX_AGENT_STEPS_DEFAULT = 200` per agent, no spawn-depth limit |
| Wall-clock cap | `DELEGATION_WALL_CLOCK_SECS = 120s` + per-agent `max_wall_clock_secs` | Per-tool `run_terminal_command` timeout (30s default); no per-agent wall clock |
| Result contract | `DelegationResult` dataclass (status, run_id, output, error_type, iterations) | `AgentOutput` discriminated union (lastMessage / allMessages / structuredOutput / error) |
| Observability | `ObsCollector` + `ObservationSnapshot` + SSE events + `/api/observability` | `TraceWriter` callback + `onStateSnapshot` every 5s + per-step ledger |
| Persistence protocol | `.context/` vendored protocol, git-tracked, multi-session memory | `knowledge.md` / `AGENTS.md` / `CLAUDE.md` static files; no protocol |

---

## 1. Agent System — How Agents Are Defined

### 1.1 LocalMind

LocalMind agents live in **directories** under `backend/src/agents/<name>/`.
Per ADR-8 Phase 1 (Session 34, `repos/LocalMind/.context/memory/plans/decisions.md:264-...`),
each agent directory must contain:

- `__init__.py` — re-exports the agent class for backward compatibility
- `agent.py` — the `BaseAgent` subclass
- `tools.py` — a frozenset of allowed tool intents (e.g. `CODING_TOOLS`)
- `context_builder.py` — `build_context()` implementation that loads `playbook.md`
- `is_done.py` — the agent's stop condition
- `playbook.md` — the constraint-style workflow (loaded into the system prompt)

The registry (`agents/registry.py:76`) auto-discovers any subdirectory
that contains an `agent.py` file. Adding a new agent = adding a new
directory — no manual `register()` call needed (though the API is retained
for test doubles and programmatic registration).

Each agent inherits from `BaseAgent` (`agents/base_agent.py:78`) which
mandates four abstract methods: `config()`, `build_context()`, `is_done()`,
`description()`. The shared `run()` method delegates to the existing
`AgentLoop` in Phase 1 (current state) and will host the actual 5-step
loop in Phase 2.

The eight agents (`localmind.md:74-86`) are: `browser`, `coding`,
`research`, `direct`, `verifier`, `reviewer`, `debugger`, `analyst`. Each
has a scoped toolset — `coding` has 8 tools (shell, file_task, file_write,
edit_file, code_exec, git, process, delegate), `analyst` has only 3
(file_task, git, delegate) because it "reads and understands, doesn't
build."

### 1.2 Codebuff

Codebuff agents are TypeScript objects implementing the `AgentDefinition`
interface (`repos/open-codebuff/agents/types/agent-definition.ts:21-269`).
The shape includes:

- `id`, `publisher`, `version` — for the Agent Store
- `model: ModelName` — each agent picks its own OpenRouter model
- `toolNames` — explicit allowlist (no scoped-toolset directory)
- `spawnableAgents` — whitelist of children this agent may spawn
- `inputSchema` / `outputSchema` — Zod-validated structured I/O
- `outputMode: 'last_message' | 'all_messages' | 'structured_output'`
- `systemPrompt`, `instructionsPrompt`, `stepPrompt` — three prompt slots
- `handleSteps?: (ctx) => Generator<ToolCall | 'STEP' | 'STEP_ALL' | StepText | GenerateN>` —
  this is the key lever: an agent can be **a program**, not just a prompt

The built-in store agents (`agents/base2/base2.ts`, `agents/editor/editor.ts`,
`agents/basher.ts`, `agents/file-explorer/file-picker.ts`,
`agents/thinker/best-of-n/thinker-best-of-n.ts`, etc.) number ~12, but
users can add their own by dropping a `.ts` file in `.agents/` (loaded by
`sdk/src/agents/load-agents.ts:201-337`).

### 1.3 Comparison

Both systems converge on **agents-as-directories/packages** rather than
scattered modules. LocalMind's directory layout (ADR-8) is more rigid —
it mandates `agent.py`, `tools.py`, `context_builder.py`, `is_done.py`,
`playbook.md`. Codebuff's `AgentDefinition` is a single TS object that
can optionally have a `handleSteps` generator; co-location is via the
`agents/<name>/` directory convention but not enforced by a registry
auto-discovery algorithm.

The crucial difference is **the `handleSteps` generator**. A Codebuff
agent can encode procedural logic — "first call `set_messages` to trim,
then spawn 3 parallel editors with different prompts, then spawn a
selector, then convert the winner's `propose_*` calls to real edits" —
as a readable TypeScript function (`agents/editor/best-of-n/editor-multi-prompt.ts:58-246`).
LocalMind agents have no equivalent: their behavior is entirely governed
by the `playbook.md` text injected into the system prompt, plus the
model's own reasoning over the scoped toolset.

This means **Codebuff can express best-of-N, propose/select/apply,
and inline context mutation as first-class agent shapes**, while
LocalMind must rely on the model's prompt adherence to implement
similar workflows. The trade-off: Codebuff agents are harder to write
(need TypeScript, need to think procedurally) but more deterministic;
LocalMind agents are easier to write (just edit a markdown playbook)
but more probabilistic.

---

## 2. Tools — Inventory and Contract

### 2.1 LocalMind

LocalMind ships 14 tools (the `localmind.md:130-148` table lists 11 but
`git_tool.py`, `process_tool.py`, `delegate.py`, `diagnostics.py` bring
the actual count to ~14). Each tool is a self-contained Python module in
`backend/src/tools/<name>.py` exposing `async def run(input, context) -> ToolResult`.

The `ToolResult` contract (`core/models.py`) carries `content`, `risk`
(`LOW`/`MEDIUM`/`HIGH`), `source`, `success`, `error_type`, and optional
`metadata`. Risk levels gate permission: `HIGH` tools (file_write,
edit_file) require explicit user permission; `MEDIUM` tools (code_exec,
shell, browser) are configured via env flags (`LOCALMIND_CODE_EXEC_ENABLED`,
`LOCALMIND_SHELL_ENABLED`).

Tools are registered via `register_tool(Intent, fn, description, cost,
latency_ms, parallelizable)` in `tools/__init__.py`. The `Intent` enum is
the routing key — `Intent.SHELL → shell`, `Intent.FILE_WRITE → file_writer`,
etc. The `parallelizable` field exists but is unused at runtime —
LocalMind's `delegate` tool registers `parallelizable=False` (`tools/delegate.py:486`)
and there is no parallel tool execution primitive.

### 2.2 Codebuff

Codebuff has ~35 tools (`codebuff-deep-profile.md` Appendix B). The roster
includes the expected file/shell/search tools but also: `propose_str_replace`
/ `propose_write_file` (stage edits without applying), `set_messages` /
`add_message` / `set_output` (manipulate the agent's own history),
`spawn_agents` / `spawn_agent_inline` (delegation), `add_subgoal` /
`update_subgoal` / `create_plan` (subgoal scratchpad), `ask_user` /
`suggest_followups` / `render_ui` (UX), `think_deeply` (forced
brainstorming step), `skill` (load markdown skill on-demand).

Tools are defined via `common/src/tools/params/tool/<name>.ts` files
that export a Zod-validated param schema plus a `tool` constant. The
handler registry (`packages/agent-runtime/src/tools/handlers/list.ts:56-99`)
maps tool names to async handler functions.

The contract for return values is loose — handlers can return strings,
objects, or throw. The `spawn_agents` handler returns a structured
`AgentOutput[]` (`spawn-agents.ts:198-216`); most other handlers return
strings that get appended to `messageHistory` as tool messages.

### 2.3 Comparison

Codebuff's tool inventory is roughly **2.5× larger** than LocalMind's,
and the difference is in three categories that LocalMind lacks entirely:

1. **Self-modification tools** (`set_messages`, `add_message`, `set_output`)
   — the agent can rewrite its own conversation history mid-turn.
2. **Propose-stage tools** (`propose_str_replace`, `propose_write_file`)
   — edits can be staged without applying, enabling best-of-N selection.
3. **Subgoal/plan tools** (`add_subgoal`, `update_subgoal`, `create_plan`)
   — a structured scratchpad that survives across steps within one run.

LocalMind's tool surface is deliberately minimal: each tool does one
thing, and the agent's playbook governs multi-tool orchestration. This
is the right design for a system targeting small local models
(`llama3.1:8b`, `gemma3:1b`) where a smaller tool surface improves
selection reliability (ADR-6 point 6). Codebuff's broader surface
assumes a stronger base model (Opus, Gemini Pro) that can pick correctly
from 35 options.

The **`propose_*` family is the single most impactful tool pattern
LocalMind is missing**. Without it, LocalMind cannot express best-of-N
editing: the model must commit to one edit, run it, observe failure, and
retry. Codebuff's editor agents produce 3-5 parallel proposals, a
selector picks the winner, and the parent applies it — a workflow that
is structurally impossible in LocalMind today.

---

## 3. Orchestration — How an Agent Is Picked and Run

### 3.1 LocalMind

LocalMind's pipeline (described in `core/agent/orchestrator.py:1-28` and
`localmind.md:74-90`) is three layers:

1. **Chat Agent (Layer 1)** — acknowledges and reformulates the user
   message.
2. **AgentOrchestrator (Layer 2, optional)** — makes a planning LLM call
   (no tools, low temperature) that produces JSON with `steps[]`,
   `confidence` (0.0–1.0), and `needs_clarification`. If confidence ≥
   `ORCHESTRATOR_CONFIDENCE_HIGH`, proceed; if medium, ask one
   clarifying question; if low, escalate to the user. The orchestrator
   can also `replan()` after a step failure — receiving the failed step
   and a failure reason, it produces an updated plan.
3. **Execution Agent (Layer 3)** — `BaseAgent.run()` → `AgentLoop.run()`
   with the orchestrator's context injected.

Agent selection is done by `agents/selection.py` which has two maps:
`_INTENT_TO_AGENT` (Phase 1–3 fallback) and `_DOMAIN_TO_AGENT` (ADR-8
Phase 4 — `primary_domain` from `ThinkingDispatcher` takes precedence
over intent). The registry is consulted via `get_agent(name)`.

The AgentLoop itself (`core/agent/loop.py`, ~110KB) implements a
plan-execute-verify loop: a planning LLM call produces a step-by-step
plan that's injected into the system prompt, then the loop iterates
(assemble → call → parse → execute → observe) up to `MAX_ITERATIONS = 8`
(configurable via `LOCALMIND_MAX_ITERATIONS`) and `MAX_WALL_CLOCK_SECS
= 180s` (configurable). After `file_write`, the file is read back to
confirm; after `code_exec`, the output is checked for error indicators.

### 3.2 Codebuff

Codebuff's pipeline (`packages/agent-runtime/src/main-prompt.ts:167` →
`run-agent-step.ts:667`) is a single loop with a programmatic pre-step:

1. `initialSessionState()` loads `.agents/*.ts`, knowledge files,
   tree-sitter code map.
2. `callMainPrompt()` → `assembleLocalAgentTemplates` builds the system
   prompt with tool docs as XML in the prompt (not native `tools` param).
3. `loopAgentSteps` iterates. Each iteration:
   - `runProgrammaticStep` — if the agent has a `handleSteps` generator,
     advance it. It may yield tool calls, `'STEP'` (one LLM call with
     tools), `'STEP_ALL'` (LLM call until no more tool calls), synthetic
     text, or `GENERATE_N` (N parallel completions).
   - `runAgentStep` — make one LLM call, stream the response, parse
     `<codebuff_tool_call>{json}</codebuff_tool_call>` tags, execute
     each tool (handlers may spawn subagents).
   - `addAgentStep` — append the step to the agent's ledger.
   - `shouldEndTurn` check — if the model didn't emit tool calls and
     isn't in mid-tool-execution, end.

There is **no separate orchestrator layer**. The orchestrator role is
encoded in the base agent's `handleSteps` generator (`agents/base2/base2.ts:53-579`)
which: (a) optionally spawns `context-pruner` inline before each step,
(b) yields `'STEP_ALL'` to let the model run, (c) checks for special
user mention tokens (`@AgentName`) and rewrites them to `spawn_agents`
calls, (d) applies `cloud_plan_ready` signaling for async planning.

Confidence-based escalation (LocalMind's medium-confidence "ask one
clarifying question") has no direct equivalent in Codebuff. The model
either calls `ask_user` (multiple-choice) or proceeds; there's no
numerical confidence score produced by a planning call.

### 3.3 Comparison

LocalMind has a **separate orchestrator layer with explicit confidence
scoring and replanning**. Codebuff has **no orchestrator layer** — the
orchestration logic is encoded procedurally in the base agent's
`handleSteps` generator.

Both approaches are defensible. LocalMind's design gives a clean
three-layer separation (chat / plan / execute) that's easy to reason
about and easy to disable (`ORCHESTRATOR_ENABLED=False` reverts to
direct mode). Codebuff's design is more compact and lets the
orchestrator evolve with the base agent — but it also means changing
orchestration logic requires editing `base2.ts:53-579`, a 500-line file,
rather than a separate module.

The **replan() loop** in LocalMind (`orchestrator.py:361-511`) is a
distinct feature: when an execution step fails, the orchestrator
receives the failure context and produces an updated plan that avoids
the failed approach. Codebuff has no equivalent — a failed tool call
just becomes a tool message in history, and the model is expected to
react to it on the next step. This is a real LocalMind advantage worth
preserving.

---

## 4. Isolation — How Agent Runs Are Separated

### 4.1 LocalMind

LocalMind's isolation model is **immutable instruction packets +
contextvars**. The `DelegationInstructionPacket` dataclass
(`core/agent/delegation.py:23-140`) is frozen — `target_agent`,
`objective`, `scope`, `constraints`, `forbidden_tools`, `input_evidence`,
`output_requirements`. The child agent receives only this packet as its
sole user message; it does **not** inherit the parent's `messageHistory`,
memory facts, or trace.

Per-run identity is tracked via `AgentRunContext` (`delegation.py:143-173`)
with a `run_id` (UUID hex), `agent_name`, `instruction`, `parent_run_id`,
and `started_at`. The current run ID is stored in a `contextvars.ContextVar`
(`_current_run_id`, `delegation.py:203-206`) so nested delegations form a
chain — but the chain is metadata-only, not a context-inheritance chain.

Recursion depth is capped at `MAX_DELEGATION_DEPTH = 2`
(`tools/delegate.py:74`): A delegates to B (depth 1), B can delegate to
C (depth 2), C cannot delegate further. A wall-clock cap
(`DELEGATION_WALL_CLOCK_SECS = 120s`, `delegate.py:80`) prevents a
single delegation from consuming the entire turn budget.

The child's adapter is shared with the parent (set via `_current_adapter`
ContextVar in `delegate.py:444-449`), so the child uses the same model +
provider. The child's `AgentConfig.allowed_tools` is honored — CodingAgent
delegating to DirectAgent as a sub-agent gets a single model call, no
tools (`tools_enabled=False`).

### 4.2 Codebuff

Codebuff's isolation model is **fresh AgentState per child + shared
fileContext by reference**. When `spawn_agents` runs
(`packages/agent-runtime/src/tools/handlers/tool/spawn-agent-utils.ts:113-441`),
it constructs a new `AgentState` with:

- A fresh `agentId` (UUID)
- `parentId` set to the parent's `agentId`
- `ancestorRunIds` carrying the run-chain for telemetry
- A fresh `messageHistory` (empty or seeded with the spawn prompt)
- A fresh `stepsRemaining = MAX_AGENT_STEPS_DEFAULT = 200`
- `creditsUsed = 0` (cost accumulates per child, then rolls up to parent)

The child does **not** share the parent's `messageHistory` by default —
the `includeMessageHistory` flag on `AgentDefinition` is `false` by
default. The exception is `spawn_agent_inline`
(`spawn-agent-inline.ts:26-178`), which **does** share the parent's
history and system prompt (for prompt caching) and then **overwrites**
the parent's history with its own at line 174 — used by `context-pruner`
to compact context transparently.

The shared `fileContext` (`sdk/src/run-state.ts:61-65`) is a mutable
object holding proposed file contents, file change hooks, etc. It's
shared **by reference** across all agents in a run, so a child's
`propose_*` calls are visible to the parent without explicit return.

### 4.3 Comparison

LocalMind's isolation is **stricter but more rigid**. The
`DelegationInstructionPacket` is immutable, the child sees only what
the parent explicitly puts in the packet, and there's no shared mutable
state between parent and child. This is good for predictability — a
child can't accidentally corrupt the parent's context — but it means
the parent must explicitly pass everything the child needs (which can
be verbose) and explicitly receive everything back (via the
`DelegationResult.output` string).

Codebuff's isolation is **looser but more flexible**. The default is
still "fresh history per child" (`includeMessageHistory: false`), but
the `spawn_agent_inline` escape hatch lets a child mutate the parent's
history — enabling the `context-pruner` pattern that LocalMind has no
way to express. The shared `fileContext` is a deliberate leak that lets
`propose_*` calls flow up without explicit return values.

The **`spawn_agent_inline` pattern is the most consequential isolation
difference**. LocalMind would need a new primitive (something like
`delegate_inline(target_agent, task, mutate_parent_history=True)`) to
support it — and would need to think carefully about safety, since a
misbehaving inline child could corrupt the parent's transcript.

---

## 5. Parallelization — Concurrent Agent Execution

### 5.1 LocalMind

LocalMind's delegation is **strictly sequential handoff**
(`tools/delegate.py:40-46`, "Parallel vs handoff: this implementation
is HANDOFF"). The `parallelizable` field on `register_tool` exists but
is unused — there is no `asyncio.gather()` over multiple `delegate`
calls, no `TaskGroup` for concurrent sub-agent runs, no barrier primitive.

The closest thing to parallelism in LocalMind is **within a single
tool**: `web_search.py` races DuckDuckGo and SearXNG in parallel via
`asyncio.gather`, returning the first successful result with Brave as
a sequential fallback. But this is tool-internal, not agent-level
parallelism.

The `should_use_sub_agents()` heuristic in `core/agent/sub_agent.py`
(legacy, ~50KB) does have an `execute_sub_tasks()` path that uses
`asyncio.gather()` for independent sub-tasks — but ADR-8 Phase 3
explicitly deprecates this in favor of agent-initiated delegation
(`tools/delegate.py:21-29`), and the current `delegate` tool does not
use it.

### 5.2 Codebuff

Codebuff has **first-class parallel fan-out** via `spawn_agents`
(`spawn-agents.ts:34-263`). The handler accepts an array of agent
specs, calls `Promise.allSettled(agents.map(...))` at line 89, and
returns when all children have completed (or failed). Each child runs
`loopAgentSteps` recursively on its own `AgentState`.

Two patterns build on this:

1. **Best-of-N editor** (`agents/editor/best-of-n/editor-multi-prompt.ts:58-246`):
   spawn N editor children with different strategy prompts in parallel,
   each returns `{ toolCalls, toolResults, unifiedDiffs }` as structured
   output; then spawn one `best-of-n-selector2` with all implementations
   as params; the parent applies the winner's tool calls as real edits.
2. **Best-of-N thinker** (`agents/thinker/best-of-n/thinker-best-of-n.ts`):
   spawn N thinker children with different reasoning prompts in parallel,
   each returns a structured analysis; the parent (or a selector) picks
   the most useful one.

There's also `GENERATE_N` (`run-programmatic-step.ts`) — a yield from
`handleSteps` that requests N parallel completions from the same model
with the same prompt (cheap diversity for selection). This is distinct
from `spawn_agents` because it's one model call with N samples, not N
agent runs.

### 5.3 Comparison

This is **LocalMind's biggest gap**. Without parallel delegation, it
cannot express:

- **Best-of-N editing** — produce 3 candidate edits, pick the best.
- **Parallel research + coding** — research the API while coding starts
  on the skeleton.
- **Multi-perspective review** — run reviewer, debugger, and security
  auditor concurrently on the same diff.
- **Speculative execution** — start a "max" path and a "lite" path in
  parallel, cancel the loser when the winner produces output.

The fix is well-understood: add a `delegate_parallel(targets: [{agent,
task}, ...])` tool that uses `asyncio.gather()` over multiple
`agent.run()` coroutines, with the same `MAX_DELEGATION_DEPTH` and
wall-clock caps as the sequential `delegate`. The result contract
(`DelegationResult[]`) already exists — it's just an array of the
existing `DelegationResult`.

The deeper question is whether **the underlying model can use this
primitive well**. Codebuff's editor agents are Claude Opus 5 — a model
that can be trusted to produce 3 high-quality candidate edits in
parallel. LocalMind targets `llama3.1:8b` and smaller, where each
individual edit may be unreliable enough that picking the "best of 3"
is still picking from a weak field. **Parallel delegation may need to
wait for stronger local models** — or LocalMind could route parallel
sub-agent runs to a cloud model (the existing OpenAI-compat adapter
supports this) while keeping the orchestrator on the local model.

---

## 6. Delegation — Hand-off Semantics

### 6.1 LocalMind

LocalMind's `delegate` tool (`tools/delegate.py`) is **handoff only**.
The calling agent blocks on `asyncio.wait_for(_collect_sub_agent_response(),
timeout=DELEGATION_WALL_CLOCK_SECS)` until the sub-agent finishes, then
continues with the sub-agent's output string in its context (as a tool
message).

The result is wrapped in a `ToolResult` whose `content` is a markdown
string (`## Delegated to {target_agent} agent\n\n**Sub-task:** ... \n\n
**Sub-agent response:** ...`). The `metadata` field carries structured
`instruction`, `run`, and `delegation` sub-objects — useful for UI
observability but not for programmatic selection (the parent model sees
the markdown string, not the structured metadata).

The `DelegationInstructionPacket` (`delegation.py:23`) is the
**contract** between parent and child. Notable fields:

- `forbidden_tools: tuple[str, ...]` — parent can suppress specific
  tools in the child (e.g. "research this, but don't run shell commands").
  Propagated in `delegate.py:310` via `child_allowed_tools.difference(packet.forbidden_tools)`.
- `input_evidence: str` — untrusted data the child should treat as
  data, not instructions. Delimited in the prompt with
  `--- BEGIN UNTRUSTED EVIDENCE ---` / `--- END UNTRUSTED EVIDENCE ---`
  (`delegation.py:113-123`) — a prompt-injection mitigation.
- `output_requirements: tuple[str, ...]` — explicit "report contract"
  telling the child what to return.

### 6.2 Codebuff

Codebuff has **three delegation mechanisms**, each with a different
semantic:

1. **`spawn_agents`** (structured fan-out, parallel) — child runs to
   completion, returns an `AgentOutput` discriminated union:
   `{ type: 'lastMessage', value }`, `{ type: 'allMessages', value }`,
   `{ type: 'structuredOutput', value }` (Zod-validated against
   `outputSchema`), or `{ type: 'error', message, statusCode, ... }`.
   The parent's LLM sees this as a `tool` message in its next step.

2. **Agent-as-direct-tool-call** (`buildAgentToolSet`) — each spawnable
   agent is also exposed as a tool with the agent's short-name (e.g.
   `file_picker`). When the model emits
   `<codebuff_tool_call>{ "cb_tool_name": "file_picker", ... }</codebuff_tool_call>`,
   `tryTransformAgentToolCall` rewrites it to a `spawn_agents` call
   internally. This gives the model a more natural interface for
   single-agent delegation while keeping the same execution path.

3. **`spawn_agent_inline`** — child shares the parent's `messageHistory`
   and system prompt, runs to completion, and **overwrites** the parent's
   history with its own (`spawn-agent-inline.ts:174`). Used by
   `context-pruner` to compact context transparently before every
   main-agent step.

The `spawnableAgents` whitelist (`agent-definition.ts:131-138`) limits
which agents a parent may spawn. The base orchestrator's whitelist
varies by mode (`agents/base2/base2.ts:148-168`): `default` mode allows
~15 children; `max` mode adds `-max` variants and best-of-N agents;
`lite`/`free` modes are stripped down. The `getMatchingSpawn` function
(`spawn-agent-utils.ts:113-169`) parses publisher/version from both
sides and matches on agent-id, optionally with wildcards.

### 6.3 Comparison

LocalMind's delegation is **cleaner contract-first** — the
`DelegationInstructionPacket` explicitly enumerates objective, scope,
constraints, forbidden tools, input evidence, and output requirements.
Codebuff's delegation is **looser schema-first** — the input/output
shape is defined by `inputSchema`/`outputSchema` (Zod), but there's no
explicit "constraints" or "forbidden tools" field on the spawn call.

The `input_evidence` delimiter pattern in LocalMind
(`delegation.py:113-123`) is a real prompt-injection mitigation that
Codebuff lacks — Codebuff passes `params` directly to the child as a
user message without untrusted-data framing.

Codebuff's three-mechanism split is more expressive but harder to
learn. A new agent author has to choose between `spawn_agents` (when?),
agent-as-tool (when?), and `spawn_agent_inline` (almost never — it's
for framework internals like context-pruner). LocalMind has one
mechanism — `delegate` — and the choice is just "which target agent."

The **agent-as-tool-call pattern** is worth borrowing: it gives the
model a natural verb-like interface ("file_picker(...)" reads better
than "spawn_agents([{agent: 'file-picker', ...}])") without changing
the execution path. This is a low-risk improvement LocalMind could
adopt.

---

## 7. Memory — Persistent vs Ephemeral

### 7.1 LocalMind

LocalMind has a **persistent vector memory store** — sqlite-vec +
`nomic-embed-text` embeddings (`localmind.md:131-137`, `storage/vector.py`).
Tell the agent "remember that..." and it stores the fact with its
embedding. On every subsequent turn, relevant facts are passively
retrieved and injected into the system prompt before the model call.

Memory operations are exposed via the `memory_op` tool (store, recall,
list, delete). The `Memory` class (`core/memory.py`) handles embedding
generation (via the Ollama adapter's `/api/embeddings` endpoint),
similarity search (cosine similarity via sqlite-vec), and CRUD.

Beyond semantic memory, LocalMind has the **`.context/` protocol** —
a vendored git-tracked memory system for agent sessions (kickoff.md,
memory/workflows/active.md, memory/tasks/current.md, memory/agents/sessions.md,
memory/plans/decisions.md as append-only ADR log, memory/flaws/log.md,
memory/inefficiencies/log.md, memory/sessions/<date>-N/notes.md).
This is **multi-session memory** — it survives across CLI invocations
and is shared between local and cloud agents.

### 7.2 Codebuff

Codebuff has **no persistent vector memory**. The single source of
truth is `agentState.messageHistory` — an array of `Message` objects.
Between CLI sessions, the host is responsible for persistence (the SDK
does not write to disk).

When history exceeds the model's context window, the `context-pruner`
agent runs (`agents/context-pruner.ts:13-944`):

- Walks `messageHistory`, separating user/assistant/tool messages.
- For blacklisted agent outputs (file-picker, researcher-web, basher,
  code-reviewer, librarian, tmux-cli, browser-use — lines 51-62), drops
  the `spawn_agents` result entirely.
- Truncates long messages: `USER_MESSAGE_LIMIT = 13_000`,
  `ASSISTANT_MESSAGE_LIMIT = 1_300`, `TOOL_ENTRY_LIMIT = 5_000` chars.
- Builds a token-budgeted summary and replaces the history with
  `{ header: SUMMARY_HEADER, ...summary, footer: SUMMARY_DISCLAIMER }`.
- Spawned **inline** before every main-agent step via the base agent's
  `handleSteps` (`agents/base2/base2.ts:393-471`), so the parent's
  history is rewritten in-place.

Static context comes from `knowledge.md`, `AGENTS.md`, or `CLAUDE.md`
in the project root (priority: knowledge > AGENTS > CLAUDE), loaded
into the system prompt via the `{CODEBUFF_KNOWLEDGE_FILES_CONTENTS}`
placeholder. There's also a `skills` system (`sdk/src/skills/load-skills.ts:47-250`)
— markdown files with YAML frontmatter loaded on-demand via the `skill`
tool, a lightweight prompt-injection mechanism.

A `TraceWriter` callback receives the full message history at each
step boundary (`run-agent-step.ts:427-435`) for replay/debug.

### 7.3 Comparison

This is **LocalMind's clearest advantage**. Persistent semantic memory
means a user can say "remember that the deploy script is at
`scripts/deploy.sh`" and the agent will recall that fact in every
future session. Codebuff has no equivalent — each session starts fresh,
and the only cross-session continuity is whatever the host persists
(typically nothing, since the SDK doesn't write to disk).

The `.context/` protocol is a more structured cross-session memory
system than Codebuff's `knowledge.md` / `AGENTS.md` convention. It has
typed files for current task, backlog, decisions (ADRs), flaws,
inefficiencies, sessions, system info, user identity/preferences —
vs Codebuff's single `AGENTS.md` blob.

The **`context-pruner` agent** is a Codebuff idea worth borrowing.
LocalMind's context window management is implicit (the `AgentLoop`
trims oldest-first near the limit per `localmind.md:163`). A dedicated
pruner agent that summarizes old tool outputs (replacing them with
`{ contentOmittedForLength: true }` stubs, preserving the conversation
narrative) would be more token-efficient. The `simplifyReadFileResults`
and `simplifyTerminalCommandResults` helpers in Codebuff are concrete
implementations of this idea.

---

## 8. Safety — Kill Switches, Caps, Sandboxing

### 8.1 LocalMind

LocalMind safety surface:

- **Risk levels** (`ToolResult.risk`): `LOW` (no gating), `MEDIUM`
  (env-flag gated: `LOCALMIND_CODE_EXEC_ENABLED`, `LOCALMIND_SHELL_ENABLED`),
  `HIGH` (per-call user permission).
- **Per-tool timeouts**: `code_exec` 30s (`LOCALMIND_CODE_EXEC_TIMEOUT`),
  `shell` 20s (`LOCALMIND_SHELL_TIMEOUT`).
- **Iteration cap**: `MAX_ITERATIONS = 8` (`LOCALMIND_MAX_ITERATIONS`),
  raised from 5 in v0.9 to accommodate plan-execute-verify phases.
- **Wall-clock cap**: `MAX_WALL_CLOCK_SECS = 180s`
  (`LOCALMIND_MAX_WALL_CLOCK_SECS`).
- **Delegation recursion cap**: `MAX_DELEGATION_DEPTH = 2` (`delegate.py:74`).
- **Delegation wall-clock cap**: `DELEGATION_WALL_CLOCK_SECS = 120s`
  (`delegate.py:80`).
- **Safety gate**: `core/safety_gate.py` — pre-execution permission
  checks for HIGH-risk tools.
- **Workspace feedback loop**: `core/workspace_state.py` injects
  `git status` / `git diff` into context every turn (ADR-5) so the
  model sees the consequences of its edits.
- **Check-before-acting workflow**: `backend/data/workflows/safety.md`
  is injected into every agent's system prompt via
  `build_agent_system_prompt()` — "every tool invocation that creates,
  writes, modifies, or deletes something MUST first check whether the
  target already exists."
- **Hit-limit-aware fallback**: when `trace.hit_limit` is True,
  `_summarize_trace_for_user()` says "iteration limit reached" and
  suggests "tell me to continue" — never "switch to a larger model"
  (Session 32 contract).

Code execution is **not sandboxed** — it runs with the user's full
Python environment. Shell is similarly unconfined. The README calls
this out: "Code execution is not sandboxed — trusted-user only."

### 8.2 Codebuff

Codebuff safety surface:

- **Step cap**: `MAX_AGENT_STEPS_DEFAULT = 200` per agent
  (`common/src/constants/agents.ts:95`). Each `runAgentStep` decrements
  `stepsRemaining`; at zero, `shouldEndTurn = true`.
- **Stream recovery**: `classifyStreamEndRecovery` detects dropped
  streams / output-budget exhaustion, pushes a `STREAM_INTERRUPTED` or
  `OUTPUT_LIMIT` tagged message, forces another step. After
  `MAX_CONSECUTIVE_STREAM_RECOVERIES = 3` (`stream-parser.ts:49`), the
  turn fails loudly.
- **Output schema retry**: if an agent has `outputSchema` but tries to
  end without `set_output`, retry once with a system message reminder.
- **Abort signal**: `AbortSignal` threaded through every layer
  (`RunOptions.signal`); `loopAgentSteps` checks `signal.aborted` at
  the top of each iteration and throws `AbortError`.
- **Steering**: `drainSteeringMessages` lets the host inject user
  messages at step boundaries without aborting — smoother UX than
  cancel-and-re-run.
- **State snapshots**: `onStateSnapshot` fires every 5s, JSON-clones
  `mainAgentState` (not `fileContext`) for crash recovery.
- **Terminal command safety** (`run-terminal-command.ts:307-585`):
  - Process group isolation on POSIX (`detached: true`).
  - `taskkill /t /f` on Windows for tree-kill.
  - `BoundedOutputBuffer` caps retained output at 50,000 chars.
  - SIGTERM → 1.5s grace → SIGKILL escalation.
  - `exitSweep` registers `process.on('exit')` handler.
- **System prompt warnings**: `agents/base2/base2.ts:194` explicitly
  warns against `git push`, `git commit`, package installs, production
  scripts unless the user asks.

**Notably absent in Codebuff** (`codebuff-deep-profile.md` §9.7):
no file-write allowlist/denylist, no code execution sandbox, no
per-tool wall-clock cap (other than terminal), no recursive spawn
depth limit beyond the per-agent step cap.

### 8.3 Comparison

LocalMind's safety surface is **more defense-in-depth on the
orchestration side** (iteration caps, wall-clock caps, recursion caps,
delegation caps, hit-limit-aware fallback messaging). Codebuff's
safety surface is **more defense-in-depth on the process side**
(process groups, exit sweeps, bounded output buffers, abort signals,
state snapshots, steering without abort).

The two systems have complementary strengths:

- LocalMind could borrow Codebuff's **abort signal threading** —
  currently `AgentLoop.run()` has no clean cancellation path; an
  `AbortSignal`-style argument would let the UI cancel a running agent
  cleanly.
- LocalMind could borrow Codebuff's **bounded output buffer** for
  `shell` and `code_exec` — currently these have a 4000-char output
  cap (`localmind.md:111`) but no head+tail retention.
- Codebuff could borrow LocalMind's **per-delegation wall-clock cap**
  — Codebuff has no `DELEGATION_WALL_CLOCK_SECS` equivalent, so a
  single misbehaved sub-agent could burn its full 200-step budget
  (which could be minutes).
- Codebuff could borrow LocalMind's **hit-limit-aware fallback
  messaging** — when `stepsRemaining` hits zero, Codebuff emits
  `STEP_WARNING_MESSAGE` but doesn't diagnose "iteration limit reached"
  vs "model overload" the way LocalMind does.

Both systems punt on sandboxing code execution, which is a real risk
for both. Neither uses Docker, firejail, nsjail, or any other
confinement. This is an open problem.

---

## 9. Model Layer — Provider Abstraction

### 9.1 LocalMind

LocalMind has two adapters:

- **Ollama adapter** (`adapters/ollama.py`) — talks to
  `http://localhost:11434` via Ollama's `/api/chat` endpoint with
  native tool calling.
- **OpenAI-compat adapter** (`adapters/openai_compat.py`) — talks to
  any OpenAI-compatible API (Zen, OpenRouter, DeepSeek, etc.).

The adapter interface (`adapters/base.py`) exposes `chat()` (streaming)
and `chat_with_tools()` (tool-calling). The `ModelRouter`
(`core/model_router.py`) picks the adapter based on config.

Provider quirks are documented in `AGENTS.md:100-128`:

1. Trailing `tool` role → 400 on some providers. Fix: `chat_with_tools`
   appends a synthetic `user` message when the last message is `tool`.
2. Phase 1 detection must wait for content, not just reasoning.
   DeepSeek-v4-flash-free produces 80+ reasoning chunks before the
   tool_call delta arrives.

The model is configured per-session via `OLLAMA_MODEL` env var (or
auto-detected). There is **no per-agent model selection** — every agent
uses the same model.

### 9.2 Codebuff

Codebuff routes all traffic through its own backend
(`sdk/src/impl/model-provider.ts:81-151`) which forwards to
OpenRouter. The backend centralizes billing, enforces
`data_collection: 'deny'` on every paid request, supports BYOK
(`BYOK_OPENROUTER_HEADER`), and free-tier gating
(`FREEBUFF_ACTING_USER_HEADER`).

Each agent picks its own model (`agents/types/agent-definition.ts:380-463`
lists ~50 recommended models). Examples:

- `base2` (orchestrator): `OPUS_MODEL` (Claude Opus 5) for default/max,
  `LITE_MODEL` for lite, `FREEBUFF_MINIMAX_M3_MODEL_ID` for free.
- `basher` and `file-picker`: Gemini 3.5 Flash Lite (cheap, fast).
- `thinker`: Opus (heavy reasoning).
- `librarian`: MiniMax M3 (free-tier-capable).
- `code-reviewer-deepseek`: DeepSeek.

The `CODEBUFF_REVIEWER_BY_MODEL` map (`base2.ts:47-51`) picks a reviewer
whose model matches the parent's tier — a free-tier session gets
`code-reviewer-deepseek-flash`, a paid Opus session gets
`code-reviewer`. The `canFreebuffModelSpawnGeminiThinker` gate
(`base2.ts:96`) limits which free models can pull a premium Gemini Pro
thinker.

`inheritParentSystemPrompt` exists specifically to enable prompt
caching: a child that inherits the parent's system prompt keeps the
same prefix, so Anthropic's 5-minute ephemeral cache hits. The
`context-pruner`'s `cacheExpiryMs: 30 * 60 * 1000` param sets the
expectation.

### 9.3 Comparison

Codebuff's **per-agent model routing** is a sophisticated cost
engineering lever that LocalMind completely lacks. LocalMind uses one
model for everything — a `llama3.1:8b` coding agent also handles
research, browser, review, and analysis. Codebuff uses Opus for the
orchestrator and thinker, Gemini Flash Lite for basher and file-picker
(cheap, fast), MiniMax M3 for librarian (free-tier-capable), DeepSeek
for code-review.

This matters because **not every agent needs the same model size**.
A file-picker that just lists files doesn't need Opus. A thinker that
reasons about architecture doesn't benefit from a fast cheap model.
Per-agent routing lets you spend tokens where they matter.

LocalMind could implement this by extending `AgentConfig` with a
`model: Optional[str]` field — when set, the agent constructs its own
adapter with that model (via the OpenAI-compat adapter if the model is
cloud, via a separate Ollama adapter if it's a different local model).
The plumbing already exists (the `delegate` tool passes the parent's
adapter to the child); the change is to let the child override it.

The other Codebuff idea worth borrowing is **prompt-cache-aware
inheritance**. When a child agent inherits the parent's system prompt
prefix, Anthropic's cache hits and the call is cheaper. LocalMind's
delegation currently gives the child a fresh prompt; an opt-in
`inherit_parent_prompt=True` flag on `DelegationInstructionPacket`
could enable this for cloud-model delegations.

---

## 10. Synthesis — Where Each System Wins

### 10.1 LocalMind wins on:

- **Persistent semantic memory** — sqlite-vec + nomic-embed-text,
  passive retrieval on every turn. Codebuff has nothing equivalent.
- **Multi-session protocol** — `.context/` vendored protocol with
  typed memory files, ADRs, flaws, inefficiencies. Codebuff has only
  `AGENTS.md`.
- **Strict delegation isolation** — immutable instruction packets,
  untrusted-evidence delimiters, `forbidden_tools` propagation,
  explicit output requirements. Codebuff's spawn is looser.
- **Hit-limit-aware fallback** — diagnostic messaging that
  distinguishes "iteration limit reached" from "model overload."
  Codebuff's `STEP_WARNING_MESSAGE` is generic.
- **Local-first** — runs entirely on the user's machine via Ollama;
  no cloud dependency, no API costs, no data egress.

### 10.2 Codebuff wins on:

- **Parallel delegation** — `spawn_agents` + `Promise.allSettled` is
  first-class; LocalMind has no equivalent.
- **Best-of-N editing** — `propose_*` + selector + apply is a clean
  pattern that LocalMind cannot express.
- **`handleSteps` generator** — agents are programs, not just prompts.
  Enables procedural workflows like "set_messages → spawn N → select
  → apply."
- **`spawn_agent_inline`** — child mutates parent's history. Enables
  the `context-pruner` pattern.
- **Per-agent model routing** — Opus for thinker, Flash Lite for
  basher, DeepSeek for reviewer. Sophisticated cost engineering.
- **Abort signal + steering** — clean cancellation and mid-run
  redirection. LocalMind has neither.
- **Bounded output buffers** — head+tail retention for long tool
  output. LocalMind has a hard 4000-char cap.
- **State snapshots** — 5s checkpoint for crash recovery. LocalMind
  has none.
- **Agent Store + SDK** — publishable agents, programmatic embedding.
  LocalMind is a desktop app only.

### 10.3 Both systems share:

- Multi-agent architecture with scoped toolsets per agent.
- Agent-as-directory/package organization.
- Native function calling (LocalMind) or XML-tag calling (Codebuff)
  for tool dispatch.
- Wall-clock + iteration caps on the agent loop.
- No code execution sandboxing.
- Per-step observability via events / trace writer.

The borrowing recommendations in `recommendations.md` focus on the
Codebuff-wins column, since that's where LocalMind has the most to
learn.
