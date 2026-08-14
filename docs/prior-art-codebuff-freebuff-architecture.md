# Prior Art: Codebuff / Freebuff Production Architecture

> **Status:** Verified prior art — recorded 2026-08-09 (Session 101) from the user's
> architecture thread (`/Users/bao/Desktop/Buffy - LocalMind Chat.txt`) plus web
> research done inside that thread. **Do not re-research these facts** — they are
> already captured here and referenced by ADR-14 / ADR-15 / ADR-16.
>
> Purpose: LocalMind's architectural targets (single front door, thin dispatcher,
> sub-agent contracts, per-agent model routing) are grounded in this real,
> shipped system rather than speculation. When implementing anything in the
> ADR-14/15/16 family, read this file first.

---

## 1. What Codebuff/Freebuff is

- **Codebuff** is the underlying open-source multi-agent AI coding engine. Edits
  and commands run locally; prompts, code, files, and repository context are
  sent to the model provider.
- **Freebuff** is the free, ad-supported product by the **same team**, running
  the **same** underlying multi-agent architecture — monetized via ads in the
  IDE instead of paid credits. Not a divergent product.
- LocalMind's own `.context` protocol sessions run inside this system, so the
  architecture below is LocalMind's daily working environment, not a remote
  curiosity.

## 2. The agent roster (verified)

| Agent | Role |
|---|---|
| `codebuff/base` | Main coding assistant / **orchestrator** — coordinates all other agents |
| `editor` | Code editing and file modifications |
| `reviewer` | Code review and feedback |
| `thinker` | Deep thinking and problem analysis |
| `researcher` | Web search and documentation lookup |
| `file-picker` | File discovery |
| `basher` | Terminal command execution |
| `code-searcher` | Search patterns in code files (the Greptile-style role) |

**General vs specific sub-agents** (the pattern ADR-15 adopts):

- **General sub-agent** — broad-purpose worker scoped per-call by whatever
  instruction the dispatcher passes ("read this file and summarize", "run this
  command", "search the web for X"). Covers the long tail; one build, many uses.
- **Specific sub-agent** — purpose-built for one recurring job with its own
  tuned prompt, tool access, and **fixed output schema**: e.g. basher always
  returns `{stdout, exitCode}`-shaped results; a code-review sub-agent always
  returns `{issues: [...], severity: ...}`. Narrower but more reliable and
  faster for their one job because the output shape is fixed, not inferred per
  call.
- **Routing rule:** cheap classification — "does this sub-task match one of my
  specific sub-agents, or does it fall through to the general one?" Add specific
  sub-agents **incrementally** as recurring task types appear; never enumerate
  them all up front.

## 3. Model routing per agent (verified SHIPPED, not aspirational)

- **Claude Opus 4.7** handles the Default and Plan orchestration (the heavy
  reasoning work: the orchestrator).
- **Gemini 3.1 Flash Lite** runs several sub-agent tasks (the cheap mechanical
  work).
- **MiniMax M3** is used in Lite mode.

This is the strongest prior art for LocalMind's latency work: routing the
heavy-reasoning orchestrator to a strong model while routing narrow sub-agents
to small/fast models is exactly how Codebuff gets low latency at scale.
LocalMind shipped its own realization of this as per-agent model routing
(B-2026-08-02-10, Session 85).

## 4. The orchestrator pattern (the "single front door")

- **User ↔ orchestrator (Buffy) is the ONLY external interface.** The user never
  invokes a sub-agent directly — sub-agents take orders only from the main agent
  ("It only receives orders from Buffy, not the user").
- **The orchestrator is a thin front door, not a full pipeline pass.** Its job:
  acknowledge → classify intent (cheap: structured output / function-calling,
  ideally not even a full model call when a heuristic will do) → decide the
  route → kick it off. The route is one of:
  - trivial/conversational → straight to Generate, skip everything else
  - needs a tool → Tool Select → Execute → Generate (report result)
  - needs a sub-agent → delegate, get structured JSON back, then Generate
  - needs multi-step work → hand off to the objective/agentic loop
- The orchestrator's own "thinking" is fast and cheap (structured/constrained
  output), and it only invokes the heavier stages the specific input needs —
  never every stage unconditionally for every message. Running the dispatcher
  through Context Build + Tool Select + Generate on its own account is the
  redundancy that produced ~40s latency on "Hi" in LocalMind's early pipeline.
- One documented variant goes further: an orchestrator with **zero tools except
  spawning other agents** ("perfect context management for free"). More radical
  than LocalMind needs today, since LocalMind's dispatcher also answers trivial
  conversational replies directly.

## 5. Final-output-only context (the speed mechanic)

- Spawned agents contribute **only their final output** to the orchestrator's
  context — never their full message histories or reasoning trails.
- This is why the orchestrator stays fast while coordinating many sub-agents:
  it never re-reads a sub-agent's reasoning, just its answer. The orchestrator's
  context window grows slowly regardless of how many sub-agents it spawns.
- **Consequence for LocalMind (ADR-15 §3):** keep sub-agent message histories out
  of the parent prompt; only the structured result should flow back.

## 6. Bounded instruction in, fixed structured result out

- Sub-agents receive explicit, bounded instructions: exactly what to do, what
  **not** to do, and exactly what shape to return.
- Reasoning lives in the main agent. The sub-agent executes against a spec — it
  does not reason from context. "Never 'figure out what to do' — always 'do
  exactly this, return exactly that'."
- This is why specific sub-agents pay off with **function-calling / tool-use
  output schemas**: a fixed schema per sub-agent is far easier to constrain than
  getting one general-purpose sub-agent to return consistently-shaped JSON
  across every possible task.

## 7. The three-tier tool model (refines "tool vs sub-agent")

