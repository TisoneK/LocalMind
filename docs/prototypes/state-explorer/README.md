# State Explorer — prototype UI for the state-driven engine

The state engine (`backend/src/core/state_engine/`, ADR-71) is not a chat: it holds a state, fans out candidate
moves, really probes the read-only ones, keeps the best and backtracks from dead ends. Its natural picture is a
**game tree**, not a transcript — so this surface is built around that.

Open `index.html` (serve the folder: `python3 -m http.server 5199` here). It replays four REAL runs captured from
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

Next: a React surface in the app that streams the same events over SSE (backlog `B-2026-09-21-19`).
