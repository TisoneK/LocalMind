# Codebuff — Deep Technical Research Report

> Repository researched: `https://github.com/CodebuffAI/open-codebuff`
> (public mirror of the private Codebuff/Freebuff source tree; cloned to `/home/z/my-project/repos/open-codebuff`)
> Scope: produce a deep, file-and-code-cited profile of Codebuff's agentic architecture so it can be compared against LocalMind.

---

## 1. Overview

Codebuff is an **open-source, multi-agent, model-agnostic coding assistant**. Its public pitch (see `README.zh-CN.md:5-13`) is that — unlike single-model tools such as Claude Code — it **orchestrates multiple specialized agents** (file picker, planner, editor, reviewer) that collaborate to understand a project and make precise code changes. On their own `BuffBench` evaluation (see `evals/buffbench/README.md`), Codebuff reportedly beats Claude Code 61% vs 53% on 175+ real-world coding tasks across open-source repos.

The product ships in three forms, all built from this one repo:

1. **Codebuff CLI** (`cli/`, distributed as the `codebuff` npm package): an interactive terminal app built with React + Ink. `npm install -g codebuff`, then `cd your-project && codebuff`.
2. **`@codebuff/sdk`** (`sdk/`): a programmatic client (`CodebuffClient.run({...})`) for embedding agents into CI, scripts, or other products. See `sdk/README.md:1-53`.
3. **Freebuff** (`freebuff/`, distributed as the `freebuff` npm package): an ad-supported, zero-config free variant that uses cheaper models (MiniMax M3, DeepSeek, GLM, MiMo, etc.) and is gated to free-tier-only sub-agents.

The repo is organized as a monorepo (Bun-managed, see `packages/agent-runtime/package.json:25-27`):

- `packages/agent-runtime/` — the core agent loop, tool dispatch, XML stream parser, prompt assembly.
- `packages/code-map/` — tree-sitter based codebase indexer for `read_subtree`.
- `packages/llm-providers/` — OpenAI-compatible provider implementation (used to talk to the Codebuff backend that fronts OpenRouter).
- `common/` — shared types, tool schemas, constants, Zod validation.
- `agents/` — the built-in agent definitions (the "store" agents): `base2`, `editor`, `thinker`, `reviewer`, `basher`, `file-picker`, `librarian`, `browser-use`, etc.
- `sdk/` — the host SDK that wires `agent-runtime` to the filesystem, child_process, MCP, and the Codebuff web API.
- `cli/` — the React/Ink TUI.
- `evals/buffbench/` — a polyglot benchmark harness (`runners/codebuff.ts`, `runners/claude.ts`, `runners/codex.ts`, `runners/opencode.ts`) with a judge model.

Key value props, summarized from `README.zh-CN.md:166-175`: (a) custom TypeScript workflows mixing LLM calls with programmatic control via generators, (b) **OpenRouter model freedom** (any model, no vendor lock-in), (c) an Agent Store where published agents are reused like "next-gen MCP servers", and (d) a full SDK for embedding.

---

## 2. Architecture Diagram

```
                       ┌──────────────────────────────────────────┐
                       │              Host process                 │
                       │                                          │
   user prompt  ──────►│  CodebuffClient (sdk/src/client.ts)      │
   (CLI / SDK)         │   └─ run()  (sdk/src/run.ts:263)         │
                       │       │                                  │
                       │       ▼                                  │
                       │  initialSessionState()                  │
                       │   loads:                                 │
                       │     • .agents/*.ts  (local agents)       │
                       │     • .agents/skills/*/SKILL.md          │
                       │     • knowledge.md / AGENTS.md           │
                       │     • projectFiles + tree-sitter map     │
                       │       │                                  │
                       │       ▼                                  │
                       │  callMainPrompt()                        │
                       │  (agent-runtime/src/main-prompt.ts:167)  │
                       │       │                                  │
                       │       ▼                                  │
                       │  assembleLocalAgentTemplates             │
                       │  (templates/agent-registry.ts:93)        │
                       │       │                                  │
                       │       ▼                                  │
                       │  loopAgentSteps()                        │
                       │  (run-agent-step.ts:667)                 │
                       │       │                                  │
                       │       ▼  per step:                        │
                       │  ┌────────────────────────────────────┐  │
                       │  │ 1. runProgrammaticStep             │  │
                       │  │    (handleSteps generator)         │  │
                       │  │ 2. runAgentStep                    │  │
                       │  │    • build messages + tools        │  │
                       │  │    • promptAiSdkStream             │  │
                       │  │      → /api/v1/chat/completions    │  │
                       │  │        (Codebuff backend)          │  │
                       │  │        → OpenRouter                 │  │
                       │  │    • processStream (XML parser)     │  │
                       │  │    • executeToolCall                │  │
                       │  │      └─ may spawn subagents ────────┼──┼─┐
                       │  │ 3. addAgentStep (ledger)            │  │ │
                       │  │ 4. check shouldEndTurn              │  │ │
                       │  └────────────────────────────────────┘  │ │
                       │       │                                  │ │
                       │       └─ finishAgentRun                  │ │
                       └──────────────────────────────────────────┘ │
                                                                       │
                       ┌──────────────────────────────────────────┐ │
                       │       Child agent (recursive)            │◄┘
                       │                                          │
                       │  spawn_agents tool handler               │
                       │  (spawn-agents.ts:34)                    │
                       │   • Promise.allSettled(agents.map(...))  │ ← parallel fan-out
                       │   • executeSubagent → loopAgentSteps     │ ← recursive entry
                       │     (spawn-agent-utils.ts:369)           │
                       │   • result.output → JSON tool result     │
                       │     back to parent's message history     │
                       └──────────────────────────────────────────┘
```

The whole system is **in-process** (no subprocess per agent). Spawning a child agent is a recursive call to `loopAgentSteps` on a fresh `AgentState` whose `parentId` is the parent's `agentId` and whose `ancestorRunIds` carry the run-chain for telemetry.

---

## 3. Agent System

### 3.1 Agent Definition Contract

Every agent — built-in or user-defined — conforms to the `AgentDefinition` interface at `agents/types/agent-definition.ts:21-269`. The shape is:

```ts
export interface AgentDefinition {
  id: string
  publisher?: string
  version?: string
  displayName: string
  model: ModelName                              // any OpenRouter model
  providerOptions?: OpenRouterProviderRoutingOptions
  reasoningOptions?: { enabled?: boolean; exclude?: boolean } & ({ max_tokens: number } | { effort: 'high'|'medium'|'low'|'minimal'|'none' })
  mcpServers?: Record<string, MCPConfig>
  toolNames?: (ToolName | string)[]
  spawnableAgents?: string[]                    // 'publisher/agent@version' or local id
  inputSchema?: { prompt?: ...; params?: JsonObjectSchema }
  outputMode?: 'last_message' | 'all_messages' | 'structured_output'
  outputSchema?: JsonObjectSchema
  spawnerPrompt?: string                        // when/why to spawn
  includeMessageHistory?: boolean               // default false
  inheritParentSystemPrompt?: boolean           // for prompt caching
  systemPrompt?: string
  instructionsPrompt?: string                   // the main lever for behavior
  stepPrompt?: string                           // injected every step
  handleSteps?: (ctx) => Generator<ToolCall | 'STEP' | 'STEP_ALL' | StepText | GenerateN, void, ...>
}
```

