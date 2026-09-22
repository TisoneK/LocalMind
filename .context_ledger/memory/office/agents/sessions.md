# Agent Sessions (append-only within the current office)

One entry per agent session in the **current office**, newest at the bottom.
Never edit or delete past entries — append corrections instead. This is not
append-only *forever*: when the office reaches `office_size` sessions (or a
milestone), `ledger-history close` freezes this whole office verbatim into
`.context_ledger/history/office-<NNN>/` (roster, registry, notes, logs —
nothing trimmed), writes the permanent accomplishments record
`.context_ledger/history/office-<NNN>.md`, and opens a fresh empty office
here. Closed offices in `history/` and `archive/` are never read at session
start. Before closing, note which open threads still matter — they are
re-seeded into the new office explicitly, and nothing else carries over.

<!-- TEMPLATE — copy below the last entry and FILL IN every placeholder:
---
## YYYY-MM-DD — Session N
- **Agent:** <name> | **Model:** <model id> | **Platform:** <machine/sandbox + OS> | **Role:** <engineer, or overlay from .context_ledger/core/roles/> | **Core:** <version from .context_ledger/core/VERSION>
- **Task:** <what this session set out to do>
- **Commits:** <count> (<first-sha>..<last-sha>)
- **Outcome:** <done / partial / blocked — one line>
- **Open items:** <pointers into tasks/backlog.md (actionable) or tasks/parking-lot.md (findings/questions), or "none">
- **Notes:** .context_ledger/memory/office/sessions/<date>-<N>/notes.md  (or "none")
- **Report:** .context_ledger/memory/office/reviews/YYYY-MM-DD-review.md
-->

## 2026-09-21 — Mosi (S001) — office-002 closed; the state engine becomes a standalone engine with the State Explorer as its UI

- **Agent:** Mosi | **Model:** deepseek-flash (ZCode desktop) | **Platform:** macOS (Darwin 24.6.0) | **Role:** engineer | **Core:** 2.0.3
- **Task (owner-directed, three turns of scope):** continue the state-driven engine — finish the in-app State Explorer + the Classic/State engine setting; make the Explorer "very powerful"; then the reframe: *the engine is the product and LocalMind is only the first environment it runs in.*
- **Door work first (the office was 8 sessions past `office_size`):** core 1.2.0→2.0.3 migrated with the entrypoint files regenerated (`a892320c`); checked in (`e03a9b84`); ran `ledger-history close` — office-002 frozen verbatim with a 137-line permanent record, a 24-row actionable backlog, the carried ADRs (62–71) and four still-open protocol traps re-seeded, and the fresh office opened with this session signing it (`ad544b2b`). Logged and fixed a packaging flaw: the core templates ship eight office files mode 0755, so every close injects mode churn (`b447cf14`).
- **Shipped (engine selection + the Explorer in the app):** `engine` setting with `POST /api/settings/engine` + `EngineChoice` in Settings → Agent, and the app shell swaps the chat pane for the State Explorer when State is selected (`9661ce64`, 20 frontend tests).
- **Shipped (the Explorer as an instrument):** search-budget controls fed by the backend's published defaults/limits, tree layers (moves / failed / not-best / pruned), a chosen-path-only view, run history persisted across reloads, side-by-side run comparison, an inspector that reads the *state* (facts learned, actions ruled out, path, spend), evidence out as JSON and as a Markdown summary, keyboard control, and a progress curve (`8232aa26`; engine events now carry `fact_list`/`failed_fps`/`trail` so a UI can read the search). Fixed a real engine bug the UI exposed: a failed probe was remembered as failed only on the backtrack path, so a failed action could be re-proposed after a round that succeeded.
- **Shipped (the reframe):** `backend/src/state_agent/` is now the whole engine — contracts (`Environment`, `Simulator`, `Proposer`, `Evaluator`, `TerminalCondition`, `ModelPort`), the immutable state, the loop with injectable terminal conditions, and the model's two jobs — importing nothing of LocalMind's; `state_agent/adapters/localmind.py` holds tools/dispatcher/provider/CLI, the web route builds through it, and `tests/state_agent/test_boundary.py` fails the build if the engine reaches back into the host. The old `core/state_engine/` is deleted. ADR-72 records it; the engine has its own README. (`e740841f`)
- **Verification:** 595 frontend tests green (incl. 33 for the engine's pure layer and the Explorer's powers); 37 backend tests for the engine + routes; ruff clean; `tsc` clean; `eslint` 0 errors — **live** run through the refactored engine on the isolated 8765 stack with deepseek/deepseek-chat: a real goal settled in 2 model calls with 3 real probes and a grounded answer ("39 folders under /Users/bao"), the budget I sent honoured in the `meta` event, and the new `fact_list` carrying real observation text.
- **Not verified / open:** the browser pass of the in-app Explorer against the isolated stack (needs `npm run build`; the components are covered by tests, the SSE contract was live-verified) — filed in the backlog; Windows still unverified; the exit gate remains blocked by the pre-existing frontend warning budget (B-2026-09-21-1, 59 > 53, 0 errors).
- **Coordination:** solo in the tree (the previous office's session had gone cold, its work uncommitted; I took it over at the owner's direction and committed it). Claim `20260921T204211Z-Mosi-01261bbd` published before the first edit; release below.
- **Report:** `office/reviews/2026-09-21-review-s1-state-agent.md`

