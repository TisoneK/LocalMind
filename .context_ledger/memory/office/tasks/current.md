# Current Task (overwrite each session)

Holds exactly one task — the one being worked on right now. Set it at
session start (protocol Step 3), clear it at session end (Step 15). If
you find a stale in-progress entry here, a prior session died mid-task —
its roster row (if left behind) says who was here; check the session
entry and backlog before starting.

- **Session:** 2026-10-29 — Zuberi / GLM (Z.ai) (S030)
- **Feature:** provenance & audit symmetry — roadmap §U item 3 (`docs/reference-harness-gap-inventory.md`, rows B + G, fixes F5)
- **Task:** shipped as 5a1fde4e — the retry-attempt ledger (dispatch layer keeps every failed attempt; it rides the tool record end to end), the typed injected-items ledger (exact rendered text + producer, one context_injected event per prompt surface, persisted and restored on reload), the degraded provider-death phase persisted in the strip, and the frontend outcome truth (an errored reply renders the turn failed; the plan pill names "didn't finish"; retries expand into the attempt ledger; the context popover shows "Injected this turn" with opaque fallback for unknown kinds).
- **Status:** done — backend 3720 passed / 2 skipped (+13), frontend 640 passed (+15), live wire proof PASS (`scripts/live_test_provenance_symmetry.py`: record == wire, retry ledger on the wire, degraded death + error object, reload persistence); both prior live harnesses re-run PASS. §U item 4 (done-rules extension) is the next build session.
