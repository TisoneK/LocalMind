# Current Task

- **Session:** 154 (2026-08-12)
- **Feature:** verification-first-hardening
- **Task:** Design review + lock of the P0 acceptance gate (B-2026-08-12-1) —
  the user picked "design review first" and settled the four open decisions.
- **Done (154):** walked the P0 design grounded in the current code (loop,
  trace/evidence model, base agent, dispatcher schema) and LOCKED it:
  1. strict + honest-report gate (unmet criteria block completion; final
     answer states what's unmet), 2. wire `is_done()` into the existing
     `AgentLoop` iteration head (no `BaseAgent._run_loop()` extraction in
     P0), 3. explicit LLM replan call on gate failure, 4. `success_criteria`
     accepted by BOTH the dispatcher's `execution_plan` and the model's
     `create_plan` tool. Full design persisted at
     `features/verification-first-hardening/design-p0.md` (four pieces:
     typed success criteria, first-class TaskState, deterministic
     `verify.py` checker + real per-agent `is_done()`, verify→replan gate;
     build order steps 1-6; no-regression list).
- **Next:** Session 155 — implement B-2026-08-12-1 in the design-p0.md build
  order: (1) `task_state.py`, (2) `verify.py`, (3) wire is_done into
  AgentLoop, (4) dispatcher + create_plan schemas, (5) gate integration +
  replan call, (6) real-model smoke (Zen overloaded 2026-08-12 — a local
  Ollama model unblocks the live test earlier; per the flaw log do not ship
  loop-path code untested). Secondary pending: B-2026-08-12-4 (Session 151
  carry-over — live two-turn UI check).