Notable fields:
- `inheritParentSystemPrompt` (`agent-definition.ts:184-190`): lets a subagent **share the parent's system prompt** for Anthropic prompt-cache hits.
- `includeMessageHistory` (`agent-definition.ts:177-182`): when true, the child receives a *copy* of the parent's transcript up to the spawn call (the spawn call itself is sliced out — see `spawn-agent-utils.ts:268-307`).
- `handleSteps` (`agent-definition.ts:211-268`): a **TypeScript generator** the agent author writes to programmatically orchestrate tool calls. The generator can yield `{ toolName, input }` tool calls, `'STEP'` (one LLM round), `'STEP_ALL'` (LLM rounds until end-turn), `{ type: 'STEP_TEXT', text }` (synthetic assistant text), or `{ type: 'GENERATE_N', n }` (n parallel completions). It receives `{ agentState, prompt, params, model, logger }` and gets back `{ toolResult, stepsComplete, nResponses }`. Crucially the generator is **serialized via `.toString()` and `eval`'d at runtime** (`run-programmatic-step.ts:38-41`, `sdk/src/agents/load-agents.ts:254-262`), so closures over outer scope don't survive — values must be baked into the function body.

### 3.2 The Built-in Agent Registry

Built-in agents live in `agents/` and are published under the `codebuff` publisher (`agents/constants.ts`). Each is a default-exported `AgentDefinition`. The roster (with persona names from `common/src/constants/agents.ts:4-55`):

| Agent ID | Display name | File | Model | Role |
|---|---|---|---|---|
| `base2` (default), `base2-lite`, `base2-max`, `base2-fast`, `base2-free` and ~15 free variants | Buffy the Orchestrator | `agents/base2/*.ts` | Opus / MiniMax M3 / GLM / etc. | Top-level orchestrator |
| `editor`, `editor-gpt-5`, `editor-multi-prompt`, `editor-implementor-*` | Code Editor / Multi-Prompt Editor | `agents/editor/*.ts` | Opus / GPT-5 / GLM / Kimi / DeepSeek / MiniMax | Apply code changes |
| `thinker`, `thinker-gpt`, `thinker-gemini`, `thinker-best-of-n`, `thinker-best-of-n-opus` | Theo the Theorizer | `agents/thinker/*.ts` | Opus / GPT-5 / Gemini | Deep reasoning with no tools |
| `code-reviewer`, `code-reviewer-opus`, `-gpt`, `-glm`, `-deepseek`, `-lite`, `-multi-prompt`, etc. | Nit Pick Nick | `agents/reviewer/*.ts` | many | Reviews file changes |
| `basher` | Basher | `agents/basher.ts` | Gemini 3.5 Flash Lite | Runs a single terminal command |
| `file-picker`, `file-picker-max`, `file-lister`, `file-lister-max`, `code-searcher`, `directory-lister` | Fletcher / Dora | `agents/file-explorer/*.ts` | Gemini Flash Lite | Find relevant files |
| `researcher-web`, `researcher-docs` | Reid Searcher | `agents/researcher/*.ts` | various | Web/docs research |
| `librarian` | Librarian | `agents/librarian/librarian.ts` | MiniMax M3 | Shallow-clones a repo to /tmp and answers questions |
| `browser-use` | Browser Use Agent | `agents/browser-use/browser-use.ts` | Gemini Flash Lite | Chrome DevTools automation |
| `tmux-cli` | tmux cli | `agents/tmux-cli.ts` | — | tmux session tooling |
| `context-pruner` | Context Pruner | `agents/context-pruner.ts` | Claude Sonnet 4.6 | Runs between steps to compact history |
| `agent-builder` | Bob the Agent Builder | (referenced) | — | Generates new agent templates |
| `opus-agent`, `gpt-5-agent`, `general-agent` | General purpose | `agents/general-agent/*.ts` | Opus / GPT-5 | Last-resort complex problem solvers |

There is **no static central registry object**; agents are looked up dynamically by ID. The lookup function `getAgentTemplate` (`packages/agent-runtime/src/templates/agent-registry.ts:21-88`) has a clear three-tier priority:

1. `localAgentTemplates[agentId]` — dynamic agents from the user's `.agents/` directory + built-in templates bundled into the SDK.
2. `databaseAgentCache[agentId]` — an LRU `BoundedAgentCache` (200 entries, `sdk/src/impl/agent-runtime.ts:29-47`).
3. `fetchAgentFromDatabase(...)` — a web-API call to the Codebuff agent store for `publisher/agent@version` IDs.

Custom agents are loaded from `.agents/` (cwd, parent, home — `sdk/src/agents/load-agents.ts:149-154`). Files can be `.ts/.tsx/.js/.mjs/.cjs`; TypeScript is loaded natively by Bun.

### 3.3 Skills

Distinct from agents, **skills** are Markdown instruction files (`.agents/skills/<name>/SKILL.md` with YAML frontmatter, parsed by `sdk/src/skills/load-skills.ts:47-80` via `gray-matter`). They are loaded into `fileContext.skills` and surfaced via the `skill` tool. The system prompt advertises them: `npx skills find <query>` / `npx skills add <owner/repo> --skill <name> --yes`. Skills are like a lighter-weight version of agents — pure prompt injection, no model/tool bindings.

---

## 4. Tools

### 4.1 Tool Contract

Every tool is defined in `common/src/tools/params/tool/<name>.ts` as a Zod-validated `$ToolParams` object with `{ description, inputSchema, outputSchema, toolName, endsAgentStep }`. The full registry is built in `common/src/tools/list.ts:46-86` (`toolParams` object) — note this is a flat `Record<ToolName, $ToolParams>`, not a class hierarchy.

The tool **names** are declared in `common/src/tools/constants.ts:26-64` as a const array. There are 35 of them (plus Composio meta-tools):

```
add_message, add_subgoal, apply_patch, ask_user, browser_logs,
code_search, cloud_plan_ready, create_plan, end_turn, find_files,
glob, gravity_index, list_directory, lookup_agent_info,
propose_str_replace, propose_write_file, read_docs, read_files,
read_subtree, read_url, render_ui, run_file_change_hooks,
run_terminal_command, set_messages, set_output, skill,
spawn_agents, spawn_agent_inline, str_replace, suggest_followups,
task_completed, think_deeply, update_subgoal, web_search,
write_file, write_todos
```

`TOOLS_WHICH_WONT_FORCE_NEXT_STEP` (`common/src/tools/constants.ts:12-23`) lists tools whose presence in a response does *not* force another loop iteration: `think_deeply, set_output, set_messages, add_message, update_subgoal, create_plan, render_ui, suggest_followups, suggest_prompts, task_completed`. These are essentially side-effect-free annotations.

