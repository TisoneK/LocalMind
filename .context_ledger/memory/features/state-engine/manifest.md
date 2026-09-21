# Feature: state-engine

Goal: a state-driven agent engine built BESIDE the classic parent (ADR-71 in
`history/office-002/plans/decisions.md`) — a goal is treated as a sequence of
state transitions (goal → state → candidate moves → simulate → evaluate →
apply → new state), the ENGINE owns the state, and the model has exactly two
jobs: propose candidate moves and score outcomes. Owner direction: "like
chess", and the engine's interface should be its own geeky, advanced surface —
not a chat pane. Engine and model are independent axes; users pick the engine.

**Started:** 2026-09-21 (the office-002 state-engine slice)
**Status:** ACTIVE — slice 1 + the served explorer are live on main; the in-app
explorer and the Classic/State engine selector are the current work.

## Shipped (on main)

- **Slice 1 — the engine package** `backend/src/core/state_engine/` (state,
  catalog, executor, LLM proposer/evaluator, search loop, `python -m
  core.state_engine`): immutable `AgentState` rebuilt from real observations,
  compact rendering with no chat history, per-move fingerprints so a failed
  move is never re-proposed, beam-of-one with backtracking (the entry move into
  a dead end is pruned), a hard budget with an honest `stopped` that says the
  goal is NOT settled, and read-only by construction — a tool not marked
  read-only is surfaced as `needs_confirmation` instead of executed. Live on
  deepseek-chat: a folder question in 2 model calls; a README/stack goal in 4
  (correct: React 19). Two live flaws found and fixed: the evaluator saw only
  900 chars (hid the answer in a long listing → wrongly stopped) and
  backtracking without pruning re-took the same dead end.
- **The event contract** enriched for the UI: `seq`, run clock, tree ids
  (`node`/`parent`/`at`), fingerprints, observation excerpts, probe ms,
  reasons, goal — plus a `--json` CLI.
- **The State Explorer page** — `GET /state-explorer` (page),
  `GET /api/state-engine/info`, `POST /api/state-engine/run` (SSE: `meta` then
  every `EngineEvent`; disconnect cancels; errors arrive as a `stopped`
  event), registered in `api/app.py`. `backend/src/api/static/state-explorer/`
  is the served copy written by `build.py`; no npm/build step, so it also runs
  on Windows. Tests: `tests/api/test_state_engine_routes.py`.
- **The prototype** `docs/prototypes/state-explorer/` — a self-contained
  game-tree UI (tree canvas, PGN-style move list, eval bar, inspector, meters,
  rewindable timeline, keyboard nav, light/dark) replaying four real captured
  runs.

## Next

- The React port inside the app and the Classic/State engine selector setting
  (in flight), then slice 2: write-capable moves behind the ADR-67
  confirmation with model-PREDICTED outcomes, beam > 1, persisted state,
  tree visualization from `EngineEvent`s, and a per-provider concurrency budget
  before parallel probes. Backlog rows B-2026-09-21-2/-3/-4.
