# LocalMind — Architecture

> **Last updated:** 2026-07-31 (v4.1 — 8-agent registry, 15 tools)

## Overview

LocalMind is a layered system. Each layer has one responsibility and communicates only with the layer directly above or below it. No layer knows about the user interface. No layer calls the model directly except the adapter.

```
┌─────────────────────────────────────────────────┐
│                   SURFACE                        │
│          Web UI (React)  │  CLI (Typer)          │
└──────────────┬───────────┴───────┬───────────────┘
               │                   │
┌──────────────▼───────────────────▼───────────────┐
│                  API LAYER                        │
│          FastAPI  ·  SSE streaming                │
└──────────────────────┬────────────────────────────┘
                       │
┌──────────────────────▼────────────────────────────┐
│                 CORE ENGINE (v4.0)                 │
│   ThinkingDispatcher → Tool Dispatcher → Context  │
│   Builder → Response Assembler → Memory           │
│                                                   │
│   Sub-systems:                                    │
│   - agent/ (AgentLoop, orchestrator, sub-agents)  │
│   - workspace/ (WorkspaceOrchestrator)            │
│   - execution_graph.py (DAG-based parallel exec)  │
│   - flywheel.py (routing learning)                │
│   - safety_gate.py (input safety)                 │
│   - metrics.py (p50/p95 per intent)               │
└──────┬──────────────┬────────────┬───────────────┘
       │              │            │
┌──────▼──────┐ ┌─────▼─────┐ ┌───▼──────────────┐
│ TOOL        │ │ STORAGE   │ │ ADAPTER           │
│ REGISTRY    │ │ SQLite +  │ │ Ollama            │
│ 15 tools    │ │ sqlite-vec│ │ OpenAI-compat     │
│ (see below) │ └───────────┘ └──────────────────┘
└─────────────┘
```

## Layers

### Surface
Web UI (React 19 + Vite 6, served by FastAPI) and CLI (Typer). Both are thin wrappers — all intelligence is in the engine. Adding a new surface requires zero changes to any other layer.

Electron wraps the web UI as a desktop app.

### API Layer
FastAPI application. Handles HTTP routing, multipart file uploads, and SSE streaming. Routes live in `api/routes/` — one file per resource (13 route files).

### Core Engine (v4.0)
The central coordinator (`core/engine/`). The v4.0 pipeline has 6 layers:

0. **Safety Gate** — blocks unsafe messages
1. **Load History + Persist User Message**
2. **Capability Inference** via ThinkingDispatcher → OrchestrationPlan (TaskProfile + ExecutionGraph)
3. **Derive routing** from TaskProfile.execution_mode
4. **Execute**: DIRECT (chat) | SINGLE_TOOL | MULTI_TOOL | AGENT_LOOP | MULTI_PHASE
5. **Post-Processing**: Memory persistence, history, observability, metrics

Key sub-modules:
- **ThinkingDispatcher** (`core/thinking_dispatcher.py`) — the SOLE routing mechanism (no regex classifier). Uses LLM capability inference.
- **AgentLoop** (`core/agent/loop.py`) — multi-turn parent agent with tool calling, verification, and delegation dispatch.
- **ExecutionGraph** (`core/execution_graph.py`) — DAG-based parallel capability execution.
- **Flywheel** (`core/flywheel.py`) — learns from routing outcomes to improve future dispatching.
- **MetricsStore** (`core/metrics.py`) — aggregated p50/p95 latency per intent + tool success rates.
- **SafetyGate** (`core/safety_gate.py`) — input safety screening.

### Agent Registry (ADR-6)

8 agents sharing a common `BaseAgent` with per-agent scoped toolset (ADR-6). Smaller tool surface = more reliable selection on small models.

| # | Agent | Iter | Wall | Tools | Role |
|---|---|---|---|---|---|
| 1 | Browser | 15 | 240s | browse + delegate | Drive a browser |
| 2 | Coding | 20 | 600s | shell, file_task, file_write, edit_file, code_exec, git, process, delegate | Build & edit code |
| 3 | Research | 10 | 300s | web_search, web_fetch, delegate | Search & fetch web |
| 4 | Direct | 1 | 60s | (none) | Single model call |
| 5 | Verifier | 15 | 480s | shell, process, git, file_task, edit_file, delegate | Run tests, prove it works |
| 6 | Reviewer | 10 | 300s | file_task, git, shell, delegate | Assess quality & specs |
| 7 | Debugger | 12 | 360s | file_task, git, shell, process, delegate | Isolate root causes |
| 8 | Analyst | 8 | 180s | file_task, git, delegate | Clarify requirements |

Agents live in `agents/<name>/` directories (ADR-8 Principle 5). Each directory contains: `agent.py`, `context_builder.py`, `tools.py`, `is_done.py`, `playbook.md`. The registry auto-discovers directories with `agent.py`.

Intent → agent routing in `agents/selection.py`: `Intent.VERIFY → verifier`, `Intent.REVIEW → reviewer`, etc.

