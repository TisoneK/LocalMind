# Review — S023 (Zuri): the Planner lane — the real todo list on the production path

**Date:** 2026-11-02 · **Trigger:** the owner's second live export (session-1793620218681, "How are things") and the owner's verdict: *"I see task list is just the old style tool echoing task no actual plan output is messy and it feels like everything we have been building has gone to waste."*

## What the export actually showed (verified from the JSON, not from memory)

1. **`syn-0` tool-echo todos on ordinary turns.** The weather turn's only todo was `syn-0 "Search: weather Kitengela current now"` — a synthetic row synthesized from the tool call itself. The Agents panel showed it at "100%". No drawn plan anywhere.
2. **The thinking channel carried the Thinker consult's JSON rehearsal.** The Arsenal turn's `thinking` field opens with the pre-tool consult's reasoning verbatim — including `"Let me structure this as a JSON response: ```json {"facts": …"` — and ends mid-JSON. The consult's decision JSON belongs to the TEXT channel; the flash model rehearses constructing it ON the thinking channel, and the consult streamed that rehearsal to the visible ThinkingBlock.
3. The turn otherwise behaved (search ran, completion judge ran, lanes stamped) — the app the owner tested ran post-S022 main. This was a real product gap, not staleness.

## Root cause (the "everything is wasted" feeling was a wiring gap, not lost work)

S020 (f76cabff) built the real `{todo, outcome}` plan INTO the parent-init branch — gated on `not skip_planning`. The production runtime (`agent_runtime`, warm-kernel, since August) passes `skip_planning=True` for every parent turn, so **the branch the plan lives in is dead code on production turns**. The plan-derivation chain that DOES run on production (`goal_items` → `derive_sequence_plan`) covers file-deliverables and self-sequenced requests only, and `lookup_plan.py` says so outright: *"There is deliberately no canned plan for an open-ended request such as a web lookup."* Every lookup turn therefore fell to the `syn-` fallback. The S022 review's cut list said the same thing: "P3 conversation→todo contamination = S020's" — but S020's mechanism was unreachable where it mattered.

## What shipped

**A. The Planner lane (the fix for the tool-echo complaint).** `agent_runtime` now draws the plan by MODEL before the loop on every task turn that has no goal checklist, no self-spelled sequence, no outstanding open question, and is not a pure social gesture: the same `build_initialization_prompt` / `parse_initialization` contract S020 gave the classify call, as a bounded lane (thinking-off per-call override, 12s, fail-open on timeout/error/non-execute — the turn then proceeds exactly as before). The drawn plan rides the existing `plan_steps` seam plus two new run() params:
- `plan_outcomes` — the per-todo verification contract; seeds `todo_created` with `expected_outcome` + `status="pending"` on the runtime branch (previously that branch emitted bare rows), AND seeds `trace.success_criteria` when no explicit criteria exist — the per-todo contract IS the completion contract (S020's seeding, now reachable).
- `plan_objective` — the Planner's one-line understanding, rendered as the UNDERSTANDING plan context so execution reads the objective, not just step labels.
The branch also emits `todo_cleared` before seeding (matching the parent-init branch — a new plan replaces what the session showed). `BaseAgent.run()` forwards both new params (the plan_steps forgot-to-forward crash class, guarded by test).

**B. Adaptive plan revision + retired status (B-2026-11-02-2, first half).** The acceptance gate's replan now flows into run()'s `_apply_plan_revision` closure (one revision per turn): dropped rows retire explicitly (`todo_updated status="retired"` carrying the discovery in `result`), genuinely new work appears as new `plan-{i}` rows, and a `todo_revised {added, retired, kept}` diff lands on the record. Closed rows (evidence-backed done / failed) never churn. `_parse_replan_steps` parses the replan's bare numbered steps (the planner's STEPS-headered parser + its concrete-command filler filter both mis-fit a replan). The finalize sweep leaves `retired` rows closed. Frontend: retired rows render struck-through with a Ban marker, leave the n/n denominator, a "Plan revised — N steps retired" marker appears, and the result note carries the discovery.

