# Current Task

- **Session:** 150 (2026-08-11)
- **Feature:** B-2026-08-11-5 — stats split + context-window meter; B-2026-08-11-6 — git-phrasing signal
- **Done (149-150):** git-phrasing signal (zero-LLM for "Check git status…" → chained status→diff plan); bottom-right corner now shows cumulative session stats (summed tokens, weighted speed, average latency, turns chip) while per-message lines stay under each bubble; top-bar confidence badge removed → live context-window occupancy meter (this turn's prompt / 128K zen window, color-graded). backend 1293 / frontend 95 tests green.
- **Next:** Session 151 — browser-level real-UI validation of the new corner + meter (start backend + frontend, drive a real request, verify the corner accumulates across two turns and the meter moves), then continue the ADR-17 latency track.