### Tool Registry
15 isolated modules in `tools/`. Each tool exposes a single `async run()` function. Tools share no state. A broken tool cannot crash the engine.

| Tool | Module | Risk | Description |
|---|---|---|---|
| File reader | `file_reader.py` | LOW | PDF, DOCX, CSV, XLSX, code, images (OCR) |
| File writer | `file_writer.py` | HIGH | Create/edit files (permission-gated) |
| Edit file | `edit_file.py` | HIGH | Surgical edits to existing files |
| Web search | `web_search.py` | LOW | DDG + SearXNG race, Brave fallback |
| Web fetch | `web_fetch.py` | LOW | Fetch and parse a specific URL |
| Browser agent | `browser_agent.py` | MEDIUM | Headless Chromium automation |
| Code exec | `code_exec.py` | MEDIUM | Run Python (30s timeout) |
| Shell | `shell.py` | MEDIUM | System commands (20s timeout) |
| Git | `git_tool.py` | MEDIUM | Structured git ops (status, diff, log, branch, commit, etc.) |
| Process | `process_tool.py` | MEDIUM | Long-running process management (start, stop, restart, logs) |
| Memory | `memory_tool.py` | LOW | Persistent semantic memory |
| Sysinfo | `sysinfo.py` | LOW | Hardware + time (offline, <100ms) |
| Installed programs | `installed_programs.py` | LOW | List installed apps (Windows/Linux/macOS) |

### Storage Layer
- **SQLite** (`storage/db.py`) — session history, conversation logs. File-based, zero config.
- **sqlite-vec** (`storage/vector.py`) — cross-session semantic memory. Local vector store. Replaced ChromaDB (which was used in earlier versions).

### Adapter Layer
Translates core engine calls into runtime-specific API calls. One file per runtime. The engine calls `BaseAdapter.chat()` — it never talks to Ollama directly.

```
adapters/
  base.py            ← interface all adapters implement
  ollama.py          ← wraps Ollama OpenAI-compatible API
  openai_compat.py   ← composable adapter for OpenAI/Anthropic/OpenRouter/LiteLLM
```

## Request Flow

```
User message
     │
     ▼
Safety Gate          check(message)
     │
     ▼
Load History         SessionStore.load(session_id)
     │
     ▼
ThinkingDispatcher   classify(message, has_attachment) → OrchestrationPlan
     │                = TaskProfile (capabilities) + ExecutionGraph (DAG)
     ▼
Execute              DIRECT | SINGLE_TOOL | MULTI_TOOL | AGENT_LOOP | MULTI_PHASE
     │
     ▼
Context Builder      build(context, model_context_window)
     │                = system + memory + tool_result + file + history
     ▼
Adapter              POST /v1/chat/completions (streaming)
     │
     ▼
Response Assembler   yield StreamChunk → SSE → UI
     │
     ▼
Post-Processing      memory persistence + observability + metrics
                     + secondary intent handling + reflection
```

## Directory Structure

