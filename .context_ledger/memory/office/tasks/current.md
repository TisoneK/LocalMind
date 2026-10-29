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
