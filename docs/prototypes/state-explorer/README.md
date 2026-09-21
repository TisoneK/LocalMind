# State Explorer — prototype UI for the state-driven engine

The state engine (`backend/src/core/state_engine/`, ADR-71) is not a chat: it holds a state, fans out candidate
moves, really probes the read-only ones, keeps the best and backtracks from dead ends. Its natural picture is a
**game tree**, not a transcript — so this surface is built around that.

**Play with it live (Windows, macOS, Linux — no npm, no build):** start LocalMind's backend as usual and open
**http://localhost:8000/state-explorer**. Type a goal ("how many entries are in my Downloads folder?", "find the README
in ~/Code/x and name its framework"), press *run live*, and watch the tree grow. It uses whatever provider and model
LocalMind is set to. The engine is read-only: it can list, read, search the web and do arithmetic, never write or run
commands. Stop cancels the run. (The page and route are `backend/src/api/routes/state_engine.py`; the served copy is
`backend/src/api/static/state-explorer/index.html`, written by `build.py`.)

The page also opens standalone (`index.html`, or `python3 -m http.server 5199` in this folder) as a replay-only demo. It replays four REAL runs captured from
the engine on deepseek-chat (home path replaced with `~`): a two-step success, a dead end with a backtrack and an
honest stop, a fast one, and an unanswerable question that stops immediately.

| Region | What it shows |
|---|---|
| Tree canvas | states (violet) → candidate moves (cards) → next state; **green** = chosen path, ✕ red = failed probe, dashed = pruned branch, dashed amber arc = backtrack, ghost cards with `show unrevealed` |
| Move list (left) | PGN-style: `1. move ✓ progress`, `↩ backtrack`, `✔ settled` / `⛔ not settled`; click to jump |
| Eval bar | best progress reached so far, chess-style |
| Inspector (right) | the selected move or state: fingerprint, tool, why, probe outcome, score, the REAL observation excerpt |
| Meters | model calls, depth, backtracks against the budget; probes, elapsed, ply |
| Timeline | every event ticked by kind on the run clock; drag to rewind/replay ("rollback" is literal) |

Keys: `Space` play · `←/→` step · `Home/End` · `1‑9` run · `F` ghost · `0` fit · `+/-` zoom · `?` help.
It never shows hidden reasoning — only states, moves and outcomes.

- `template.html` — the page; `build.py` — inlines captured runs into `index.html`.
- Capture: `cd backend && PYTHONPATH=src .venv/bin/python -m core.state_engine --json "<goal>" > run.jsonl`
- The event fields the live UI will consume are `EngineEvent.to_dict()` in `core/state_engine/search.py`
  (`seq`, `t_ms`, `kind`, tree ids `node`/`parent`/`at`, `fp`, `excerpt`, `ms`, `reason`).

Next: a React surface inside the app (backlog `B-2026-09-21-19`); the route and event stream it needs now exist.
