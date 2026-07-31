# LocalMind — Product Requirements

## Problem

Local AI models running through Ollama hit two walls immediately:
- **Stale knowledge** — training cutoff 2023+, no current information
- **No file access** — models cannot read PDFs, code, or documents

These are infrastructure problems, not model quality problems.

## Vision

An open-source tool-use and retrieval layer that wraps any Ollama model and makes it behave like a capable AI assistant. Free, local, private, forever.

> "The goal is not to match frontier model intelligence. It is to give local models the same infrastructure that frontier models rely on."

## Target Users

| User | Need |
|---|---|
| Developer | Local AI that fits into existing workflow — code review, file ops, automation |
| Non-technical user | Simple chat UI that reads documents, no setup required |
| Student / researcher | Free alternative to ChatGPT that reads papers |

## Core Capabilities

| # | Capability | Status |
|---|---|---|
| 1 | File reading (PDF, DOCX, TXT, CSV, code) | v0.1 |
| 2 | Web search (DuckDuckGo / Brave) | v0.2 |
| 3 | Cross-session memory (SQLite + sqlite-vec) | v0.3 |
| 4 | CLI + scripting support | v0.4 |
| 5 | Code execution (sandboxed Python + JS) | v0.5 |
| 6 | File writing (with confirmation UX) | v0.5 |
| 7 | Git operations (status, diff, log, commit, etc.) | v0.6 |
| 8 | Process management (start, stop, restart, logs) | v0.6 |
| 9 | 8-agent registry (browser, coding, research, direct, verifier, reviewer, debugger, analyst) | v0.6 |

## Agent Registry (v0.6)

LocalMind uses a multi-agent architecture (ADR-6) with per-agent scoped toolsets.
Each agent is a thin `BaseAgent` subclass with its own context builder, scoped
tools, and stop condition. The registry auto-discovers agents from the
`agents/<name>/` directory structure (ADR-8 Principle 5).

| Agent | Tools | Role |
|---|---|---|
| Browser | browse | Drive a headless browser |
| Coding | shell, file_task, file_write, edit_file, code_exec, git, process, delegate | Build, edit, and manage code |
| Research | web_search, web_fetch, delegate | Search and fetch web content |
| Direct | (none) | Single model call, no tools |
| Verifier | shell, process, git, file_task, edit_file, delegate | Run tests, reproduce bugs, validate |
| Reviewer | file_task, git, shell, delegate | Assess code quality and spec conformance |
| Debugger | file_task, git, shell, process, delegate | Isolate failures, find root causes |
| Analyst | file_task, git, delegate | Clarify requirements, analyze specs |

## Non-Goals

- Replacing frontier model intelligence
- Another generic Ollama chat UI
- Cloud service or SaaS
- Fine-tuning or modifying models

## Architecture Reference

See [ARCHITECTURE.md](ARCHITECTURE.md).

## Roadmap

### v0.1 — File Reading MVP
**Acceptance criteria:** User opens Web UI, uploads a PDF, asks a question, gets an accurate answer sourced from the document. Runs fully locally, no internet required.

Tasks:
1. FastAPI project structure per ARCHITECTURE.md
2. Ollama adapter — wrap `/v1/chat/completions`, handle streaming
3. File reader tool — parse PDF/DOCX/TXT, chunk by token count
4. Context builder — system prompt + file chunks + history, respect context window
5. React UI — file upload, chat input, streaming response
6. Wire FastAPI routes — `POST /api/chat` with optional file
7. pytest tests for file_reader and context_builder
8. README with install and run instructions

### v0.2 — Web Search
- DuckDuckGo search tool
- Auto-trigger on time-sensitive queries
- Source citation in responses

### v0.3 — Memory
- Session history persistence (SQLite — already scaffolded)
- Cross-session fact store (ChromaDB — already scaffolded)
- Memory viewer in UI

### v0.4 — CLI
- `localmind ask`, `localmind chat`, `localmind start`
- Pipe support: `cat report.pdf | localmind ask "summarise"`
- Config file (YAML)

### v0.5 — Code Execution + File Write
- Sandboxed Python/JS execution
- File write with confirmation UX
- Diff preview for edits

## Competitive Position

| Tool | File Read | Web Search | Code Exec | Lightweight |
|---|---|---|---|---|
| Open WebUI | ✓ | ✗ | ✗ | ✗ Heavy |
| AnythingLLM | ✓ | ✓ | ✗ | ✗ Complex |
| Msty | ✗ | ✗ | ✗ | ✓ |
| **LocalMind** | ✓ | ✓ | ✓ | ✓ |

### v0.6 — Agent Architecture + Diagnostics
- 8-agent registry with per-agent scoped toolsets (ADR-6)
- Structured Git tool (status, diff, log, branch, commit, etc.)
- Process management tool (start, stop, restart, logs, wait)
- Agent delegation via `delegate` tool (ADR-8 Phase 3)
- workspace_state feedback loop (git diff after every turn)

## Model Profiles

| Profile (UI label) | Model | Min RAM |
|---|---|---|
| Fast & Light | llama3.2:3b | 4 GB |
| Balanced | llama3.1:8b | 6 GB |
| Best for Code | qwen2.5-coder:7b | 6 GB |
| High Quality | deepseek-coder-v2:16b | 12 GB |
| Writing Focused | mistral:7b | 6 GB |
