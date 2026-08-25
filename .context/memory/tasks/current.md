# Current Task

**Status:** IDLE — Session 402 (B-2026-08-25-6 diff-card accept fix) COMPLETE
and pushed (3072074 + context commit); pending user visual sign-off in the
running app. No live session in progress. The Session 399 notes below are
retained for context.

## Session 399 — done this session (all pushed)

guard exemption (5678a05) · B-24-5 label swap (0827fdf) · B-24-3 remove old
tool selector (8447d22) · B-24-4 agent-turn titles (9e374e1) · B-24-10 shell
timeout 45→120s (e827e8b) · B-24-11 psutil dependency (7552aa0) · B-24-2
failure-aware/wall-clock-bound iteration cap (ef465ea + 487e408, live-tested) ·
WorkspaceLayout stale test mock (ae298ad) · B-24-13 app bg = Settings surface
(1b15c2f) · B-24-14 removed `layout` reflow jitter from live lists (6cc1aa7).

**More done:** B-24-9 self-disclosure policy + knowledge-doc load-path fix
(0a2c67c, live-verified); B-25-1 local-search-over-shell 4-layer fix
(a2d4ff4/8f3c1e1/1bf3594, live-verified); live_test script made portable.

**Open B-24 items:** B-24-1 + B-24-6 (curated narration — user chose "curated
narration only"; big item) · B-24-7 (gemini bypasses agent) · B-24-12 (sysinfo
native fallbacks) · B-24-15 (todos completed on cut-short turn) · B-24-16
(chat→agent switch prompt) · B-24-17 (terminal redesign). Open B-25: -2
(content search), -3 (open_with verify). B-24-8 = standing live-test practice.

**Live-test:** authorized per-item when necessary; test backend on **port 8010**
(never 8000 — the user's app). Read `.context/memory/system/live-testing.md`.

---

## Session 400 — system-search-tool Phase 1 COMPLETE (separate session)

**Feature:** system_search unified local search tool (6 ops), local-discovery
routing fix, find_path retired from model surface; backend 2586 passed / 2
skipped; live-verified on zen/hy3-free + zai/glm-4.5-flash. Next candidates
logged as B-2026-08-25-1/-2/-3. See
`features/system-search-tool/manifest.md` for the evidence table and limits.

**User directive reminders (standing):** one feature per session; fix spotted
issues unless they need their own session; no pauses between sessions; multi-
agent development; live-test the real app on free models; never touch port
8000; never print key values.
