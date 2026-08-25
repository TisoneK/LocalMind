# LocalMind — Future Vision Architecture

> **Status:** direction document (not a release plan). Recorded 2026-08-25
> from the owner's vision statement. **It does not change the current
> scope** — ADR-53 (Parent-only) governs what is built *now*; this document
> describes the long arc those increments serve. Where the vision shows
> specialist agents, they sit behind explicit maturity gates (§8) and are
> NOT permission to start multi-agent work early.

---

## 1. The core equation

```text
Model Intelligence + Harness = Agent
```

LocalMind is **not** "a local chatbot powered by Ollama." That framing is
too narrow. The long-term identity:

> **LocalMind is an agent runtime and intelligence harness that turns one
> or more AI models into persistent, context-aware, tool-using agents.**

```text
                    ┌───────────────┐
                    │     AGENT     │
                    └───────────────┘
                           ▲
              ┌────────────┴────────────┐
              │                         │
     ┌────────▼─────────┐    ┌─────────▼─────────┐
     │ MODEL            │    │ HARNESS           │
     │ INTELLIGENCE     │ +  │                   │
     │                  │    │ • Tools           │
     │ • Reasoning      │    │ • Memory          │
     │ • Understanding  │    │ • Context Engine  │
     │ • Planning       │    │ • Sandbox         │
     │ • Generation     │    │ • Orchestration   │
     └──────────────────┘    │ • Serving Layer   │
                             └───────────────────┘
```

The model supplies reasoning and decision-making. The harness supplies
tools, state, execution, orchestration, and constraints. The single most
important architectural principle:

> **THE MODEL IS NOT LOCALMIND. THE MODEL IS THE INTELLIGENCE.
> LOCALMIND IS THE SYSTEM THAT GIVES THAT INTELLIGENCE MEMORY, CONTEXT,
> CAPABILITIES, EXECUTION, AND CONTINUITY.**

This is the identity shift the product is riding:

```text
LOCALMIND TODAY    →  AI application
LOCALMIND NEXT     →  Single intelligent agent
LOCALMIND FUTURE   →  Agent runtime + intelligence harness
LOCALMIND LONG TERM→  Platform that hosts, coordinates, and evolves
                      multiple intelligent agents
```

---

## 2. The long-term architecture

```text
╔══════════════════════════════════════════════════════╗
║                    USER / CLIENTS                    ║
║   Web UI  •  Desktop  •  CLI  •  API  •  Integrations║
╚═════════════════════╤════════════════════════════════╝
                      ▼
╔══════════════════════════════════════════════════════╗
║                   SERVING LAYER                      ║
║        Sessions • Streaming • API • Identity         ║
╚═════════════════════╤════════════════════════════════╝
                      ▼
╔══════════════════════════════════════════════════════╗
║                  AGENT RUNTIME                       ║
║  Understand → Reason → Plan → Act → Observe → Respond║
╚═════════════════════╤════════════════════════════════╝
                      ▼
        ┌───────────────┼────────────────┐
        ▼               ▼                ▼
╔════════════════╗ ╔════════════════╗ ╔════════════════╗
║ Context Engine ║ ║ Memory System  ║ ║ Orchestration  ║
╚════════════════╝ ╚════════════════╝ ╚════════════════╝
        └───────────────┼────────────────┘
                        ▼
╔══════════════════════════════════════════════════════╗
║                 CAPABILITY LAYER                     ║
║    Files • Web • Code • APIs • System • Specialists  ║
╚═════════════════════╤════════════════════════════════╝
                        ▼
╔══════════════════════════════════════════════════════╗
║                    SANDBOX                           ║
║       Controlled Execution • Isolation • State       ║
╚═════════════════════╤════════════════════════════════╝
                        ▼
╔══════════════════════════════════════════════════════╗
║                MODEL INTELLIGENCE                     ║
║   Local Models • Remote Models • Specialized Models  ║
╚══════════════════════════════════════════════════════╝
```

Each layer below is described three ways: **the vision** (what it becomes),
**today** (what already exists in this repo — the honest starting point),
and **the gap** (what the next increments are). The mapping matters: the
vision is not a rewrite, it is a continuation of structure that already
exists.

---

## 3. Layer: Model Intelligence

**Vision.** The model is a *replaceable intelligence component*. The
architecture stays stable while the provider evolves:

```text
Today:    Ollama model
Tomorrow: local model • remote Ollama • OpenAI • Anthropic
          • custom model • specialized model
```

