# Current Task (overwrite each session)

Holds exactly one task — the one being worked on right now. Set it at
session start (protocol Step 3), clear it at session end (Step 15). If
you find a stale in-progress entry here, a prior session died mid-task —
its roster row (if left behind) says who was here; check the session
entry and backlog before starting.

- **Session:** 2026-10-29 — Soren / Opus 4.8 (`claude-opus-4-8`) (S032)
- **Feature:** live-test harness exit-code fix (isolated worktree; follow-up to S031's `office/inefficiencies/log.md` 2026-10-29 entry)
- **Task:** port the S031 `fake.server_close()`-before-port-sweep fix into the three older live-test harnesses (`live_test_provider_death_honesty.py`, `live_test_identity_injection.py`, `live_test_provenance_symmetry.py`) so a passing proof stops exiting non-zero — the in-process fake provider's listening socket, left bound by `ThreadingHTTPServer.shutdown()`, made the teardown `kill_port(FAKE_PORT)` taskkill the harness itself on Windows.
- **Status:** done — three identical teardown edits matching the `done_rules` reference; all four harnesses `py_compile` clean, `ruff check backend/src` clean, `tsc -b --noEmit` clean. Mechanism proven env-agnostically (after `shutdown()` the port sweep hits the harness's own pid; after `server_close()` it hits nothing). Real booted end-to-end run deferred to a Windows session (the failure cannot manifest on POSIX). One of three concurrent sibling sessions off a single hand-off.
- **Session:** 2026-10-29 — Rafael / Opus 4.8 (S032)
- **Feature:** trajectory view → projection of the record — `docs/reference-harness-gap-inventory.md` rows B + G (1 of 3 parallel worktree sessions)
- **Task:** the agent run tree + phase strip are now derived by one deterministic reducer (`frontend/src/lib/localmind/turnProjection.ts`) from the turn's recorded obs stream — the same projection the backend persists and a reload renders — replacing the imperative live accumulator in `useLocalMind.ts`; a cross-language contract test pins the two ports together; `has_content` now requires real work so a direct turn shows no run node on any path (live == reload).
- **Status:** done — FE 660/660 (tsc+eslint clean), backend 3749 passed / 2 skipped (ruff clean), live proof PASS (`scripts/live_test_trajectory_projection.py`, fake + `--real deepseek`). Committed `14e18caa` on branch `claude/trajectory-projection-13b286`. Follow-ups B-2026-10-29-1 (flat tool-pills) and B-2026-10-29-2 (async-suite config flake). Awaiting owner review / merge.
- **Session:** 2026-10-29 — Jabari / GLM (Z.ai) (S033)
- **Feature:** independent review — S031 done-rules extension (roadmap §U item 4, row E, commit `9bfe6fd2`)
- **Task:** supervisor-requested second review pass over the done-rules work: deep-read `backend/src/core/agent/turn_outcome.py`, the `loop.py` diff, `tests/core/test_done_rules.py`, `scripts/live_test_done_rules.py`; re-run the done-rules suite and the live harnesses live on this tree; verdict per the code-review playbook; orientation note on the two unmerged S032 side branches for the supervisor.
- **Status:** done — verdict **PASS with findings, the S031 release stands** (review `542b9398`); guarantees verified live (40/40 + 73/73 unit, done-rules probe A wire-perfect, degraded path confirmed via the provenance harness PASS). Two findings parked for the owner: (1) harness fakes race the product's background provider calls (two false-negative live runs, mechanism traced); (2) the no-evidence death wording at `loop.py:6739-6748` still sits outside the turn contract with its matching contract shapes unreachable. Read-only claim honored; release event cites claim + review commit.
