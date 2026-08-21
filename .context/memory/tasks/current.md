# Current Task

**Status:** IDLE — Session 330 shipped the synthesize/evaluate stage (fixed goal-checklist
gating completion, `30e37b8`; ADR-54; B-2026-08-20-24 done).

## Session 330 outcome — completion gated on a goal-derived fixed checklist

- The user's consolidated finding: premature completion, todos mutating to match whatever ran
  (always 100%), and the 2/2 lie are symptoms of ONE missing piece — no synthesize/evaluate
  stage holds a fixed goal-checklist and compares outcomes against it before declaring done.
- **FIX (`30e37b8`, live-verified):** deterministic `derive_goal_items(message)` (zero LLM
  calls) derives the fixed checklist from the request (named files + write verbs, folders +
  create verbs; conversational/abstract → [] → legacy path). agent_runtime passes it as BOTH
  plan_steps (fixed Todos denominator, plan-0..N up front) and success_criteria (gate
  contract), with `skip_head_gate=True` (criteria gate at the final-answer point, never the
  iteration head). The gate no longer auto-accepts a goal turn with ZERO tool evidence
  (live-found: "I'll set up the tools needed for file operations." → 3/3 todos, zero files) —
  all-unmet → replan → honest-stop at cap (`agent_loop_gate_honest_stop` + per-goal todo
  state); chat.py `_finalize_plan_todos(skip=True)` stops flipping unmet items (no false
  100%). verify.py `_norm()` Windows-backslash tolerance (S264/S325 family).
- **LIVE before/after (bankofai/deepseek-v4-flash, isolated 8765):** before — no-tool stop
  accepted with 3/3 todos and no files; after — `agent_loop_gate_failed_replan` fired, the
  model created the folder + a.txt="first" + b.txt="second" (on disk), finished
  `criteria=3 gate=pass` "✓ 3/3 criteria met". Backend 2106 / 2 skipped / 0 failures.
  Honest-stop cap path + SSE skip: unit-verified (the live model cooperated after the replan).
- **Next:** user restarts the app backend and re-runs the path-test / notes-txt tasks — the
  panel shows the fixed checklist up front and completion only with evidence. Optional
  follow-ups (backlogged): `todo_failed` event for unmet items (failed styling); LLM
  goal-derivation tier for abstract tasks (deliberately deferred — false-fail + latency risk).

## Session 329 outcome — hyphenated creation-commitment tool-talk fix

- User live trace: path-test task ran ONE tool (shell listing of Dev/) then stopped mid-sentence
  ("Let me create the path-test folder and the two files") with no files created, yet the UI
  reported Todos 2/2, 100% and "Turn complete". Honest split: the premature stop is NOT the
  synthesized-todos change (pre-existing S323-class free-tier behavior) — but the "2/2 100%"
  panel IS our artifact (synthesized todos = tools that ran). Real bug: `_is_tool_talk`'s
  creation-commitment adjective group `(\w+ )?` can't match hyphenated/dotted tokens
  ("path-test folder", "a.txt"); widened to `(\w+(?:[.\-]\w+)* )?` — exact repro caught, S323
  preserved, safe negatives safe; regression test with the user's exact sentence. `93d59d6`.
  Backend 2087/2. (Note: Session 330's goal-checklist gate now also catches this class — a
  no-tool "I will create X" final answer fails the criteria gate instead of being accepted.)

## Next

- **B-2026-08-20-20 (Medium):** deepseek 500-chunk reasoning-then-empty ends turn via provider-error fallback.
- **B-2026-08-20-10 (High):** MiniMax XML interception conflicts with prose-commitment detector.
- **B-2026-08-20-11 (Medium):** 429 on iter=1 → empty bubble.

**Feature:** none (single-session loop fix)
**ADR:** ADR-54 (completion gated on a goal-derived fixed checklist)
**Review:** `.context/memory/reviews/2026-08-20-review-94.md`
