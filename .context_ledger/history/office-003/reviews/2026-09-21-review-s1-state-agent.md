# The state engine gets its own architecture, and the Explorer becomes an instrument

Report for the session that closed office-002 and continued the state-driven engine. Written for the owner.

## What happened

The office had been eight sessions past its size limit, so the first work was the door: the vendored core
was updated to 2.0.3, I checked in, and I ran the office close the protocol had been waiting for. Office-002
is frozen verbatim in `history/office-002/` with a permanent record of what it achieved, the decisions still
in force, and the open threads; the fresh office carries only actionable work (24 rows) and four still-open
protocol traps. Closing also surfaced a packaging flaw (the core templates ship eight office files
executable, so every close injects mode churn) — logged, and fixed here.

Then the engine. Three things shipped:

1. **It is selectable.** Settings → Agent → Agent engine offers Classic (the parent agent, still the default)
   or State. Choosing State replaces the centre of the app with the State Explorer.
2. **The Explorer is an instrument, not a viewer.** You can set how hard the engine searches (depth,
   branches, model calls, backtracks — the defaults and limits come from the backend, not from hard-coded
   numbers in the UI), read a big tree one layer at a time or as the chosen path only, keep every run across
   reloads, compare two runs on the numbers that matter, read a state's *actual* content (the facts it
   learned, the actions it ruled out, the path that reached it, what the run had spent), and take the
   evidence out as JSON or as a Markdown summary.
3. **It stopped being a LocalMind feature.** Following your direction, the engine now lives in its own
   package with no knowledge of LocalMind: contracts for an environment, a simulator, a proposer, an
   evaluator, a model port and terminal conditions; the state, the loop and the model's two jobs behind
   them. Everything LocalMind-specific — its read-only tools, its tool dispatcher, its provider adapters,
   the web route, the CLI — sits in one adapter file. A test fails the build if the engine ever imports
   back into the host. A CLI, an IDE, a browser or a standalone app is now another adapter file, not a
   rewrite. The engine has its own README explaining the concepts and what writing an adapter takes.

A real bug fell out of making the state readable: a failed probe was only remembered as failed when the
engine backtracked, so an action that failed could be proposed again after a round that succeeded. It is
fixed, with a test that would have caught it.

## What was verified, and how

Live, on the isolated 8765 stack with deepseek/deepseek-chat (never port 8000, never your home): a real goal
ran through the refactored engine and the adapter — the budget sent from the UI path was honoured in the
run's meta event, three tools were really probed (5ms, 0ms, 1ms), and the run settled with a grounded
answer ("39 folders directly under /Users/bao") in 2 model calls. The new state payload carried the real
observation text the inspector shows. 595 frontend tests and 37 engine/route tests pass, `tsc` and `ruff`
are clean, `eslint` reports 0 errors.

**Not verified:** the in-app Explorer was not driven in a browser against the isolated stack this session
(that needs a frontend build; its components are covered by tests and the SSE contract it consumes was
live-verified). Windows remains unverified. The exit gate is still blocked by the pre-existing frontend
warning budget (59 warnings against 53 — the row the office has carried for days; 0 errors).

## Added after the first pass: the Simulator

The engine could act but could not *reason about acting*: an action that changes something was refused and
the search stopped there. It now predicts such an action instead (given what the state already knows), so a
goal that needs a write can be searched and planned with nothing written. A prediction is labelled as one
in the event stream, on the tree card and in the inspector, is never learned as a fact, and can never settle
a goal; if only predictions can advance, the run stops with `needs_action` naming the action and what it
would produce. Live proof on the isolated stack: a goal that asked for a file to be written ran a real
search (6 probes, a backtrack), predicted the write twice, created **no file**, and stopped not-settled.
Building it also caught a genuine hole — a prediction was reaching the state as a transition — which is now
fixed and covered by tests.

## Still open

- The Explorer's browser pass, and Windows, per above.
- The engine's next slices: **executing** a confirmed action behind the ADR-67 confirmation (the write is
  currently only planned and predicted, never performed), a second `Environment` as the proof the adapter
  boundary holds, beam > 1, persistent state. The `needs_action` stop is unit-tested but was not observed
  live (the live run's real probes failed first, so it stopped `no_progress`). These are backlog rows in
  the fresh office.
- The office's own high-priority row: the exit gate's warning budget — fix the warnings or consciously
  raise the number, but do not let a red gate become normal.
