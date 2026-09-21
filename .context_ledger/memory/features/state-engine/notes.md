# Notes: state-engine (append-only while alive)

## 2026-09-21 — the slice-1 session (carried in from office-002)

- The engine was built beside the parent on purpose, importing only stable
  capabilities (model adapters, tool dispatcher, `ToolResult`) — the parent
  stays untouched, so the old engine can be retired if the new one proves
  better. Do not let it reach into the parent loop for convenience.
- Live runs, not unit tests, found the two slice-1 flaws that mattered: an
  evaluator view too small to see the answer (it scored every outcome 0 and
  wrongly stopped) and backtracking that re-took the same dead end without
  pruning the entry move. Keep the evaluator's view of a tool result large
  enough to contain the answer.
- `EngineEvent`s are the UI contract and they never carry hidden reasoning —
  that constraint is what makes the explorer honest, and it is worth keeping
  when the record grows.
- The page is deliberately build-free (static files under
  `backend/src/api/static/state-explorer/`, written by `build.py`) so it can be
  opened on the owner's Windows machine; resist making it depend on the Vite
  build.

## 2026-09-21 — office close, opening the next office (Mosi)

- Office-002 was closed eight sessions past `office_size`; the close itself is
  cheap and mechanical (`ledger-history close --confirm` freezes the office
  verbatim and opens a fresh one). The cost is entirely in the re-seed — the
  permanent record and the actionable backlog rows — so budget for that, not
  for the freeze.
- The office was closed with product work in flight and uncommitted in the
  working tree (the in-app explorer + engine selector). The closing commit
  staged only `.context_ledger/` paths explicitly; the product work was left
  exactly as found, for the session that owns it.