**Re-check-in — same session, the owner said "go ahead": the Simulator slice (extends this entry, not a second session):**
- Re-added my roster row (same name/codename), claimed the scope, and built the engine's next concept rather than another UI feature: **a `Simulator`** so an action that must not be performed can still be *planned*. `state_agent/simulator.py` predicts an action's outcome from what the state already knows; the engine's three guarantees are enforced in code and pinned by tests — a prediction is labelled (`predicted`), is never learned as a fact, and can never settle a goal. Building it exposed a real hole: a predicted outcome was reaching `AgentState.apply` as if it were a transition, so a prediction could have moved progress and depth. Fixed: predictions are scored and compared but never applied, and when only predictions can advance a run the engine stops honestly with `needs_action`, naming the action and its predicted result.
- Wired in LocalMind's adapter (`file_write` published as NOT read-only, simulator on by default) and in the UI (cards read "◌ predicted", the inspector says "PREDICTION (the action was not performed)", and the tool note counts "6 read-only · 1 simulated").
- **Verification:** 39 backend tests (engine + routes) and 30 frontend tests green; ruff/tsc clean; eslint 0 errors / 59 warnings (the pre-existing budget). **Live**, isolated 8765 + deepseek-chat: a goal asking for a file to be written ran a real search — 6 probes (4 real read-only, 2 predicted writes), 1 backtrack, 21 events — and **no file was created**; the run ended `stopped / settled: false`.
- **Honest gaps:** the live run stopped with `no_progress` (its real probes failed first), so the `needs_action` stop is unit-tested but not yet observed live; the write action is still only *planned*, never executed behind a confirmation (that is the next slice, together with a second `Environment` as proof the adapter boundary holds).

**Re-check-in — same session, the owner's boundary directive ("make sure the core engine has no accidental dependency on LocalMind"):**
- Audited the engine for coupling and found it where it was least visible: in *vocabulary*, not code. The core's own docstrings cited LocalMind's ledger IDs (ADR-67 in two files) — host coupling, and a violation of the project's one-way-linkage rule. Reworded to state the rule rather than the host's record number, and the boundary test grew two exception-free guarantees: the core cites **no host record system** (ADR-N / B-IDs / session codenames / ledger paths) and reads **no ambient configuration** (no env vars, no config files — everything arrives through the constructor).
- Built **adapter #2**, the strongest available proof of independence: `state_agent/adapters/files.py` (a read-only filesystem environment, standard library only), `adapters/openai_compat.py` (a `ModelPort` over any OpenAI-compatible endpoint, stdlib HTTP, key by env-var NAME, never read or printed), and `adapters/files_cli.py` — a CLI that runs a goal with no host application, no server and no settings file. 33 engine tests green (7 new), ruff clean.
- **Extracted Prototype 0 into its own repository** at `~/Code/ti-matrix` (private, remote wired, `git push` pending the owner creating the empty repo — the `gh` CLI is not installed on this machine): its own history, `pyproject.toml` (distribution `ti-matrix`, import package `state_agent`), README, and the engine + both adapters. Proven self-sufficient: with `PYTHONPATH` cleared the engine loads from its own tree and **all 33 tests pass with nothing of LocalMind on the path**. The boundary test now locates the engine by import, so it holds in both repos.
- **Decision recorded for the follow-up (not done):** LocalMind should stop being the engine's home and become a consumer — vendor the engine or depend on `ti-matrix` — and its in-app Explorer becomes the engine's Studio UI. Filed as backlog row `B-2026-09-21-25`.