### 4.2 Tool Calling Protocol — XML, not native function-calling

This is one of the most distinctive Codebuff design choices. **Codebuff does not use the providers' native tool-call API.** Instead, it injects a pseudo-tool specification into the system prompt and parses tool calls out of the model's streamed text response as XML.

The format is documented in `packages/agent-runtime/src/tools/prompts.ts:172-215`:

```
<codebuff_tool_call>
{
  "cb_tool_name": "tool_name",
  "parameter1": "value1",
  "parameter2": 123
}
</codebuff_tool_call>
```

The constant `toolXmlName = 'codebuff_tool_call'` and tag boundaries are in `common/src/tools/constants.ts:6-10`. The parser is a stateful streaming XML extractor at `packages/agent-runtime/src/util/stream-xml-parser.ts:53-163` that handles partial tags at chunk boundaries, extracts the JSON payload, dispatches to the tool handler, and emits the surrounding text as normal assistant content.

A clever side effect: the `endsAgentStepParam = 'cb_easp'` constant (`common/src/tools/constants.ts:7`) is injected as an extra Zod field into tools flagged `endsAgentStep: true`, and `"cb_easp": true` becomes the **global stop sequence** for the LLM (`packages/agent-runtime/src/constants.ts:3`: `globalStopSequence = JSON.stringify(endsAgentStepParam)`). When the model emits a tool call that ends the agent step, it naturally terminates its own response via the stop sequence — meaning even non-function-calling providers behave like they have native tool calls.

The stream parser is dual-mode: `processStreamWithTools` (in `tool-stream-parser.ts`) accepts a `defaultProcessor` and a `processors` map keyed by tool name. The `executeXmlToolCall` callback (`stream-parser.ts:378-384`) executes XML-parsed calls **inline during streaming** (rather than after the stream completes), so long-running tools like `spawn_agents` start before the model finishes its sentence.

### 4.3 Tool Handler Shape

Each tool has a handler in `packages/agent-runtime/src/tools/handlers/tool/<name>.ts`, registered in `handlers/list.ts:56-99`. The type is `CodebuffToolHandlerFunction<T>` (`handlers/handler-function-type.ts`). A handler receives:

- `toolCall: CodebuffToolCall<T>` — `{ toolName, input, toolCallId, ... }`
- `agentState: AgentState` — the *parent* agent's mutable state
- `agentTemplate: AgentTemplate`
- `previousToolCallFinished: Promise<void>` — for sequential chaining
- `fileContext: ProjectFileContext`, `localAgentTemplates`, `tools`, `system`, `userId`, `userInputId`, `sendSubagentChunk`, `writeToClient`, plus the full `AgentRuntimeDeps` (DB, billing, LLM, analytics, fetch, etc.)

It returns `Promise<{ output: CodebuffToolOutput<T> }>`. Tool outputs are typed arrays of `{ type: 'json'; value: ... } | { type: 'text'; value: string }` parts — they are JSON-serialized into the tool-result message.

### 4.4 Tool Result Simplification

When context grows large, the `context-pruner` rewrites old tool results to compact stubs: `simplifyReadFileResults` replaces file contents with `{ path, contentOmittedForLength: true }` (`packages/agent-runtime/src/util/simplify-tool-results.ts:7-21`), and `simplifyTerminalCommandResults` drops stdout keeping only `{ command, message, exitCode, stdoutOmittedForLength: true }` (lines 23-61).

### 4.5 Custom Tools and MCP

SDK users can define custom tools via `getCustomToolDefinition({ toolName, description, inputSchema: z.object(...), execute })` (`sdk/src/custom-tool.ts`, used in `sdk/README.md:88-100`). Their schemas arrive as JSON Schema and are converted to Zod via `zod-from-json-schema` (`packages/agent-runtime/src/tools/prompts.ts:24-36`).

MCP servers per-agent (`agentDefinition.mcpServers`) are listed by `common/src/mcp/client.ts` and surfaced as additional tools through `getMCPToolData` (`packages/agent-runtime/src/mcp.ts`). They go through the same XML dispatch path.

---

## 5. Orchestration — the Agent Loop

### 5.1 Entry Path

A run starts in `sdk/src/run.ts:263` (`run()` → `runOnce()`). It builds a `SessionState`, wires `AgentRuntimeImpl` (`sdk/src/impl/agent-runtime.ts:49`), and calls `callMainPrompt` (`packages/agent-runtime/src/main-prompt.ts:167`). That function:

1. Resets `creditsUsed`/`directCreditsUsed` to 0 (server-side cost authority, line 184-185).
2. Appends any extra tool results (e.g. user-run terminal commands) to history.
3. Calls `assembleLocalAgentTemplates` (`templates/agent-registry.ts:93`) to merge dynamic `.agents/` definitions with bundled static templates.
4. Emits a `start` event chunk to the host.
5. Calls `mainPrompt(...)` (`main-prompt.ts:27`), which selects the agent type from `agentId` or `costMode` (a `Record<CostMode, AgentTemplateType>` map at lines 106-115: `ask→ask`, `free/lite→base_free`, `normal→base`, `max→base_max`, `experimental→base2`), looks up the template, and calls `loopAgentSteps`.

### 5.2 The `loopAgentSteps` Loop

`loopAgentSteps` (`packages/agent-runtime/src/run-agent-step.ts:667-1313`) is the heart of the system. Per iteration:

1. **Aborted check.** If `signal.aborted`, throws `AbortError`.
2. **`startAgentRun`** — registers a run row in the web DB; returns a `runId`. For `context-pruner` (lines 767-775), this is bypassed with an `untracked-` prefix to avoid 3 round-trips per main-agent step.
3. **Build initial messages.** Construct `messageHistory` from `initialAgentState.messageHistory` + the new user message + `instructionsPrompt`. Tag messages with `USER_PROMPT`, `INSTRUCTIONS_PROMPT`, `STEP_PROMPT`.
4. **Build tools.** `getToolSet` (`tools/prompts.ts:349-411`) merges (a) builtin tools filtered by `toolNames`, (b) custom tool definitions from MCP / SDK, (c) `agentTools` — the spawnable agents exposed as direct tool calls (see §7 below).
5. **Loop body** (`while (true)`, lines 983-1163):
   - Increment `totalSteps`.
   - Compute `stepPrompt` and `contextTokenCount` locally (no Anthropic token-count API call — comment at line 1017-1021 explains it added seconds of serial overhead).
   - **Run programmatic step first** if `handleSteps` is defined: `runProgrammaticStep` (`run-programmatic-step.ts:67`). This resumes the user's generator and may yield tool calls or signal end-of-turn.
   - **Schema retry**: if `outputSchema` is required but `output` is missing and the agent tried to end, push a system message asking it to use `set_output` and continue (lines 1063-1094).
   - **Run `runAgentStep`** (the LLM call + tool dispatch, lines 1108-1120).
   - **Steering hook**: drain `drainSteeringMessages` at the step boundary (lines 1149-1162) — lets the host inject mid-turn user messages without aborting.