| Tier | Behavior | Examples |
|---|---|---|
| **Raw tool** | Mechanical, no interpretation — plain function call | read a file, list a directory |
| **Tool-acting-as-subagent** | Bounded interpretation within a scope, fixed structured return | basher (terminal), Greptile / code-searcher (semantic code Q&A) |
| **Inline-only (stays with main agent)** | Needs full accumulated context + open reasoning | file **writing** — deciding what the change should be is itself the reasoning task |

**Two-factor test** (ADR-15 §5) for deciding tool-vs-subagent:

- context-heavy + reasoning-heavy → inline with the main agent's thinking block
  (file writing: the full context of the turn + reasoning over it is what makes
  an inline write trustworthy).
- context-light + execution-only → good sub-agent candidate (cheap model, no
  thinking block; basher's "run this command and tell me what happened" needs
  only the command, not Buffy's reasoning trail).

The boundary is **where the reasoning happens**, not the API classification.
Buffy does all the reasoning up front and compresses it into an unambiguous
instruction; the sub-agent's job is faithful execution with a fixed return
shape. File writing stays inline precisely because it *is* the reasoning task.

## 8. Mapping to LocalMind's ADRs and shipped work

| Prior-art fact | LocalMind realization |
|---|---|
| Single front door / thin dispatcher | **ADR-14** (Session 95, target); ADR-11 conversational fast-path shipped (Sessions 68-71) |
| Sub-agent contract, general+specific, three-tier model | **ADR-15** (Session 95, target); fixed output schema on ReviewerAgent shipped (B-15, Session 98) |
| General vs objective-loop as distinct entry points | **ADR-16** (Session 95, target) |
| Per-agent model routing | **B-2026-08-02-10** shipped (Session 85) |
| Best-of-N editor pattern | **B-2026-08-02-11** shipped (Session 86) |
| Tool-vs-subagent as a cost/reasoning question | **B-2026-08-09-16** — measurement surface built (Session 99); decision: no tool converted to sub-agent until `tool_timings` shows its own execution is the cost driver |
| Specific sub-agent output schemas | **B-2026-08-09-15** shipped (Session 98) |

## 9. Open questions for LocalMind (carry into implementation)

1. Does shell-as-inline-tool cost real latency by inheriting the main model's
   weight for mechanical execution — or is that negligible next to the
   dispatcher fix? (Answer from `tool_timings.shell.avg_ms` once a real-model
   session has been measured — B-16 follow-up.)
2. Should the dispatcher be an "orchestrator with zero tools except spawning"
   (the radical Codebuff variant) or keep direct trivial-reply capability?
   LocalMind's current direction: keep direct replies (ADR-14 fan-out #1).

## 10. Official contract verification (2026-08-14, Session 196)

The uploaded Freebuff/Codebuff research was checked against the official
Codebuff documentation and published agent definitions. The verified core
contract is:

- An agent definition owns `model`, `toolNames`, `spawnableAgents`,
  `spawnerPrompt`, `systemPrompt`, `instructionsPrompt`, optional
  `includeMessageHistory`, and an output mode/schema.
- The exact spawn payload is
  `spawn_agents({ agents: [{ agent_type, prompt?, params? }] })`.
  Multiple entries run in parallel; the child allowlist comes from
  `spawnableAgents`.
- `handleSteps` can yield deterministic tool calls, `STEP`, or `STEP_ALL`;
  `set_output` returns a structured result to the parent.
- Child history is isolated by default (`includeMessageHistory: false`), while
  specific agents opt into history. Published examples confirm specialized
  contracts: file-picker uses `find_files`, code-searcher uses `code_search` +
  `set_output`, reviewer uses only `run_file_change_hooks` + `end_turn`, and
  context-pruner uses `set_messages`.
- Freebuff's public README confirms specialized agents and isolated parallel
  Desktop workspaces, but that workspace isolation is a product-surface claim;
  it should not be confused with generic parallel child execution.

The uploaded claims about Google A2A endpoints, `/api/v1/agent-runs`,
`codebuff_metadata`, and `ancestorRunIds` were not found in the official sources
reviewed. Third-party reverse-engineering/proxy pages mention similar private
transport details, but they are not implementation requirements for LocalMind.

LocalMind already has the durable equivalents that matter: scoped directory
agents, per-agent model routing, immutable bounded delegation packets, handoff
and parallel delegation, an inline context-pruner, fixed reviewer output schema,
parent/child run IDs, and final-output-only child message histories. Remaining
follow-ups are tracked as B-2026-08-14-1 (legacy heuristic removal),
B-2026-08-14-2 (parallel workspace safety), and B-2026-08-14-3 (bounded parent
result content).

### Official references

- https://www.codebuff.com/docs/agents/overview
- https://www.codebuff.com/docs/walkthroughs/creating-your-first-agent
- https://www.codebuff.com/docs/advanced/sdk
- https://www.codebuff.com/publishers/codebuff/agents/base/0.0.18
- https://www.codebuff.com/publishers/codebuff/agents/researcher-file-explorer/0.0.3
- https://www.codebuff.com/publishers/codebuff/agents/file-picker/0.0.4
- https://www.codebuff.com/publishers/codebuff/agents/code-searcher/0.0.19
- https://www.codebuff.com/publishers/codebuff/agents/reviewer/0.0.10
- https://www.codebuff.com/publishers/codebuff/agents/context-pruner/0.0.22
- https://www.codebuff.com/publishers/codebuff/agents/editor/0.0.6
- https://www.codebuff.com/publishers/codebuff/agents/thinker-best-of-n-gpt-5/0.0.15
- https://github.com/CodebuffAI/freebuff
- https://news.codebuff.com/p/codebuff-goes-open-source-beats-claude
