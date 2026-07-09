# LocalMind

**A local AI runtime that gives Ollama models real tools — file reading, code execution, shell access, web search, persistent memory, and browser automation. Everything runs on your machine. No data leaves your device.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![React 19](https://img.shields.io/badge/React-19-61dafb.svg)](https://react.dev/)

---

## What LocalMind Does

LocalMind wraps local LLMs (via [Ollama](https://ollama.com)) in a FastAPI server and gives them capabilities that generic chat models don't have:

- **Persistent semantic memory** — tell it "remember that..." and it recalls the fact in future sessions automatically, powered by sqlite-vec + nomic-embed-text embeddings.
- **Real-time web search** — DuckDuckGo + SearXNG race in parallel for low latency, with Brave as a premium fallback.
- **File reading** — PDF, DOCX, CSV, XLSX, code files, and images (OCR via pytesseract if installed). Up to 50 MB.
- **File writing** — create and save scripts, documents, or any text content directly to disk (with explicit permission gating).
- **Python code execution** — run real Python and see real output, not a guess. 30-second timeout, 4000-char output cap.
- **Shell access** — list files, check disk space, run git commands, and more. 20-second timeout.
- **Browser automation** — navigate, click, fill forms, scroll, screenshot, and execute JavaScript on real web pages via headless Chromium.
- **System info** — current time, date, OS, CPU, RAM, and disk — instant and accurate, fully offline.

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| [Ollama](https://ollama.com) | latest | Must be running at `http://localhost:11434`. Pull a model (`ollama pull llama3.1:8b`) and the embed model (`ollama pull nomic-embed-text`). |
| Python | 3.10+ | Backend server. |
| Node.js | 18+ | Frontend + Electron. |
| npm | 9+ | Comes with Node.js. |

**OS support:** Developed on Windows; works on macOS and Linux with minor path adjustments (see [Known Issues](#known-issues)).

## Quick Start

### 1. Clone

```bash
git clone https://github.com/TisoneK/LocalMind.git
cd LocalMind
```

### 2. Install Ollama models

```bash
ollama pull llama3.1:8b          # chat model (or any 7B+ model)
ollama pull nomic-embed-text     # required for memory
```

### 3. Install backend dependencies

```bash
cd backend
python -m venv .venv

# Activate the venv:
#   Windows:  .venv\Scripts\activate
#   macOS/Linux:  source .venv/bin/activate

pip install -e ".[dev]"
cd ..
```

### 4. Install frontend + Electron dependencies

```bash
npm install
```

### 5. Run everything

```bash
npm run dev:full
```

This starts three processes concurrently:
- **Backend** — FastAPI on `http://localhost:8000`
- **Frontend** — Vite dev server on `http://localhost:3000`
- **Electron** — desktop wrapper that loads the frontend

The first run may take a few seconds while Ollama loads the model into memory.

### Run individual pieces

| Command | What it does |
|---|---|
| `npm run dev:backend` | Backend only (FastAPI on :8000). **Note:** the default script uses a Windows venv path — see [Known Issues](#known-issues) for macOS/Linux. |
| `npm run dev:frontend` | Frontend only (Vite on :3000). |
| `npm run dev:electron` | Electron only (expects backend + frontend already running). |
| `npm run build` | Production build of frontend + Electron. |

## Architecture

LocalMind is a layered system. Each layer has one responsibility and communicates only with adjacent layers.

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
│                 CORE ENGINE                        │
│   ThinkingDispatcher → Tool Dispatcher → Context  │
│                   Builder → Response Assembler     │
└──────┬──────────────┬────────────┬───────────────┘
       │              │            │
┌──────▼──────┐ ┌─────▼─────┐ ┌───▼──────────────┐
│ TOOL        │ │ STORAGE   │ │ ADAPTER           │
│ REGISTRY    │ │ SQLite +  │ │ Ollama            │
│ 13 tools    │ │ sqlite-vec│ │ OpenAI-compat     │
└─────────────┘ └───────────┘ └──────────────────┘
```

**Design principles:**
1. **One direction of dependency** — surfaces → engine → tools/adapter. Never upward.
2. **Tools are isolated** — each tool is a self-contained module. No shared state. A broken tool cannot crash the engine.
3. **No framework lock-in** — no LangChain. Plain Python. Readable in one hour.
4. **Local by default** — no data leaves the machine except web search (opt-in).
5. **Adapter pattern** — switching from Ollama to another runtime = one new file.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full architecture reference.

## Tools

LocalMind ships with 13 tools. Each is a self-contained Python module in `backend/src/tools/`.

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
| Memory | `memory_tool.py` | LOW | Persistent semantic memory |
| Sysinfo | `sysinfo.py` | LOW | Hardware + time (offline, <100ms) |
| Installed programs | `installed_programs.py` | LOW | List installed apps (Windows) |

See [`localmind.md`](localmind.md) for the auto-generated system knowledge reference (updated at server startup).

## Configuration

All runtime config is loaded from a `.env` file in the `backend/` directory (gitignored). Defaults are defined in [`backend/src/core/config.py`](backend/src/core/config.py).

Key settings:

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API URL |
| `OLLAMA_MODEL` | _(empty = auto-detect)_ | Chat model to use |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Embedding model for memory |
| `LOCALMIND_CODE_EXEC_ENABLED` | `true` | Enable Python code execution tool |
| `LOCALMIND_SHELL_ENABLED` | `true` | Enable shell command tool |
| `LOCALMIND_MAX_FILE_SIZE_MB` | `50` | Max upload file size |
| `LOCALMIND_CODE_EXEC_TIMEOUT` | `30` | Code execution timeout (seconds) |
| `LOCALMIND_SHELL_TIMEOUT` | `20` | Shell command timeout (seconds) |
| `BRAVE_SEARCH_API_KEY` | _(empty)_ | Optional Brave search API key |

## Project Structure

```
LocalMind/
├── backend/                 FastAPI server (Python 3.10+)
│   ├── src/
│   │   ├── core/            Engine, agent loop, context, memory, metrics
│   │   ├── tools/           13 tool modules
│   │   ├── adapters/        Ollama + OpenAI-compatible adapters
│   │   ├── api/routes/      13 API route files
│   │   ├── storage/         SQLite + sqlite-vec persistence
│   │   └── cli/             Typer CLI
│   ├── server.py            Entry point
│   └── pyproject.toml       Python deps + ruff/pytest config
├── frontend/                React 19 + Vite 6 + Tailwind 4 + shadcn/ui
│   ├── src/
│   │   ├── components/      chat/, layout/, panels/, shared/, ui/
│   │   ├── hooks/           Custom React hooks
│   │   └── lib/             API client, utilities
│   └── package.json
├── electron/                Electron desktop wrapper
│   ├── main.js
│   ├── preload.js
│   └── tray-icon.js
├── tests/                   pytest suite
├── docs/                    Architecture, PRD, analysis docs
├── scripts/                 Demo, janitor, seed, reset scripts
├── localmind.md             Auto-updated system knowledge reference
├── CONTRIBUTING.md
└── LICENSE
```

## Development

### Backend

```bash
cd backend
source .venv/bin/activate        # or .venv\Scripts\activate on Windows

ruff check .                     # lint
pytest ../tests                  # tests
mypy src                         # type check
python server.py                 # run server
```

### Frontend

```bash
npm run dev:frontend             # dev server on :3000
npm run build                    # production build (runs tsc + vite build)
```

### Adding a new tool

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the full guide. Summary:

1. Create `backend/src/tools/my_tool.py` with `async def run(input, context) -> ToolResult`
2. Register in `backend/src/tools/__init__.py` with an intent mapping
3. Write tests in `tests/tools/test_my_tool.py`

## Known Issues

- **`npm run dev:backend` uses a Windows-only venv path** (`.venv\Scripts\python.exe`). On macOS/Linux, run the backend directly: `cd backend && .venv/bin/python server.py`. Tracked as H4 in [`REVIEW.md`](REVIEW.md).
- **Code execution is not sandboxed** — trusted-user only. The Python tool runs with your user's full permissions.
- **Small models (1B–3B params) have limited reasoning** — upgrade to 7B+ for complex tasks.
- **nomic-embed-text must be pulled** for memory to work: `ollama pull nomic-embed-text`.

## Contributing

Contributions are welcome. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for code standards, the pull request process, and how to add new tools, adapters, or surfaces.

## License

[MIT](LICENSE) © Tisone Kironget