The model owns the cognitive work — understanding the request, reasoning,
planning, deciding when a tool is necessary, interpreting tool results,
synthesizing the answer. It does **not** own the system around it.

**Today.** This layer is the most mature. `backend/src/adapters/` already
abstracts Ollama + ~20 OpenAI-compatible providers behind one interface;
`core/model_router.py` routes task types to models; provider quirks
(thinking params, context windows, error envelopes) live in the adapter
layer, not in the agent. Switching providers is a settings change.

**Gap.** Model *capability tiers* are implicit. The future work is making
the runtime's expectations explicit (minimum tool-calling fidelity,
context window floor, thinking support) so a weak model degrades
gracefully instead of mysteriously — and letting specialized models serve
narrow roles (e.g. a cheap embedder, a fast title generator) under the
same contract.

---

## 4. Layer: The Harness (LocalMind's real product)

The harness is everything that makes the intelligence useful. Its
subsystems:

### 4.1 Tools (capability layer)

**Vision.** The agent acts, not just talks:

```text
User: "Find the project configuration and tell me why the server
       isn't starting."

Agent ├── Search files        ├── Read configuration
      ├── Inspect logs        ├── Run diagnostic
      └── Explain result
```

The model decides *what* needs to happen; the tool layer provides the
*ability* to do it.

**Today.** 35 registered tools (`backend/src/tools/`) behind one registry:
file ops, shell, git, system search (files/recent/largest/duplicates/
apps/open_with), web research, browser, code exec, sqlite/csv/json,
sysinfo, memory ops, todos. Bounded-by-construction outputs and the
security gate (allowed-folders, symlink policy) are the standing
discipline.

**Gap.** Capability depth per domain (content-aware search, richer code
intelligence), and uniform tool contracts — every tool must stay bounded,
honest about partial results, and security-gated as the set grows.

### 4.2 Memory

**Vision.** LocalMind becomes *continuous* instead of stateless:

```text
Past Work → Memory System → Current Context → Agent
             ├── User preferences
             ├── Project knowledge
             ├── Previous decisions
             ├── Important facts
             └── Learned patterns
```

The critical distinction: **conversation is not memory.** Conversation
history is raw chronology; memory is *selected, structured, relevant
knowledge* that survives across runs.