```
LocalMind/
├── backend/                   Backend (Python 3.10+)
│   ├── src/
│   │   ├── core/              Core engine
│   │   │   ├── config.py      Pydantic settings (from .env)
│   │   │   ├── models.py      Shared data models (TaskProfile, OrchestrationPlan, Intent, etc.)
│   │   │   ├── context_builder.py  Prompt assembly + token management
│   │   │   ├── thinking_dispatcher.py  LLM-based capability inference (sole router)
│   │   │   ├── execution_graph.py  DAG-based parallel capability execution
│   │   │   ├── safety_gate.py Input safety screening
│   │   │   ├── flywheel.py    Routing outcome learning
│   │   │   ├── metrics.py     p50/p95 latency + tool success rates
│   │   │   ├── memory.py      Memory composer
│   │   │   ├── knowledge_writer.py  Auto-updates localmind.md at startup
│   │   │   ├── engine/        Main orchestrator (split into mixins)
│   │   │   │   ├── __init__.py
│   │   │   │   ├── _pipeline.py    Main pipeline (6 layers)
│   │   │   │   ├── _helpers.py
│   │   │   │   ├── _memory_mixin.py
│   │   │   │   ├── _persistence_mixin.py
│   │   │   │   └── _reflection_mixin.py
│   │   │   ├── agent/         Agent loop (multi-turn tool calling)
│   │   │   │   ├── loop.py         AgentLoop
│   │   │   │   ├── orchestrator.py AgentOrchestrator
│   │   │   │   ├── delegation.py  Parent/child run context and delegation contracts
│   │   │   │   ├── prompts.py      Agent system prompt builder
│   │   │   │   ├── tool_dispatch.py Tool dispatch with retry
│   │   │   │   ├── synthesizer.py  Multi-source synthesis
│   │   │   │   └── constants.py    Agent config constants
│   │   │   ├── workspace/     Workspace orchestration
│   │   │   │   ├── manager.py
│   │   │   │   └── orchestrator.py
│   │   │   └── prompts/       Prompt template files
│   │   │       ├── base.md    Base personality prompt
│   │   │       ├── chat.md    Chat intent prompt
│   │   │       ├── skills/    Skill .md files (coding, debugging, research, etc.)
│   │   │       └── *.md       Per-intent prompt fragments
│   │   │
│   │   ├── agents/            8-agent registry (ADR-6)
│   │   │   ├── base_agent.py   BaseAgent abstract class + AgentConfig
│   │   │   ├── registry.py     Agent discovery + registration
│   │   │   ├── selection.py    Intent → agent name → agent class routing
│   │   │   ├── coding/         CodingAgent (shell, file, code_exec, git, process)
│   │   │   ├── research/       ResearchAgent (web_search, web_fetch)
│   │   │   ├── browser/        BrowserAgent (headless browser)
│   │   │   ├── direct/         DirectAgent (no tools, single call)
│   │   │   ├── verifier/       VerifierAgent (tests, bug reproduction)
│   │   │   ├── reviewer/       ReviewerAgent (code quality, spec conformance)
│   │   │   ├── debugger/       DebuggerAgent (root cause diagnosis)
│   │   │   └── analyst/        AnalystAgent (requirements analysis)
│   │   │
│   │   ├── tools/             Tool modules (15 tools — see table above)
│   │   ├── adapters/          Model runtime adapters (Ollama, OpenAI-compat)
│   │   ├── api/               FastAPI application
│   │   │   ├── app.py         App factory + CORS + static + lifespan
│   │   │   └── routes/        13 route files (chat, sessions, models, health, etc.)
│   │   ├── storage/           Persistence layer
│   │   │   ├── db.py          SQLite session store
│   │   │   └── vector.py      sqlite-vec vector store
│   │   └── cli/               Command-line interface (Typer)
│   ├── server.py              Entry point
│   └── pyproject.toml         Python deps + ruff/pytest/mypy config
│
├── frontend/                  React 19 + Vite 6 + Tailwind 4 + shadcn/ui
│   ├── src/
│   │   ├── App.tsx
│   │   ├── main.tsx
│   │   ├── components/
│   │   │   ├── chat/          ChatInput, ChatMessage, ThinkingBlock, ToolSteps
│   │   │   ├── layout/        CenterPanel, LeftPanel, RightPanel, WorkspaceLayout
│   │   │   ├── panels/        ActionHistory, FileExplorer, MemoryTab, ObservabilityTab, etc.
│   │   │   ├── shared/        DiffBlock, ModelSelector, SettingsModal
│   │   │   └── ui/            57 shadcn/ui primitives (Radix-based — do not edit directly)
│   │   ├── hooks/             useLocalMind, use-mobile, use-toast
│   │   ├── lib/               API client, utilities
│   │   └── types/             TypeScript type definitions
│   ├── eslint.config.js       ESLint flat config
│   ├── tailwind.config.ts     Tailwind config (dark mode: class strategy)
│   ├── tsconfig.json
│   └── package.json
│
├── electron/                  Electron desktop wrapper
│   ├── main.js
│   ├── preload.js
│   ├── tray-icon.js
│   └── package.json
│
├── tests/                     pytest suite (194 tests)
│   ├── conftest.py            Shared fixtures
│   ├── core/                  Engine, agent, context builder tests
│   ├── tools/                 Tool unit tests
│   ├── adapters/              Adapter tests (mocked)
│   ├── api/                   FastAPI integration tests
│   └── storage/               DB and vector store tests
│
├── docs/                      Architecture, PRD, analysis docs
├── scripts/                   Demo, janitor, seed, reset, dev-backend scripts
├── localmind.md               Auto-updated system knowledge reference
├── CONTRIBUTING.md
├── REVIEW.md                  Agent review findings
└── LICENSE
```

## Design Principles

1. **One direction of dependency** — surfaces → engine → tools/adapter. Never upward.
2. **Tools are isolated** — each tool is a self-contained module. No shared state.
3. **No framework lock-in** — no LangChain. Plain Python. Readable in one hour.
4. **Local by default** — no data leaves the machine except web search (opt-in).
5. **Adapter pattern** — switching from Ollama to LM Studio = one new file.
6. **Confirmations for writes** — file writer requires explicit user confirmation, enforced in the tool.
7. **ThinkingDispatcher is the sole router** — no regex classifier. LLM capability inference handles all routing, including EPL-style queries and SYSINFO detection.

## Extension Points

### Add a new tool
1. Create `tools/my_tool.py` with `async def run(input_data, context) -> ToolResult`
2. Register in `tools/__init__.py` with an intent mapping
3. Write tests in `tests/tools/test_my_tool.py`

### Add a new adapter
1. Create `adapters/my_runtime.py` subclassing `BaseAdapter`
2. Register in `adapters/__init__.py`
3. Set `LOCALMIND_ADAPTER=my_runtime` in `.env`

### Add a new surface
Call `Engine.process(message, session_id, file=...)` and handle the `StreamChunk` iterator. The engine has no knowledge of how the response is rendered.
