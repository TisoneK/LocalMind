# P0 Design — the Acceptance Gate (B-2026-08-12-1) — LOCKED 2026-08-12 (Session 154)

Design review complete; the four open decisions were settled by the user on
2026-08-12 (Session 154). This doc is the implementation contract for P0.

## Locked decisions

1. **Gate strictness: STRICT + honest report.** Unmet criteria block
   completion: the loop keeps working/replanning while iterations remain; the
   final answer MUST state which criteria are unmet when any remain. "Done"
   requires receipts.
2. **Wiring: INTO AgentLoop (small).** Call `is_done()` at the iteration head
   of the existing `AgentLoop.run()` (`loop.py:1552`); do NOT extract
   `BaseAgent._run_loop()` in P0 (ADR-8 Phase 2 extraction stays a later
   slice).
3. **Replan style: EXPLICIT replan call.** On gate failure with iterations
   remaining, run a dedicated LLM replan call (reusing the planning-phase
   prompt shape, `_plan_stream`/`build_planning_prompt`), then continue the
   loop. Extra latency/cost per failure is accepted for deliberateness.
4. **Criteria source: BOTH.** The dispatcher's `execution_plan` schema AND the
   model's own `create_plan` tool accept `success_criteria`.

## ① Typed success criteria

- Dispatcher `execution_plan` JSON (`thinking_dispatcher.py:328`) gains
  `success_criteria: list[str]` alongside `steps`.
- `create_plan` tool (`loop.py:847`) gains an optional `success_criteria`
  property (array of strings) alongside `steps`.
- `OrchestrationPlan` gains `success_criteria: list[str]`; threaded into the
  loop as a new `success_criteria` param (sibling of the existing
  `plan_steps` param on `BaseAgent.run()` / `AgentLoop.run()`); mirrored onto
  `AgentTrace.success_criteria`.
- Prompt rule (dispatcher + planning prompt): criteria must be statements
  checkable against tool output or the workspace — a command that passes, a
  file that exists with content, a git-diff outcome, an HTTP status, absence
  of ERROR markers. Subjective phrasing is discouraged (checker has a
  fallback, see ③).

## ② First-class TaskState

New module `backend/src/core/agent/task_state.py`:

```
TaskState {
  objective: str                  # reformulated query
  constraints: list[str]          # safety_level, realtime_sensitive, user constraints
  success_criteria: list[str]
  phase: 'plan' | 'execute' | 'verify' | 'final'
  completed: list[str]            # step ids/labels done
  pending: list[str]              # step ids/labels remaining
  failed: list[tuple[str, str]]   # (step, error)
  evidence: list[dict]            # {tool, input, observation_excerpt, succeeded, iteration}
  iteration: int
  budget: dict                    # {iter_used, iter_max, wall_used, wall_max}
}
```

- Created once per turn in `AgentLoop.run()`; updated after every tool
  execution; `to_prompt()` renders a compact **TASK STATE** block injected
  into the system prompt each iteration (sibling of the workspace feedback
  bar).
- Relationship to the scratchpad (`create_plan`/subgoals): the scratchpad
  stays the model's own planning artifact; TaskState is the engine-side
  record the gate judges. Complementary, not duplicative.
- `to_dict()` for obs/session persistence.

## ③ Real is_done() + deterministic checker library

New `backend/src/core/agent/verify.py` — no LLM calls, deterministic, reusing
patterns already in the codebase:

- `"tests pass"` / `"tsc"` / `"build"` → parse last shell/code_exec
  observations for the command + pass/OK/no-error markers.
- `"<path> exists"` / `"created <path>"` → os.path check in the session
  workspace + match against write/edit tool inputs.
- `"git ..."` → reuse the per-turn `workspace_state` snapshot (already
  computed every iteration).
- `"<endpoint> returns 200"` → scan web_fetch/browse observations for status.
- `"no errors"` → scan observations for ERROR/failure markers.
- **Fallback:** evidence-requirement — criterion met if the trace contains a
  tool observation quoting its key tokens (the `WorkReport.needs_report`
  token-matching trick).

Each `agents/*/is_done.py` becomes: evaluate the trace's criteria via the
checker → `(True, "criteria met: …")` if all pass; `(False, "criteria not yet
met: …")` if the model asserts done but criteria are unmet. Tasks with no
criteria (chat/trivial/research) fall back to today's behavior — zero
regression. Per-agent semantic overrides (e.g. bug-reproduction tasks where
"reproduced" ≠ "criteria met") are preserved via the per-agent file.

## ④ The verify→replan gate (the loop change)

- `is_done()` is CALLED at the top of each iteration in `AgentLoop.run()`
  (`loop.py:1552`) with the live trace + last tool result.
- **Gate on model-said-done** (no more tool calls):
  1. Evaluate all success criteria against trace evidence + workspace.
  2. All pass → final answer as normal + one-line gate summary
     (`✓ 2/2 criteria met (pytest passes, hello.py created)`).
  3. Some fail + iterations remain → **explicit replan call** (dedicated LLM
     call reusing the planning prompt shape) whose output feeds a
     verify-failure block into context: *"Success criteria NOT yet met:
     [criterion — current evidence — gap]. Revised plan: …"* → loop
     continues.
  4. Some fail + caps hit → honest close via `_summarize_trace_for_user` +
     `WorkReport`: which criteria met/unmet + evidence. Never a false "done".
- **Bounds:** existing caps unchanged (8/180s generic, 20/300s coding). The
  gate adds at most one deterministic check + at most one replan call per
  gate evaluation.

## Edge cases

- Bug-reproduction (verifier/debugger intents): per-agent overrides keep
  their own done semantics; the gate is advisory to them.
- Unmeetable criteria: honest report + evidence, bounded by caps.
- Delegated children: each child gets its own TaskState slice; parent's gate
  treats children's reports as evidence.
- Fabricated-detection (`loop.py:3185`) + heading-only rescue (Session 147):
  untouched — the gate sits after them.

## Build order (each step deterministic + unit-testable; live smoke last)

1. `task_state.py` + prompt renderer + unit tests. ✅ Session 155
2. `verify.py` checker library + unit tests. ✅ Session 155
3. Wire `is_done()` into AgentLoop iteration head (stubs still return False →
   no behavior change) + tests. ✅ Session 156 (real is_coding_done; clean
   gate-passed return, not hit-limit)
4. Dispatcher schema + `create_plan` schema + `OrchestrationPlan.success_criteria`
   + parsing + tests. ✅ Session 156
5. Gate integration at the final-answer path + explicit replan call + tests.
   ✅ Session 157 (time-boxed replan, honest unmet report at cap)
6. Real-model smoke — attempted Session 158 (`scripts/smoke_gate.py`):
   pipeline verified live to the provider call (context build → dispatcher
   thinking → Zen 429 FreeUsageLimitError). STILL BLOCKED on a live model;
   retry when Zen free tier recovers or install Ollama. Loop-path code
   covered by 18 gate tests + full suite 1358 green; per the flaw log the
   live E2E remains pending.

## No-regression list (from the manifest — must hold)

Iteration caps (8/180s) + hit-limit fallback wording; check-before-acting
`safety.md` injection; trailing-tool-role + reasoning-only Phase-1 adapter
fixes; `_obs.all()` not `drain()`; ADR-17 call collapse + signal fast paths;
evidence-quoting Worker-report gate; per-agent max_iterations honored by
`AgentLoop.run()`; Session 153 fast-path empty-stream fallback.
