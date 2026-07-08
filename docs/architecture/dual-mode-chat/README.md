# Dual-Mode Chat — Architecture Reference

Feature requested: toggle between **Agent Mode** (full pipeline) and **Direct Mode**
(fast, raw Ollama stream with memory context but no tool routing).

| File | Covers |
|---|---|
| [01-overview.md](01-overview.md) | What the two modes are, why they exist, request flow comparison |
| [02-backend.md](02-backend.md) | `Engine.process_direct()`, route branching, API contract |
| [03-frontend.md](03-frontend.md) | Mode state, toggle UI, `api.js` changes |
| [04-tasks.md](04-tasks.md) | Implementation task list (ordered, self-contained) |

## Governing principle

Direct mode is not a stripped-down agent mode — it is a separate code path that
intentionally skips classification, tool dispatch, and agent loop. History load
and memory retrieval are retained so the model stays contextually aware.