6. **End conditions** (`runAgentStep` lines 583-609): turn ends when `task_completed` or `end_turn` is called, or when there are no tool calls/results (excluding `TOOLS_WHICH_WONT_FORCE_NEXT_STEP`). If response is `<think>...</think>`-only, the turn continues.
7. **Finalization**: `finishAgentRun` with `totalSteps`, `directCredits`, `totalCredits`. Returns `{ agentState, output: getAgentOutput(...) }`.

`getAgentOutput` (in `util/agent-output.ts`) converts the final state to one of `{ type: 'lastMessage', value: Message[] }`, `{ type: 'allMessages', value: Message[] }`, `{ type: 'error', message }`, or `{ type: 'structuredOutput', value }` depending on `outputMode`.

### 5.3 `runAgentStep` — Single LLM Call

`runAgentStep` (`run-agent-step.ts:162-654`) is invoked once per LLM round. It:

1. Checks `agentState.stepsRemaining <= 0` (line 268) — fires the `STEP_WARNING_MESSAGE` and forces `shouldEndTurn`.
2. Computes `stepPrompt` and the message array, calling `filterUnfinishedToolCalls` (line 311) and `expireMessages('agentStep')` (line 312) to keep history provider-safe.
3. Calls `getAgentStreamFromTemplate` (`prompt-agent-stream.ts:16`) which calls `promptAiSdkStream` → `streamText` from the `ai` SDK, routed through the Codebuff backend.
4. `processStream` (`tools/stream-parser.ts:118`) consumes the stream, parses XML tool calls, executes them, accumulates `assistantMessages`, `toolCalls`, `toolResults`, and `errorMessages`.
5. Updates `agentState.messageHistory` in `finally` (lines 532-575), filtering orphaned tool calls (lines 558-564) so providers like DeepSeek don't reject the next request with `unexpected tool_use_id`.

---

## 6. Isolation

### 6.1 Per-Agent State

Each agent (parent or child) gets its own `AgentState` (`agents/types/agent-definition.ts:275-300`):

```ts
interface AgentState {
  agentId: string                  // generateCompactId()
  runId: string
  parentId: string | undefined
  messageHistory: Message[]
  output: Record<string, any> | undefined
  systemPrompt: string
  toolDefinitions: Record<string, { description, inputSchema }>
  contextTokenCount: number
  // plus: agentContext (subgoals), subagents, childRunIds,
  //       stepsRemaining, creditsUsed, directCreditsUsed,
  //       ancestorRunIds, agentType
}
```

A child agent's state is created by `createAgentState` (`spawn-agent-utils.ts:252-329`):
- Fresh `agentId` (compact random id).
- `parentId` set to parent's `agentId`.
- `ancestorRunIds` = `[...parent.ancestorRunIds, parent.runId]`.
- `stepsRemaining` reset to `MAX_AGENT_STEPS_DEFAULT` (200, `common/src/constants/agents.ts:95`).
- `creditsUsed`/`directCreditsUsed` reset to 0 (child costs aggregate back to parent in `spawn-agents.ts:218-259`).
- `messageHistory` — empty unless `includeMessageHistory: true`, in which case it's the parent's history sliced up to (but not including) the spawn tool call (lines 268-307). Synthetic `SUBAGENT_SPAWN` announcements and orphan tool calls are filtered out.

### 6.2 Two Spawn Modes — `spawn_agents` vs `spawn_agent_inline`

- **`spawn_agents`** (`packages/agent-runtime/src/tools/handlers/tool/spawn-agents.ts:34`): the standard fan-out tool. Children run with their own system prompt, their own tools, and their own (possibly empty) message history. The parent receives a JSON report: `[{ agentName, agentType, value: <output> }, ...]`. Children do **not** mutate the parent's state directly.
- **`spawn_agent_inline`** (`spawn-agent-inline.ts:26`): the child **shares the parent's message history and system prompt** (`inlineTemplate.includeMessageHistory = true; inheritParentSystemPrompt = true` — lines 94-118). When the child finishes, `parentAgentState.messageHistory = result.agentState.messageHistory` (line 174) — the parent's history is *replaced* by the child's. This is how `context-pruner` runs: it's spawned inline before each main-agent step, rewrites the shared history in-place, and the parent's next LLM call sees the compacted transcript. The inline child's tool calls are also hidden from the client UI unless they're lifecycle events (`subagent_start`/`subagent_finish`).

### 6.3 Tool-Level Isolation

Tools execute in the same Node/Bun process as the runtime — there is **no per-tool subprocess sandbox** (with one exception: terminal commands get their own process group, see §9). Tool handlers receive the parent agent's state by reference and can mutate `messageHistory` (e.g. `set_messages`, `add_message`) or `agentContext` (e.g. `update_subgoal`).

`handleSteps` generators are sandboxed only in the sense that they're `eval`'d from a stringified form (`run-programmatic-step.ts:38-41`); they cannot close over outer module scope. Module-level state they touch (the generator cache `runIdToGenerator`, the `STEP_ALL` flag set, the proposed-content store) is cleaned up in `clearProgrammaticRunState(runId)` on every loop exit, including abort and error paths (`run-agent-step.ts:1307-1312`).

---

## 7. Parallelization

### 7.1 `spawn_agents` is Concurrent by Default

The `spawn_agents` tool's parameter doc (`common/src/tools/params/tool/spawn-agents.ts` and `agents/types/tools.ts:337-348`) explicitly says:

> "Spawn multiple agents and send a prompt and/or parameters to each of them. **These agents will run in parallel.** Note that that means they will run independently. If you need to run agents sequentially, use spawn_agents with one agent at a time instead."

Implementation in `spawn-agents.ts:89-196`:

```ts
const results = await Promise.allSettled(
  agents.map(async ({ agent_type, prompt, params }) => {
    // ... validate, createAgentState, executeSubagent
  }),
)
```

Each spawned agent's `executeSubagent` (`spawn-agent-utils.ts:369-440`) calls `loopAgentSteps` recursively. Because `loopAgentSteps` is `async` and the runtime is single-threaded JavaScript, agents **interleave** via `await` points (LLM stream chunks, file I/O, terminal output). They do not literally run on separate threads, but their LLM calls, tool executions, and stream processing all progress concurrently — bounded only by the event loop.

### 7.2 `GENERATE_N` — N Completions in One LLM Call

`handleSteps` generators can yield `{ type: 'GENERATE_N', n }` (see `agents/types/agent-definition.ts:324`). This is a *single* LLM request that asks the model for `n` parallel completions (`run-agent-step.ts:458-510` passes `n` into `promptAiSdk` and parses the response as a JSON array of strings). Used by `thinker-best-of-n` (`agents/thinker/best-of-n/thinker-best-of-n.ts:81-84`) to generate 3-6 candidate reasonings, then a `thinker-selector` subagent picks the best.

### 7.3 Barriers

There is no formal "barrier" primitive. The implicit barrier is the `await Promise.allSettled(...)` in `spawn-agents.ts:89` — the tool call only returns when all child agents have finished (or failed). The parent's next LLM call sees all child outputs at once.

