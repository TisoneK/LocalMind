# LocalMind — Architecture

> **Updated:** 2026-08-20 — Parent-only scope amendment (ADR-53)
>
> **Long-term direction:** see [`VISION_ARCHITECTURE.md`](VISION_ARCHITECTURE.md)
> (ADR-56) — LocalMind as an agent runtime + intelligence harness
> ("Model Intelligence + Harness = Agent"). Direction only; ADR-53 governs
> current scope.

> **Naming:** the agent is **LocalMind**; "parent agent" / "Parent Agent" is its
> architectural *role* (the root agent), not its name — the code says so directly
> (`agents/parent/context_builder.py`: "You are the user-facing LocalMind agent").
>
> **Architecture status (decided 2026-08-20, ADR-53):** LocalMind is
> **Parent-only right now**. The Parent is the sole active agent and owns the
> kernel, session, turn context, tools, planning, execution, observation,
> verification, recovery, and final synthesis. Child agents, specialist agents,
> delegation, parallel delegation, and inheritance are not part of the current
> architecture. Existing multi-agent code remains parked compatibility residue;
> it is not an active routing or extension target. ADR-8 and ADR-48 remain
> historical records and are superseded by ADR-53 for current scope.

## Core model

LocalMind is a local-first agent system. The API and CLI are transport surfaces;
the **LocalMind parent agent** owns the user objective and runs the closed loop:

```text
surface → API/SSE → AgentRuntime → ParentAgent → AgentLoop
                                      │
                                      ├─ all Parent-owned tools
                                      ├─ observe evidence
                                      ├─ evaluate acceptance criteria
                                      ├─ replan when evidence is incomplete
                                      └─ synthesize the final answer
```

There is no request-time `ThinkingDispatcher`, execution graph, direct-tool
shortcut, or legacy `_pipeline.py`. Tools are actions available to the parent,
not routing destinations selected before the agent reasons.

## Request lifecycle

`core.agent_runtime.AgentRuntime` is the single request boundary. It owns only
transport/lifecycle concerns:

1. Run the safety gate.
2. Load history and persist the user message.
3. Assemble memory, attachments, session CWD, and the parent context.
4. Start one `ParentAgent` with the full parent tool contract.
5. Thread the session's abort event, steering queue, observation collector, and
   adapter into the same `AgentLoop` instance.
6. Persist the final response and publish metrics, stage timings, failures, and
   observations.

The runtime does **not** classify the request or execute a domain-specific tool
branch. `client_intent` is recorded only as an ignored UI hint; the parent owns
tool selection.

## Parent-only runtime

`agents/parent/` is LocalMind's sole active agent and user-facing identity. It
owns the complete tool allowlist, session context, acceptance gate, execution
loop, recovery, and final answer. The `ParentKernel` is boot-owned operating
context for this one Parent; it is not a factory for other agents or an
inheritance mechanism.

Other agent directories, registry entries, and delegation tools may remain in
the repository for compatibility, but they are parked and out of the current
architecture. The Parent must not route work to them or extend them. Future
child/specialist work requires a separate explicit user decision after the
Parent maturity bar is proven.

## Parent loop contract

`BaseAgent.run()` wires an agent's context builder, scoped `AgentConfig`,
acceptance hook, abort signal, steering queue, and delegation context into
`core.agent.loop.AgentLoop`. The loop performs:

```text
plan → native tool call → execute → observe → evaluate →
  (replan if needed) → native tool call ... → verified final answer
```

Hard iteration and wall-clock limits remain safety bounds. Empty streams always
produce a meaningful fallback; when the trace reaches its cap the answer says
**iteration limit reached** and suggests continuing. The acceptance gate never
passes solely because the model says “done”; it requires current-run evidence.

## Tools

Tools are registered in `tools/` and exposed as native function definitions by
the parent loop. The parent has the complete allowlist, including:

- web search and fetch
- browser automation
- shell, code execution, process management, and structured git
- file read/write/edit and deterministic parsers (CSV, JSON, SQL)
- memory, system observation, calculator, diagnostics
- plans, subgoals, skills, and edit proposals

Delegation-related implementations remain parked compatibility code and are
not exposed as the current Parent architecture.

Write-capable tools retain the universal **check before acting** safety rule.
The tool result is appended to the parent loop's internal context; it is not
returned as a final user answer until the parent evaluates and synthesizes it.

## Lifecycle services

The runtime extracts non-routing concerns from the removed pipeline:

- `core.context_builder` — bounded prompt/history/attachment assembly
- `core.safety_gate` — input safety screening
- `core.engine.stage_clock` — truthful stage timing events
- `core.observation` — immutable workspace/event snapshots
- `core.metrics` — latency and token metrics
- `core.memory` and `core.failure_memory` — facts and what-failed memory
- `core.engine._persistence_mixin` — message persistence helpers
- `core.engine._reflection_mixin` — post-response quality reflection
- `core.session_context` — per-session working directory

These services do not make routing decisions. The removed dispatcher and graph
modules may remain available as isolated data-model utilities during cleanup,
but they are not imported by the request runtime.

## Surfaces and adapters

FastAPI streams `StreamChunk` and structured observation events through SSE.
The CLI calls the same `Engine` compatibility export, which is now an alias for
`AgentRuntime`. The frontend never needs to know whether a tool was executed by
the Parent; it receives the Parent's tagged progress and synthesized answer.
Parked child/delegation code is not part of the active request lifecycle.

Adapters implement the model boundary (`chat`, `chat_with_tools`, and streaming
usage normalization). The runtime resolves the configured adapter once per turn
and passes it to the parent loop. No provider-specific routing logic belongs in
the API or runtime.

## Directory map

```text
backend/src/
├── agents/
│   ├── parent/                 LocalMind user-facing parent agent
│   ├── coding/ research/ browser/ direct/  (parked compatibility)
│   ├── verifier/ reviewer/ debugger/ analyst/ (parked compatibility)
│   ├── base_agent.py           shared loop wiring
│   └── registry.py             legacy directory registry
├── core/
│   ├── agent_runtime.py        sole request execution boundary
│   ├── agent/loop.py           plan/act/observe/evaluate loop
│   ├── agent/delegation.py     parked compatibility contracts
│   ├── context_builder.py      bounded context assembly
│   ├── safety_gate.py          safety checks
│   ├── observation.py          workspace/runtime snapshots
│   ├── memory.py               semantic memory
│   └── engine/                 lifecycle service modules only
├── tools/                      native Parent tool implementations
├── adapters/                   Ollama/OpenAI-compatible model adapters
├── api/                        FastAPI routes and SSE bridge
└── storage/                    SQLite history and vector persistence
```

## Extension rules

1. Add a tool as a registered native function; do not add a route-time tool
   branch.
2. Keep all active behavior in the Parent; do not add or route through child
   agents, specialist agents, delegation, parallel delegation, or inheritance.
3. Grow Parent-owned session memory, execution structure, verification,
   recovery, and escalation before reconsidering any child boundary.
4. Treat existing child/delegation modules as parked compatibility code unless
   the user explicitly reopens that scope.
5. Verify every new loop path with tests for evidence evaluation, silent
   fallback, abort/steer threading, and SSE visibility.