**Today.** The seed exists: `storage/vector.py` (sqlite-vec fact store,
memory-intent interception — "remember that my sister's birthday is
October 12th" lands in `vector_facts` without a model call), per-session
rolling summaries (`parent_sessions`), episode memory, and failure memory
(recurrent-trap log). Memory retrieval feeds the context builder per
turn.

**Gap.** Memory *selection* and *structure*: what gets promoted from
chronology to memory, what decays, what is project-scoped vs
user-scoped, and retrieval that ranks by relevance instead of recency.

### 4.3 Context Engine (the differentiator)

**Vision.** The future challenge is not *"how do we give the model more
context?"* — it is *"how do we give the model the right context at the
right time?"*

```text
AVAILABLE CONTEXT                    RELEVANT CONTEXT
 Project files        ─┐
 Previous sessions    ─┤             ┌──────────────┐
 User memory          ─┼── Selection ─┼──▶ MODEL
 Current conversation ─┤             └──────────────┘
 Tool results         ─┤
 System instructions  ─┤
 Agent state         ─┘
```

**The `.context` direction becomes the context substrate.** Today
`.context/` is the *development* protocol for agents working on this
repo (rules, memory, decisions, sessions — exactly the
system/rules/conventions + memory/decisions/sessions + project/spec +
agent/capabilities/policies shape). The long-term move: the same
structure becomes part of the *product* — LocalMind retrieves what is
relevant to the current task from a structured context store instead of
blindly dumping everything into the prompt.

**Today.** `core/context_policy.py`, `context_builder.py`, and
`context_compactor.py` already make per-turn assembly selective
(task-type-aware retrieval, decision preservation on compaction); the
lean tool schemas (ADR-40) proved that *curating* context beats adding
it. The dev `.context/` protocol itself is the working prototype of the
concept.

**Gap.** Unified context substrate: one selection policy over all
sources (files, sessions, memory, tool evidence, agent state) with
relevance ranking, budgeted per turn — the product-side evolution of
what `.context/` already does for development.

### 4.4 Sandbox

**Vision.** The agent can safely *do* work:

```text
Agent decides "I need to inspect this project"
  → sandbox created → files available
  → read / search / analyze / execute permitted ops / generate artifacts
  → results returned to agent
```

This changes LocalMind from a conversational system ("here is how you
could fix it") into a working system ("I inspected the project; here is
what is wrong").

**Today.** Per-session workspaces (`core/session_workspace.py`) scope
agent writes to the session folder; the code executor has a sandbox
mode; shell is timeout-bounded with guards (broad-search redirect,
check-before-acting safety workflow); the allowed-folders policy bounds
all file access.

**Gap.** True isolation — resource limits, snapshot/rollback per turn,
and artifact lifecycle (what survives the session, what the user can
inspect and replay).

### 4.5 Orchestration

**Vision.** The brain around the brain — the execution lifecycle:

```text
USER REQUEST → Understand → Need action? ──No──▶ Respond
                    │Yes
                    ▼
              Plan / Route → Select tool → Execute → Evaluate
                    ▲                                  │
                    └── More work needed ◀─────────────┤
                                                       ▼
                                                 Complete → Respond
```

**Today.** This is the parent agent loop, exactly: goal-derived
checklists, the acceptance gate, evidence-based completion, recovery and
honest-stop paths. ADR-53 deliberately keeps ONE agent owning this loop.

**Gap.** The loop's *maturity*: planning quality, verification depth,
and recovery breadth on the single Parent — the prerequisites for ever
adding specialists (§8).

### 4.6 Serving Layer

**Vision.** The runtime is independent of the interfaces that consume
it:

```text
LOCALMIND CORE → Web UI • CLI • API → External Systems
```

The agent does not belong to the React interface; the React interface is
one client of the intelligence system. Later: Desktop, CLI, API, Web,
IDE integration, and *other applications using LocalMind as an
intelligence backend*.

**Today.** Already separated: `backend/src/api/` (FastAPI + SSE) and
`backend/src/cli/` (ask/chat/sessions/models) are transport surfaces
over the same `AgentRuntime`; the Electron desktop shell wraps the web
UI.

**Gap.** Identity/auth for API consumers, multi-client session sync, and
a stable public contract for the "LocalMind as backend" case.

---

## 5. The runtime identity

At the center of the stack is the loop the harness exists to serve:

```text
        ┌──────────────────────────────────┐
        │          AGENT RUNTIME           │
User ──▶│  Understand → Plan → Act →       │──▶ Response
        │               Observe → Adapt    │
        └──────────────────────────────────┘
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
        MODEL         MEMORY         TOOLS
     Intelligence     Context       Capabilities
```

Understanding, planning, acting, observing, adapting — the current
`AgentLoop` is this diagram in code. Every harness subsystem exists to
make one of those verbs better.

---

## 6. Guiding principles

1. **The model is not LocalMind** — providers are replaceable
   intelligence; the harness is the product.
2. **Conversation is not memory** — promote selected, structured
   knowledge; do not replay chronology.
3. **Right context, not more context** — selection and ranking beat
   bigger prompts; every token sent is a cost and a distraction.
4. **Bounded by construction** — outputs, walks, and execution all carry
   budgets and honest partial-scan flags; no silent truncation.
5. **Evidence over narration** — the trace is the truth; the model's
   claims are checked against tool results.
6. **One mature agent before many** — deepen the Parent's loop before
   ever fanning out (the progression in §8).

---

## 7. What this vision does NOT authorize

Recorded so no future session misreads this document:

- It does **not** reopen ADR-53. Parent-only is the *current* scope;
  specialists appear in this document only as the *mature* end state.
- It does not justify rewriting working subsystems to "match the
  diagram" — the diagram describes the arc the current structure is
  already on (§2's mapping is deliberately "what exists today").
- It does not add scope to any backlog item; it is the reference when a
  design choice asks *which direction*.

---

## 8. Progression and maturity gates

```text
STAGE 1 (now)      Single Parent agent, deepening the loop:
                    memory quality, context selection, verification,
                    recovery, sandbox, serving hardening.

STAGE 2            Parent mature → bounded specialist capabilities
                    as TOOLS under the Parent's control (not peers).

STAGE 3            Agent runtime hosting multiple agents where the
                    Parent remains the manager — specialists are
                    called, scoped, and evaluated by the Parent.

STAGE 4            Platform: LocalMind as an intelligence backend for
                    other clients and applications.
```

The gate between each stage is **observed Parent maturity on real
workloads** (field live-testing evidence, not aspiration): planning
quality, verification depth, recovery breadth, and honest-stop
behavior. A stage is entered by an ADR that cites that evidence — the
same standard ADR-53 used to *stop* premature multi-agent work applies
to *starting* it.