There is also **sequential chaining within a single step** via `previousToolCallFinished` (`stream-parser.ts:268-332`). Each tool call's handler awaits the previous one's promise before starting. For XML-mode calls (the inline-executed path), the await is synchronous (`await toolPromise` at line 336) so tool results appear inline before the stream continues. For native-SDK tool calls (the post-stream path), they're chained but not awaited inline.

### 7.4 Best-of-N Editor Pattern

`editor-multi-prompt` (`agents/editor/best-of-n/editor-multi-prompt.ts:58-246`) demonstrates the parallel-then-select pattern cleanly:

1. `set_messages` to trim history to before the last user message (lines 78-95).
2. `spawn_agents` with N `editor-implementor-opus` children, one per strategy prompt (lines 98-111) — **all run in parallel**.
3. Each child returns `{ toolCalls, toolResults, unifiedDiffs }` as structured output.
4. Spawn one `best-of-n-selector2` with all implementations as params (lines 141-158).
5. Selector returns `{ implementationId, reason, suggestedImprovements }`.
6. Parent applies the chosen implementation's tool calls as real `str_replace`/`write_file` edits (lines 191-209), converting `propose_*` calls to real ones.
7. `set_output` with the chosen strategy, reason, applied results, and suggested improvements.

This is the seam pattern: **children produce structured proposals, parent selects and applies**.

---

## 8. Delegation — How Agents Hand Off Work

### 8.1 Spawnable Agents Whitelist

An agent can only spawn agents in its `spawnableAgents` array (`agent-definition.ts:131-138`). The base orchestrator's whitelist (`agents/base2/base2.ts:148-168`) varies by mode:

- `default` mode: `file-picker, code-searcher, researcher-web, researcher-docs, basher, thinker, opus-agent, gpt-5-agent, editor, tmux-cli, browser-use, code-reviewer, thinker-gpt, context-pruner`
- `max` mode: same but with `-max` variants + `editor-multi-prompt`, `thinker-best-of-n-opus`, `code-reviewer-multi-prompt`
- `lite`/`free` modes: stripped down; reviewer is model-dependent (`CODEBUFF_REVIEWER_BY_MODEL`, lines 47-51).

The check is `getMatchingSpawn` in `spawn-agent-utils.ts:113-169` — it parses publisher/version from both sides and matches on agent-id, optionally with publisher and/or version wildcards.

A special case: the **base agents** (`['base', 'base-free', 'base-max', 'base-experimental']`, line 183) can spawn *any* agent via `normalizeAgentIdForLookup` (line 186) — this is how `@AgentName` user mentions work.

### 8.2 Two Delegation Mechanisms

1. **`spawn_agents` tool** (structured fan-out, parallel): child runs to completion, returns a JSON report. This is ** delegation by result contract** — the parent hands off a sub-goal and gets back a structured value. The seam is `outputMode` + `outputSchema` on the child (`last_message`, `all_messages`, or `structured_output` with a Zod schema).

2. **Agent-as-direct-tool-call** (`buildAgentToolSet`, `packages/agent-runtime/src/templates/prompts.ts:74-112`): each spawnable agent is also exposed to the model as a tool with the agent's short-name (`getAgentToolName`, lines 37-39, e.g. `file_picker`). The tool's input schema is the agent's `inputSchema`. When the model emits `<codebuff_tool_call>{ "cb_tool_name": "file_picker", ... }</codebuff_tool_call>`, `tryTransformAgentToolCall` (`tool-executor.ts`) rewrites it to a `spawn_agents` call internally. This gives the model a more natural interface for single-agent delegation while keeping the same execution path.

### 8.3 Inline Delegation

`spawn_agent_inline` is the third mechanism — used for agents that should **mutate the parent's context** rather than return a value. Currently only `context-pruner` uses it (driven by the base agent's `handleSteps`, see `agents/base2/base2.ts:393-471`). The child runs, rewrites the shared `messageHistory`, and the parent continues from the new state.

### 8.4 Result Merge Back to Parent

When `spawn_agents` returns, its result is a JSON array of `{ agentName, agentType, value: AgentOutput }` (`spawn-agents.ts:198-216`). `AgentOutput` is one of:
- `{ type: 'lastMessage', value: Message[] }` — the child's last assistant message.
- `{ type: 'allMessages', value: Message[] }` — the child's full transcript.
- `{ type: 'structuredOutput', value: <matches outputSchema> }` — validated JSON.
- `{ type: 'error', message }` — failure with optional `statusCode`, `errorCode`, `countryCode`, etc.

The parent's LLM sees this as a `tool` message in its next step. Cost aggregation (`spawn-agents.ts:218-259`) walks `results` and adds each child's `creditsUsed` to `parentAgentState.creditsUsed` — even failed children's partial costs are accounted for.

---

## 9. Safety

### 9.1 Step Cap (Recursion Limit)

`MAX_AGENT_STEPS_DEFAULT = 200` (`common/src/constants/agents.ts:95`). Each `runAgentStep` decrements `agentState.stepsRemaining` (`run-agent-step.ts:611-615`). When it hits zero, the step bails with `STEP_WARNING_MESSAGE` and forces `shouldEndTurn = true` (lines 268-293). The user can override via `CodebuffClientOptions.maxAgentSteps` (`sdk/src/run.ts:115`, default applied at line 292).

This is a **per-agent** cap, not a global recursion cap — a child agent gets a fresh 200 steps. But because each child is awaited by its parent (the `spawn_agents` barrier), the total work is bounded by `200 × max_parallel_spawns × spawn_depth`. In practice the depth is shallow (3-4 levels: base → editor-multi-prompt → editor-implementor → done).

### 9.2 Stream Recovery

If the LLM stream drops mid-response or the model burns its output budget on reasoning, `classifyStreamEndRecovery` (`sdk/src/impl/stream-interruption.ts`) detects it, the stream parser pushes a `STREAM_INTERRUPTED` or `OUTPUT_LIMIT` tagged user message into history (`stream-parser.ts:440-486`), and `hadToolCallError = true` forces another step. After `MAX_CONSECUTIVE_STREAM_RECOVERIES = 3` (`stream-parser.ts:49`) consecutive failures, the turn fails loudly with `REPEATED_STREAM_INTERRUPTIONS_MESSAGE` — preventing a runaway retry loop from burning 200 steps.

### 9.3 Output Schema Retry

If an agent has an `outputSchema` but tries to end without calling `set_output`, the loop *retries once* (`run-agent-step.ts:1063-1094`): pushes a system message "You must use the set_output tool..." and continues the turn. `hasRetriedOutputSchema` ensures it only happens once.

### 9.4 Abort / Cancellation

The whole run is governed by an `AbortSignal` threaded through every layer (`RunOptions.signal`, `sdk/src/run.ts:175`). `loopAgentSteps` checks `signal.aborted` at the top of each iteration (line 985) and throws `AbortError`. The `processStream` loop breaks on abort (`stream-parser.ts:394`), filters orphaned tool calls (lines 558-564), and re-throws. The `finally` block in `loopAgentSteps` (lines 1307-1312) always calls `clearProgrammaticRunState(runId)` to release the generator, `STEP_ALL` flag, and proposed file content — preventing leaks when the SSE disconnects.

