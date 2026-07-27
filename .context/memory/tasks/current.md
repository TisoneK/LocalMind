# Current Task (overwrite each session)

Holds exactly one task — the one being worked on right now. Set it at
session start (protocol Step 3), clear it at session end (Step 15). If
you find a stale in-progress entry here, a prior session died mid-task —
check its session entry and backlog before starting.

- **Session:** —
- **Feature:** none — no session in progress (Session 34 Phase 4 complete: ADR-8 agent-centric routing FULLY IMPLEMENTED — all 4 phases shipped in Session 34. Phase 1: agents as directories (commits 5deaece+1a2b50c). Phase 2: build_context() wired into BaseAgent.run(), workflow files reach the model (6a76bd6+f534281). Phase 3: agent-initiated delegation via the delegate tool (a91baa4+4e131ac). Phase 4: task-type-based agent selection — primary_domain routes, intent is a signal not the router (672d0c8+context). 497 tests pass (412 baseline + 22 Phase 1 + 11 Phase 2 + 20 Phase 3 + 32 Phase 4 = 497). Real-model smoke tests pass on Zen/deepseek-v4-flash-free for Phases 2, 3, 4 (Phase 1 was pure structural). ADR-8 status in decisions.md still says "proposed" — a future session should update it to "accepted — implemented". See `.context/memory/features/adr-8-agent-centric-routing/notes.md` for the full per-phase implementation record + post-ADR-8 deferred work.)
- **Task:** none
- **Status:** idle
