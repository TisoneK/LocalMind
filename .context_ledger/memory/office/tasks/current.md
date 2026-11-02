# Current Task (overwrite each session)

Holds exactly one task — the one being worked on right now. Set it at
session start (protocol Step 3), clear it at session end (Step 15). If
you find a stale in-progress entry here, a prior session died mid-task —
its roster row (if left behind) says who was here; check the session
entry and backlog before starting.

<!-- TEMPLATE — replace everything below this comment:
- **Session:** YYYY-MM-DD — <agent> / <model>
- **Task:** <what is being worked on right now>
- **Status:** in-progress | done | blocked (<blocker>)
-->

- **Session:** 2026-11-02 — Zuri (S019) / GLM (Z.ai sandbox)
- **Task:** Owner's live report: the dev stack crashes on any port conflict ("uses common ports... No flexibility"). Build port flexibility end to end — env-configured ports (LOCALMIND_PORT / LOCALMIND_FRONTEND_PORT / LOCALMIND_HOST), reuse-if-LocalMind, auto-fallback with a loud notice, LOCALMIND_PORT_STRICT for the old fail-fast, and propagation through dev:full / vite / electron / CORS / the one hardcoded absolute-8000 fetch.
- **Status:** in-progress