The SDK also supports **steering** (`drainSteeringMessages`, `sdk/src/run.ts:181`): the host can inject user messages at step boundaries without aborting, letting a user "redirect" a running agent.

### 9.5 State Snapshots / Crash Recovery

`onStateSnapshot` (`sdk/src/run.ts:194`, fired every 5s, line 198) checkpoints the run state. The snapshot uses `cloneSessionState` (lines 230-245) which JSON-clones only `mainAgentState` (not `fileContext`, which is shared by reference) — ~50× faster than `cloneDeep` (~4ms vs 230ms on an 8MB session). This lets the CLI recover partial progress after a crash.

### 9.6 Terminal Command Safety

`run_terminal_command` (`sdk/src/tools/run-terminal-command.ts:307-585`) is the riskiest tool. Safeguards:
- Commands run in their own **process group** on POSIX (`detached: true`, line 391) so killing the group kills grandchildren.
- On Windows, `taskkill.exe /pid X /t /f` is used to terminate the whole tree (lines 152-162).
- A `BoundedOutputBuffer` (lines 80-144) caps retained stdout/stderr at `COMMAND_OUTPUT_LIMIT = 50_000` chars (line 16), keeping head + tail and inserting a `[...TRUNCATED DUE TO LENGTH...]` marker.
- Timeout via `timeout_seconds` (default 30, line 313), with SIGTERM → 1.5s grace → SIGKILL escalation (`KILL_ESCALATION_MS = 1500`, line 22).
- An `exitSweep` (lines 221-229) registers a `process.on('exit')` handler that SIGKILLs any still-running children.
- `BACKGROUND` process type is declared but unimplemented (line 322-324): "BACKGROUND process_type not implemented".
- The system prompt (`agents/base2/base2.ts:194`) explicitly warns against destructive commands (`git push`, `git commit`, package installs, production scripts) unless the user asks.

### 9.7 What's Missing

Notably absent:
- **No file-write allowlist/denylist.** `write_file` and `str_replace` can write anywhere under `cwd`. The system prompt asks the model not to write outside the project, but there's no enforcement.
- **No code execution sandbox.** `run_terminal_command` runs arbitrary bash with the user's full env. There is no Docker/firejail wrapper.
- **No per-tool wall-clock cap** (other than terminal timeout). Long-running `web_search` or `read_url` calls have no individual timeout.
- **No recursive spawn depth limit** beyond the per-agent step cap. A misbehaved agent could theoretically spawn a chain `A → B → C → ...` until the step cap arrests the deepest one.

---

## 10. Memory

### 10.1 Ephemeral, Per-Session

Codebuff has **no persistent vector memory**. State lives in `SessionState` (`sdk/src/run-state.ts:61-65`):

```ts
type RunState = {
  sessionState?: SessionState  // { fileContext, mainAgentState }
  output: AgentOutput
  traceSessionId: string
}
```

A `RunState` is returned from each `client.run()` and can be passed back as `previousRun` to continue the same session (`sdk/README.md:42-49`). Between CLI sessions, the host is responsible for persistence — the SDK does not write to disk.

### 10.2 `messageHistory` Is the Memory

The single source of truth is `agentState.messageHistory` — an array of `Message` objects (user / assistant / tool / system) with optional `tags` (e.g. `USER_PROMPT`, `INSTRUCTIONS_PROMPT`, `STEP_PROMPT`, `SUBAGENT_SPAWN`, `STREAM_INTERRUPTED`, `OUTPUT_LIMIT`, `TOOL_CALL_ERROR`) and `timeToLive` / `keepDuringTruncation` flags. `expireMessages(history, 'agentStep'|'userPrompt')` (`packages/agent-runtime/src/util/messages.ts`) drops ephemeral messages at the right boundary.

### 10.3 Context Pruner

When history exceeds the model's context window, the `context-pruner` agent (`agents/context-pruner.ts:13-944`) runs. It:
- Walks `agentState.messageHistory`, separating user / assistant / tool messages.
- For blacklisted agent outputs (file-picker, researcher-web, basher, code-reviewer, librarian, tmux-cli, browser-use — lines 51-62), drops the spawn_agents result entirely.
- Truncates long messages: `USER_MESSAGE_LIMIT = 13_000`, `ASSISTANT_MESSAGE_LIMIT = 1_300`, `TOOL_ENTRY_LIMIT = 5_000` chars (lines 65-67).
- Builds a token-budgeted summary (`ASSISTANT_TOOL_BUDGET = 20_000`, `USER_BUDGET = 50_000`, lines 73-76) and replaces the history with `{ header: SUMMARY_HEADER, ...summary, footer: SUMMARY_DISCLAIMER }`.
- It's spawned **inline** before every main-agent step via the base agent's `handleSteps` (`agents/base2/base2.ts:393-471`), so the parent's history is rewritten in-place.

### 10.4 Knowledge Files (Static Context)

`knowledge.md`, `AGENTS.md`, or `CLAUDE.md` in the project root are loaded as static context (`common/src/constants/knowledge.ts`, `sdk/src/run-state.ts:50-59`). Priority order: `knowledge.md > AGENTS.md > CLAUDE.md`. These are injected into the system prompt via the `{CODEBUFF_KNOWLEDGE_FILES_CONTENTS}` placeholder (`agents/types/secret-agent-definition.ts:34`).

### 10.5 Subgoal Memory

`agentContext: Record<string, Subgoal>` on `AgentState` is a per-agent scratchpad for plans/subgoals, manipulated via `add_subgoal` / `update_subgoal` / `create_plan` tools. Not persistent across runs.

### 10.6 Trace Writer

An optional `TraceWriter` (`sdk/src/run.ts:148`) receives the full message history at each step boundary (`run-agent-step.ts:427-435` and 618-626). Hosts use this for replay/debug. It's append-once per step.

---

## 11. Model Layer

### 11.1 OpenRouter via Codebuff Backend

Codebuff does **not** call model providers directly. All traffic flows through the Codebuff web backend (`sdk/src/impl/model-provider.ts:81-151`):

```ts
return new OpenAICompatibleChatLanguageModel(model, {
  provider: 'codebuff',
  url: ({ path: endpoint }) =>
    new URL(path.join('/api/v1', endpoint), getWebsiteUrl()).toString(),
  headers: () => ({
    Authorization: `Bearer ${apiKey}`,
    'user-agent': `ai-sdk/openai-compatible/${VERSION}/codebuff`,
    ...(userId && { [FREEBUFF_ACTING_USER_HEADER]: userId }),
    ...(openrouterApiKey && { [BYOK_OPENROUTER_HEADER]: openrouterApiKey }),
  }),
  // ...metadataExtractor pulls usage.cost from OpenRouter responses
})
```

