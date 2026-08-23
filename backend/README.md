# LocalMind — backend

The FastAPI backend that powers LocalMind: the local AI runtime that gives
Ollama (and cloud-compatible) models real tools — file reading/writing,
code execution, shell access, web search, persistent memory, and browser
automation.

This is a monorepo: the full project README (setup, Quick Start, architecture,
configuration) lives at the repository root: [`../README.md`](../README.md),
and the Python package's metadata points here so both `pip install -e .` and
published wheels resolve a readme inside the package directory.

## Development

```bash
# from this directory, with a virtualenv active:
pip install -e ".[dev]"

ruff check .
pytest ../tests
mypy src
python server.py
```

## Structure

- `src/core/` — engine, agent loop, context, memory, metrics
- `src/tools/` — tool modules (file, shell, code exec, web, memory, …)
- `src/adapters/` — Ollama + OpenAI-compatible adapters
- `src/api/` — FastAPI routes
- `src/storage/` — SQLite + sqlite-vec persistence
- `src/cli/` — Typer CLI