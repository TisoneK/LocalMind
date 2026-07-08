# 01 — System Overview

## Layer map

```
┌──────────────────────────────────────────────────────┐
│                      SURFACE                          │
│           Web UI (React/Vite)  │  CLI (Typer)         │
└───────────────┬────────────────┴──────┬───────────────┘
                │                       │
┌───────────────▼───────────────────────▼───────────────┐
│                     API LAYER                          │
│             FastAPI  ·  SSE streaming                  │
└─────────────────────────┬──────────────────────────────┘
                           │
┌─────────────────────────▼──────────────────────────────┐
│                    CORE ENGINE                          │
│                                                         │
│   Intent Router → Workspace Orchestrator                │
│        │                  │                             │
│        │          Plan → Dispatch → Synthesise          │
│        │                  │                             │
│        └──────────────────▼                             │
│                   Tool Dispatcher                       │
└──────┬──────────────┬──────────────┬────────────────────┘
       │              │              │
┌──────▼──────┐ ┌─────▼──────┐ ┌────▼───────────────────┐
│   TOOLS     │ │  STORAGE   │ │  ADAPTER               │
│             │ │            │ │                         │
│ file_reader │ │ SQLite     │ │ Ollama (localhost)      │
│ file_writer │ │ sqlite-vec │ │ BaseAdapter interface   │
│ web_search  │ │            │ │ # future: lmstudio,    │
│ code_exec   │ └────────────┘ │           llamacpp      │
│ shell       │                └─────────────────────────┘
│ sysinfo     │
│ memory_op   │
└─────────────┘
```

## Dependency direction

One direction only — no upward calls, no circular imports:

```
surfaces → api → core → tools / storage / adapter
```

A tool never calls the engine. The engine never calls the API. The adapter
never calls a tool. Violating this rule is an architectural defect, not a
shortcut.

## Request flow

```
User message
     │
     ▼
Intent Router          classify(message) → Intent enum
     │
     ▼
Workspace Orchestrator
     │
     ├─ 1. Plan   — LLM produces structured task list (tool + typed input)
     │
     ├─ 2. Dispatch loop
     │        │
     │        ├─ Contract validation (hard reject on schema mismatch)
     │        ├─ Tool execution (contract.execute(payload))
     │        └─ Write result to CONTEXT.md
     │
     └─ 3. Synthesise — LLM reads CONTEXT.md → final answer → SSE stream
                │
                ▼
          SessionStore   append(session_id, message + response)
```

## Directory structure

```
localmind/
│
├── core/                       Central engine
│   ├── config.py               Pydantic settings (env / .env)
│   ├── models.py               Shared data models (Intent, ToolResult, …)
│   ├── engine.py               Main turn coordinator
│   ├── intent_router.py        Message → Intent classification
│   ├── intent_router_v2.py     Semantic router (production path)
│   ├── context_builder.py      Prompt assembly + token budgeting
│   ├── agent/                  Multi-step agent loop
│   └── workspace/
│       ├── manager.py          Per-turn scratch files (TODO.md, CONTEXT.md)
│       └── orchestrator.py     Plan → dispatch → synthesise loop
│
├── tools/                      Tool modules
│   ├── __init__.py             Registry + dispatcher
│   ├── base.py                 ToolResult, RiskLevel
│   ├── contracts/
│   │   ├── base.py             ToolContract ABC + ToolRegistry
│   │   └── schemas.py          Per-tool schemas + contract classes
│   ├── file_reader.py          PDF/DOCX/TXT/CSV/image parsing
│   ├── file_writer.py          Safe-write + scratch + copy-back
│   ├── web_search.py           DuckDuckGo / Brave / SearXNG
│   ├── shell.py                OS shell actions (Phase 3 contract)
│   ├── sysinfo.py              RAM, CPU, OS, battery readings
│   ├── memory.py               Vector memory read/write
│   ├── memory_tool.py          Memory tool entry point
│   ├── code_exec.py            Code execution entry point
│   └── code_executor/
│       ├── detector.py         Language detection
│       ├── runner.py           Execution entry point
│       └── sandbox.py          Subprocess isolation
│
├── adapters/                   Model runtime adapters
│   ├── base.py                 BaseAdapter interface
│   └── ollama.py               Ollama OpenAI-compat wrapper
│
├── api/                        FastAPI application
│   ├── app.py                  Factory + CORS + static
│   └── routes/                 One file per resource
│
├── storage/                    Persistence
│   ├── db.py                   SQLite session + tool stats
│   ├── vector.py               sqlite-vec semantic memory
│   └── migrations/             Numbered SQL migrations
│
├── cli/                        Typer CLI
│   └── commands/               One file per command
│
├── ui/                         React/Vite frontend
│   └── src/
│       ├── pages/
│       ├── components/
│       ├── hooks/
│       └── lib/
│
├── tests/                      pytest suite (mirrors source tree)
├── scripts/                    Dev/ops utilities
└── docs/
    ├── ARCHITECTURE.md         Legacy overview (kept for reference)
    └── architecture/           ← this folder (authoritative)
```

## Design principles

1. **One direction of dependency** — surfaces → engine → tools/adapter. Never upward.
2. **Contract before execution** — every tool payload is validated against a typed
   schema before any I/O runs. Hard reject on mismatch, no fallback.
3. **No silent redirects** — if a path, tool, or intent cannot be resolved
   confidently, surface an error. Never guess and proceed quietly.
4. **Scratch before final** — all file writes land in `~/LocalMind/` first.
   Copy-back to the user's destination happens after, with version-control
   semantics for document formats.
5. **Local by default** — no data leaves the machine except web search (opt-in).
6. **No framework lock-in** — no LangChain. Plain Python. Readable in one hour.
7. **Adapter pattern** — switching model runtimes = one new file in `adapters/`.