The backend forwards to OpenRouter, which routes to the actual provider (Anthropic, OpenAI, Google, Bedrock, Fireworks, etc.). This gives Codebuff: (a) billing/credits centralization, (b) provider routing policies (e.g. `data_collection: 'deny'` is enforced on every paid request — `agents/base2/base2.ts:353-376`), (c) BYOK support (users can supply their own OpenRouter key via `BYOK_OPENROUTER_HEADER`), (d) free-tier gating (the `FREEBUFF_ACTING_USER_HEADER` lets trusted service accounts run on behalf of end users).

The model spec is any OpenRouter model ID (`agents/types/agent-definition.ts:380-463` lists ~50 recommended models from OpenAI, Anthropic, Google, x-AI, Qwen, DeepSeek, Xiaomi MiMo, Moonshot Kimi, Z-AI GLM, MiniMax). The `model` field is a `string & {}` branded type so any string works.

### 11.2 Provider Abstraction

The actual provider implementation is `@codebuff/llm-providers/openai-compatible` (`packages/llm-providers/src/openai-compatible/`), a fork of OpenRouter's AI SDK provider. It exposes:
- `OpenAICompatibleChatLanguageModel` (chat)
- `OpenAICompatibleCompletionLanguageModel` (legacy completions)
- `OpenAICompatibleEmbeddingModel`
- `OpenAICompatibleImageModel`

The chat model (`packages/llm-providers/src/openai-compatible/chat/openai-compatible-chat-language-model.ts`) handles:
- Converting Codebuff's internal `Message[]` to OpenAI chat format (`convert-to-openai-compatible-chat-messages.ts`).
- Preparing tools (`openai-compatible-prepare-tools.ts`) — though as noted, Codebuff injects tools into the system prompt as XML rather than using the native `tools` API parameter, this conversion is mostly for the token-count API.
- Extracting usage metadata (`openai-compatible-metadata-extractor.ts`) including OpenRouter's `usage.cost` field for billing.
- Mapping finish reasons (`map-openai-compatible-finish-reason.ts`).

### 11.3 Cost Tracking

`getProviderOptions` (`sdk/src/impl/llm.ts:69-128`) wraps every request with a `codebuff.codebuff_metadata` object containing `run_id`, `client_id`, `n` (if GENERATE_N), `cost_mode`, and `cache_debug_correlation`. The backend uses this for attribution. Credits are calculated as `Math.round(costDollars * (1 + PROFIT_MARGIN) * 100)` (line 63-67) — a markup on the upstream OpenRouter cost.

### 11.4 Per-Agent Model Selection

Each agent picks its own model — there's no global model setting. The base orchestrator uses `OPUS_MODEL` (Claude Opus 5) for default/max/fast modes, `LITE_MODEL` for lite, `FREEBUFF_MINIMAX_M3_MODEL_ID` for free (`agents/base2/base2.ts:32-38`). Sub-agents pick cheaper models: `basher` and `file-picker` use Gemini 3.5 Flash Lite; `thinker` uses Opus; `librarian` uses MiniMax M3; `code-reviewer-deepseek` uses DeepSeek; etc. This per-agent model routing is a key efficiency lever.

### 11.5 Prompt Caching

`supportsCacheControl(model)` (`common/src/old-constants`) gates whether `withCacheControl` is applied to messages. The `inheritParentSystemPrompt` flag exists specifically to enable prompt caching: a child that inherits the parent's system prompt keeps the same prefix, so Anthropic's 5-minute ephemeral cache hits. The `context-pruner`'s `cacheExpiryMs: 30 * 60 * 1000` param (in `base2.ts:402`) sets the expectation for how long cache continuity is maintained.

---

## 12. Notable Design Choices Worth Borrowing

1. **XML-based tool calling instead of native function-calling.** This is the single most opinionated choice. It makes Codebuff **provider-agnostic** — any model that can emit text can call tools, including open-source models on OpenRouter that don't support native tool calls. The cost is a custom streaming XML parser (`stream-xml-parser.ts`) and the need to inject tool docs into the system prompt. The `cb_easp` stop-sequence trick (where ending a step naturally terminates the model's response) is elegant.

2. **`handleSteps` as a serialized TypeScript generator.** Agents aren't just prompts — they're programs. The generator can yield tool calls, LLM steps, parallel N-completions, and synthetic text, all in a single readable function (see `basher.ts:60-139`, `editor-multi-prompt.ts:58-246`). The fact that it's stringified and `eval`'d means it can be shipped to the backend and executed there without shipping the whole module graph. The trade-off: no closures over outer scope, which is repeatedly called out in comments (e.g. `agents/base2/base2.ts:341-343`).

3. **Inline subagents that mutate parent state.** `spawn_agent_inline` is a unique pattern: a child agent that *shares* the parent's message history and system prompt, runs to completion, and **overwrites** the parent's history with its own. This is how the `context-pruner` works transparently — it's a separate agent with its own model (Sonnet 4.6) and prompts, but it edits the parent's transcript in-place. No other agent framework I've seen does this so cleanly.

4. **Per-agent model routing with cost-aware fallbacks.** The `CODEBUFF_REVIEWER_BY_MODEL` map (`base2.ts:47-51`) picks a reviewer agent whose model matches the parent's tier — a free-tier session gets `code-reviewer-deepseek-flash`, a paid Opus session gets `code-reviewer`. The `canFreebuffModelSpawnGeminiThinker` gate (`base2.ts:96`) limits which free models can pull a premium Gemini Pro thinker. This is sophisticated cost engineering at the orchestration layer.

5. **The `propose_*` → apply pattern for safe edits.** `propose_str_replace` and `propose_write_file` (`common/src/tools/params/tool/propose-str-replace.ts`, `propose-write-file.ts`) stage edits without applying them. The `editor-implementor-*` agents use these to produce proposals, the `best-of-n-selector2` picks the best, and the parent `editor-multi-prompt` converts `propose_*` calls to real `str_replace`/`write_file` calls (`editor-multi-prompt.ts:191-209`). This gives a clean **propose/select/apply** seam that's reusable.

6. **Tool-result simplification under memory pressure.** Rather than dropping old tool results entirely, `simplifyReadFileResults` and `simplifyTerminalCommandResults` replace them with stubs (`{ path, contentOmittedForLength: true }`). The model still sees *that* a file was read, just not its contents — preserving the conversation's narrative without paying the token cost.

7. **Untracked runs for hot-path internal agents.** The `context-pruner` runs before every main-agent step. Recording its runs in the web DB would cost 3 round-trips per step. The `UNTRACKED_RUN_ID_PREFIX = 'untracked-'` (`run-agent-step.ts:160`, 767-775) bypasses the ledger entirely — a clean escape hatch for internal agents that don't need observability.

8. **The `skills` system as lightweight prompt injection.** Skills are just markdown files with YAML frontmatter, loaded on-demand via the `skill` tool. No model binding, no tool registration — pure prompt fragments the model can pull in when relevant. This is a much lower-friction extension mechanism than full agent definitions.

9. **Steering without aborting.** `drainSteeringMessages` (`run-agent-step.ts:684-688`, 1149-1162) lets a host inject user messages at step boundaries without aborting the run. The agent sees them as new user prompts and continues its turn. This is a much smoother UX than cancel-and-re-run.