**C. The objective-fidelity lane (B-2026-11-02-2, second half).** At the gate-pass close, a bounded read-only lane (thinking-off, 5s, fail-open) asks ONE question: does the reply address the ORIGINAL request, not merely the todos? Verdicts ride `post_answer_lanes.objective_fidelity`; a `drifted` verdict emits `objective_drift` with the reason and the original ask — one drift nudge, on the record, never a block.

**D. The thinking-channel cleanup (the "messy output" complaint).** `Thinker.consult` now streams its reasoning through a fence suppressor (`_FenceSuppressor`): deliberation stays verbatim; fenced blocks (the JSON rehearsal) are dropped across chunk boundaries, including split markers; an unclosed fence suppresses to stream end. The decision JSON itself was always on the text channel — this removes only the construction noise from the visible reasoning.

## What was deliberately NOT done

- The degraded/rate-limited raw-evidence fallback (the weather turn's raw dump) — S022 already covered its shape; the export's fallback text is the honesty path working, and the underlying gap there is search QUALITY (Nairobi-instead-of-Kitengela), not rendering.
- Model-initiated plan revision (todo_write-driven diffs) — the gate-replan trigger ships; the model's own rewrite trigger stays in B-2026-11-02-2.
- The conversational fast-path answering arithmetic directly ("What is 128 times 456?" never reaches the loop) — pre-existing design, found while harnessing; not in this scope.

## Verification

- Backend 4,060 passed / 2 skipped (includes 13 new tests in `tests/core/test_planner_lane.py`: fence suppressor, runtime-path plan seeding, outcome→criteria, revision retire/add/once, fidelity verdicts + fail-opens, BaseAgent forward, finalize-retired). e2e 132. Frontend 678 + tsc. ruff clean on `src`.
- NEW standing harness `scripts/live_test_planner_lane.py` ALL PASS on the wire: the turn's FIRST provider call is the Planner lane; `plan-0/plan-1` rows arrive pending WITH the outcome contract; no `syn-` rows; the answer closes against the drawn contract without a false replan; the consult's fenced rehearsal never reaches thinking; a social turn skips the lane entirely and still reaches the model.
- Standing harnesses re-run clean: prompt-structure, arsenal-fixes, greeting-gate, goal-idle, turn-trace, turn-close, done-rules, provider-death-honesty, goal-continuity, trajectory-projection, provenance-symmetry, eval suite 13/13. (compaction / native-thinker / evidence-grounding need a real provider key — the standing environment note.)

## Harness debt found and paid en route

Five standing fakes routed by REQUEST COUNT (`len(REQUESTS) == 1`). The Planner lane legitimately adds one chat call before the loop, so "request N" stopped addressing the loop call — the fakes fed the planner the loop's scripted tool response and the turns collapsed. All five (prompt-structure, arsenal-fixes, done-rules, provider-death-honesty, provenance-symmetry) now route by CONTENT (tools-in-payload ⇒ loop call), and two latent assertion bugs died: prompt-structure's positional audit→capture index-mapping (now filters captured requests by tool schemas; the append-only audit file is truncated at run start), and arsenal P5's false-pass on an empty tool-result list (now a hard failure; the bounds assertion checks the visible contract — 10-day window, newest 1 — not the operation-name echo).

## Do-not-regress

- The lane is FAIL-OPEN by design: a slower provider, a flaky JSON, or a non-execute verdict must never change the turn's fate — it only forgoes the plan. Never make the lane's parse mandatory.
- `is_pure_social_gesture` skips the lane but NEVER the model: the S471 ruling stands (no input class is answered from a hardcoded string; greetings reach the model like any other turn).
- The fixed denominator discipline: retired rows leave the UI denominator but never mutate `_plan_steps`' seeded ids; new rows append, they do not renumber.
- The completion judge's and the fidelity lane's bounds (5s, thinking-off) — they are lanes, not the answer path (ADR-41).
