# LocalMind — Architecture

> **Updated:** 2026-08-14 — parent-agent runtime migration

> **Naming:** the agent is **LocalMind**; "parent agent" / "Parent Agent" is its
> architectural *role* (the root agent), not its name — the code says so directly
> (`agents/parent/context_builder.py`: "You are the user-facing LocalMind agent").
>
> **Architecture status (decided 2026-08-18, ADR-48):** LocalMind has accepted it
> is **past** the single-agent-first phase — the multi-agent runtime below
> (`delegate / delegate_parallel → child agents`, 11 specialists) is **first-class
> and endorsed**, not dormant. The Parent Agent spec
> [`docs/parent-agent-spec.md`](parent-agent-spec.md) is retained as the standing
> **quality bar** (§40 / §43), not a build roadmap. Remaining agent work is
> measured against §40 (open hardening: efficiency, tool-selection, recovery,
> grounding — see the backlog), not against "is it still single-agent."

## Core model

LocalMind is a local-first agent system. The API and CLI are transport surfaces;
the **LocalMind parent agent** owns the user objective and runs the closed loop:

```text
surface → API/SSE → AgentRuntime → ParentAgent → AgentLoop
                                      │
                                      ├─ scoped tools
                                      ├─ delegate / delegate_parallel
                                      │       → isolated specialized child agents
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

## Parent and child agents

`agents/parent/` is LocalMind's user-facing coordinator. It is not a copy of
another product. It provides the parent persona, complete tool allowlist, and
acceptance-gate stop condition.

Specialized agents remain directories discovered by `agents/registry.py`:

| Agent | Role | Typical scoped tools |
|---|---|---|
| Coding | Build, edit, test, and inspect code | shell, file, code, git, process |
| Research | Gather and compare external evidence | web search/fetch |
| Browser | Interact with browser sessions | browse |
| Verifier | Reproduce and verify outcomes | shell, tests, git |
| Reviewer | Read-only quality review | file, git, shell |
| Debugger | Isolate root causes | file, git, shell, diagnostics |
| Analyst | Clarify requirements and plans | read-only analysis |
| Direct | Child-only single model call | none |

A child starts with its own system prompt and the exact self-contained task
passed by the parent. It does not inherit the user's conversation implicitly.
Child reports return as internal tool results to the parent. Child progress can
be observed, but raw child tool output is filtered at the SSE boundary.

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
- delegation and parallel delegation
- plans, subgoals, skills, edit proposals, and best-of-N edits

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
the parent or a delegated child; it receives tagged progress and the parent's
synthesized answer.

Adapters implement the model boundary (`chat`, `chat_with_tools`, and streaming
usage normalization). The runtime resolves the configured adapter once per turn
and passes it to the parent loop. No provider-specific routing logic belongs in
the API or runtime.

## Directory map

```text
backend/src/
├── agents/
│   ├── parent/                 LocalMind user-facing parent agent
│   ├── coding/ research/ browser/ direct/
│   ├── verifier/ reviewer/ debugger/ analyst/
│   ├── base_agent.py           shared loop wiring
│   └── registry.py             directory discovery
├── core/
│   ├── agent_runtime.py        sole request execution boundary
│   ├── agent/loop.py           plan/act/observe/evaluate loop
│   ├── agent/delegation.py     isolated parent/child contracts
│   ├── context_builder.py      bounded context assembly
│   ├── safety_gate.py          safety checks
│   ├── observation.py          workspace/runtime snapshots
│   ├── memory.py               semantic memory
│   └── engine/                 lifecycle service modules only
├── tools/                      native parent/child tool implementations
├── adapters/                   Ollama/OpenAI-compatible model adapters
├── api/                        FastAPI routes and SSE bridge
└── storage/                    SQLite history and vector persistence
```

## Extension rules

1. Add a tool as a registered native function; do not add a route-time tool
   branch.
2. Add a specialized agent as a directory with `agent.py`, context, stop
   condition, scoped tools, and playbook/persona when appropriate.
3. Make the parent delegate a bounded, self-contained task when another domain
   is needed; pass exact scope, constraints, and output contract.
4. Keep child output internal and preserve only tagged progress at presentation
   boundaries.
5. Verify every new loop path with tests for evidence evaluation, silent
   fallback, abort/steer threading, and SSE visibility.