10. **Dual spawn interfaces (tool-call-shaped and structured).** Spawnable agents are exposed both as the structured `spawn_agents` tool (for parallel fan-out with explicit params) and as direct tool calls (e.g. `file_picker`) that the model can invoke naturally. `tryTransformAgentToolCall` rewrites the latter into the former. This gives the model the most natural interface while keeping one execution path.

---

## Appendix A: Key File Reference

| Concern | File |
|---|---|
| Agent definition type | `agents/types/agent-definition.ts:21-269` |
| Tool name + param types | `agents/types/tools.ts:1-437` + `common/src/tools/list.ts:46-86` |
| Tool constants (XML tags, lists) | `common/src/tools/constants.ts:1-114` |
| Agent personas + step cap | `common/src/constants/agents.ts:1-96` |
| Agent template lookup | `packages/agent-runtime/src/templates/agent-registry.ts:21-122` |
| Spawnable-agent-as-tool builder | `packages/agent-runtime/src/templates/prompts.ts:74-189` |
| Tool prompt assembly | `packages/agent-runtime/src/tools/prompts.ts:106-411` |
| XML stream parser | `packages/agent-runtime/src/util/stream-xml-parser.ts:53-163` |
| Tool dispatch + stream processing | `packages/agent-runtime/src/tools/stream-parser.ts:118-589` |
| Tool executor (parse + validate + run) | `packages/agent-runtime/src/tools/tool-executor.ts:1-827` |
| Tool handler registry | `packages/agent-runtime/src/tools/handlers/list.ts:56-99` |
| `spawn_agents` handler | `packages/agent-runtime/src/tools/handlers/tool/spawn-agents.ts:34-263` |
| `spawn_agent_inline` handler | `packages/agent-runtime/src/tools/handlers/tool/spawn-agent-inline.ts:26-178` |
| Subagent state creation + execution | `packages/agent-runtime/src/tools/handlers/tool/spawn-agent-utils.ts:113-441` |
| `runAgentStep` (single LLM call) | `packages/agent-runtime/src/run-agent-step.ts:162-654` |
| `loopAgentSteps` (the loop) | `packages/agent-runtime/src/run-agent-step.ts:667-1313` |
| `runProgrammaticStep` (handleSteps) | `packages/agent-runtime/src/run-programmatic-step.ts:67-623` |
| `mainPrompt` entry | `packages/agent-runtime/src/main-prompt.ts:27-265` |
| Base orchestrator agent | `agents/base2/base2.ts:53-579` |
| Context pruner agent | `agents/context-pruner.ts:13-944` |
| Editor (single) | `agents/editor/editor.ts:29-159` |
| Editor (best-of-N) | `agents/editor/best-of-n/editor-multi-prompt.ts:11-253` |
| Best-of-N selector | `agents/editor/best-of-n/best-of-n-selector2.ts:7-149` |
| Thinker (best-of-N) | `agents/thinker/best-of-n/thinker-best-of-n.ts:10-246` |
| Basher (terminal) | `agents/basher.ts:10-143` |
| File picker | `agents/file-explorer/file-picker.ts:13-269` |
| Librarian (repo clone) | `agents/librarian/librarian.ts:8-156` |
| Browser-use agent | `agents/browser-use/browser-use.ts:5-260` |
| SDK run entry | `sdk/src/run.ts:263-743` |
| SDK session state | `sdk/src/run-state.ts:61-940` |
| SDK agent-runtime impl | `sdk/src/impl/agent-runtime.ts:49-153` |
| SDK LLM stream | `sdk/src/impl/llm.ts:191-732` |
| SDK model provider | `sdk/src/impl/model-provider.ts:81-152` |
| SDK terminal command tool | `sdk/src/tools/run-terminal-command.ts:307-585` |
| SDK local agent loader | `sdk/src/agents/load-agents.ts:201-337` |
| SDK skills loader | `sdk/src/skills/load-skills.ts:47-250` |
| OpenAI-compatible LLM provider | `packages/llm-providers/src/openai-compatible/` |
| Tree-sitter code map | `packages/code-map/src/parse.ts` |

## Appendix B: Tool Roster (with file refs)

| Tool | Description | Param file |
|---|---|---|
| `read_files` | Read multiple files (20k token / 100k char limit) | `common/src/tools/params/tool/read-files.ts` |
| `read_subtree` | Tree-sitter-parsed directory blob | `read-subtree.ts` |
| `write_file` | Create/edit a file | `write-file.ts` |
| `str_replace` | Exact-match string replacement | `str-replace.ts` |
| `apply_patch` | Codex-style unified diff patch | `apply-patch.ts` |
| `propose_write_file` | Stage a write without applying | `propose-write-file.ts` |
| `propose_str_replace` | Stage a str_replace without applying | `propose-str-replace.ts` |
| `run_terminal_command` | Bash command (SYNC only; BACKGROUND unimplemented) | `run-terminal-command.ts` |
| `code_search` | ripgrep wrapper | `code-search.ts` |
| `glob` | File glob (sorted by mtime) | `glob.ts` |
| `list_directory` | List dir contents | `list-directory.ts` |
| `find_files` | Natural-language file finder | `find-files.ts` |
| `read_url` | Fetch URL, extract text (max 20k chars) | `read-url.ts` |
| `read_docs` | Context7 API for library docs | `read-docs.ts` |
| `web_search` | Serper API | `web-search.ts` |
| `spawn_agents` | Parallel subagent fan-out | `spawn-agents.ts` |
| `spawn_agent_inline` | Inline subagent (shares parent history) | `spawn-agent-inline.ts` |
| `set_output` | Set agent's structured output | `set-output.ts` |
| `set_messages` | Replace message history | `set-messages.ts` |
| `add_message` | Append a message | `add-message.ts` |
| `write_todos` | Write a todo list | `write-todos.ts` |
| `add_subgoal` / `update_subgoal` | Subgoal scratchpad | `add-subgoal.ts` / `update-subgoal.ts` |
| `create_plan` | Plan creation | `create-plan.ts` |
| `task_completed` | Signal task done | `task-completed.ts` |
| `end_turn` | End the turn | `end-turn.ts` |
| `ask_user` | Multiple-choice questions to user | `ask-user.ts` |
| `suggest_followups` | Suggest clickable followups | `suggest-followups.ts` |
| `render_ui` | Button widget in CLI | `render-ui.ts` |
| `think_deeply` | Brainstorming step | `think-deeply.ts` |
| `skill` | Load a skill's instructions | `skill.ts` |
| `lookup_agent_info` | Retrieve info about an agent by ID | `lookup-agent-info.ts` |
| `gravity_index` | Service discovery API | `gravity-index.ts` |
| `browser_logs` | Browser console logs | `browser-logs.ts` |
| `run_file_change_hooks` | Trigger file-change hooks | `run-file-change-hooks.ts` |
| `cloud_plan_ready` | Cloud plan ready signal | `cloud-plan-ready.ts` |
| `composio_*` (4 tools) | Composio integration meta-tools | `composio.ts` |
