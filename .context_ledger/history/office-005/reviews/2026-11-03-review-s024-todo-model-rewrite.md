# Review — S024 (Sanaa): the model's own plan rewrite — todo_write diffs, revised steps carry outcomes

**Date:** 2026-11-03 · **Trigger:** B-2026-11-02-2's remainder (the backlog item S023 explicitly left open): *"the MODEL's own rewrite trigger — a todo_write-driven mid-turn diff (the same retire/add/diff machinery, triggered by the model reshaping its own checklist rather than by the gate) and the acceptance criteria following a revision (revised steps carry outcomes too)."*

## The defect being closed

After S023, the acceptance gate's replan evolved the live todo list correctly — but a `todo_write` call from the MODEL still silently full-replaced the panel (`todo_cleared` + one `todo_created` per item): evidence-backed and retired rows vanished, no revision diff landed on the record, and the acceptance contract ignored the rewrite. The agent could not reshape its own checklist; it could only replace it.

## What shipped

**A. The todo_write diff (the model's own rewrite trigger).** A successful mid-turn `todo_write` result now DIFFS against the live panel rows instead of replacing them:

- **Diff base** — `_live_panel_todos()` mirrors what the panel actually shows: the model's own last-written list once it exists, otherwise the planner's `plan-{i}` rows (statuses from the loop's own close sets + the cursor), otherwise the `syn-` fallback rows.
- **Matching** — token-set equivalence among OPEN rows first (a rewrite rephrases; exact-text matching would retire and re-add the same work), the write's own id as the fallback. Closed rows (`completed`/`failed`/`blocked`/`retired`) are history: never text-matched, never churned; re-listing closed work arrives as a NEW row — the model re-added the work, and that is its call.
- **Emissions** — dropped OPEN rows retire explicitly (`todo_updated status="retired"` carrying the reason "Dropped from the agent's own revised plan."), genuinely new work appends with fresh ids (never renumbering, never colliding), matched open rows update status/outcome in place (a matched row keeps the drawn label — the panel renders on stable ids), and `todo_revised {added, retired, kept}` lands once per actual rewrite. Plan-family rows feed the loop's own close sets (`_plan_retired` — a retired row takes no more tool lifecycle: the cursor never completes one and the finalize sweep never re-opens it); the legacy fresh paths are unchanged (no live rows, or an explicit empty write → clear + create, because a list born that way has nothing to retire).
- **Schema** — `todo_write`'s tool schema documents the diff contract and accepts `expected_outcome` per row and `failed` as a first-class status; the tool's own description matches.

**B. Revised steps carry outcomes (the acceptance criteria following a revision).**

- A model-supplied `expected_outcome` on a new (or updated) row joins the acceptance contract (`trace.success_criteria` + `task_state.success_criteria`, bounded to the last 8, deduplicated) as `"<step> — done when: <outcome>"` — the gate judges the revised work by its own contract, and the objective-fidelity lane still guards the ORIGINAL ask.
- The gate's replan prompt now asks for a per-step done-when contract on every step it added or changed; `_parse_replan_contract` splits `step — done when: contract` into (steps, outcomes), backward-compatible (bare steps parse exactly as before with an empty outcome), and `_apply_plan_revision` carries each added step's outcome into its `todo_created` row. Revised steps hold outcomes too.
- Equivalence targets in the revision are the LIVE rows only: a replan step matching a RETIRED row is genuinely new work (the revision brought it back) and is added, not skipped.

**C. Self-grounding fence in the gate.** `verify.py`'s evidence flattening now excludes `todo_write`: the checklist's observation renders the model's own row labels and outcome contracts, so a revision-derived criterion would quote its own tokens back and verify itself — the same self-grounding the evidence gate forbids for the answer. Checklist rows are judged by the WORK's evidence, which is what remains after the exclusion.

**D. Found live by the new harness and fixed: the double todo bridge.** `chat.py`'s main text-chunk drain called `_bridge_todo_event(evt, ...)` TWICE per event (a legacy Session-27 site and a Session-359 site, both unconditional, both bridging the same event) — every todo event that reached the main drain landed twice on the wire and double-persisted. The new harness's exact-count assertions caught it (plan-2 created ×2, plan-1 retired ×2 on the wire while the loop logged one diff). Fixed: ONE bridge call per event, with a comment naming the defect class.

## The new standing harness

`scripts/live_test_todo_rewrite.py` (8765 fake-provider pattern, content-routed) asserts on the real SSE stream: **RW1** the Planner lane seeds the panel (exactly ONE `todo_cleared`, `plan-0` carrying its outcome contract); **RW2** the model's rewrite DIFFS — `plan-1` retires exactly once WITH its reason, `plan-2` ("Note the available memory too") appends CARRYING its `expected_outcome`, `plan-0` updates in place, no second clear ever fires; **RW3** `todo_revised {added: 1, retired: 1}` lands on the wire (generic obs_event wrapper — the panel derives its revision marker from the retired rows); **RW4** the revised contract gates the close — the answer is the honest echo of the REAL sysinfo reading and the tail is `✓ 2/2 criteria met (…)` listing both the drawn and the revised criterion, with no `[ACCEPTANCE GATE]` replan; **RW5** a retired row takes no more lifecycle (never ticked completed at close).

Two harness-building lessons are encoded in its docstring (they cost the session two debug loops): route the fake on the ASSISTANT's tool_calls in the history plus the payload's `tools` presence — the todo_write OBSERVATION echoes the plan rows verbatim (labels AND outcome contracts), so content-sniffing for "RAM" misfires on the checklist itself, and the consult's findings are INJECTED as a system-role message mentioning the read-only analyst, so the consult branch must be gated on `not tools` or the final answer call routes to it. And each handler must route on its OWN request body — `REQUESTS[-1]` races under ThreadingHTTPServer when the background Thinker consult overlaps the final answer call (both handlers read the other's payload; the observed symptom was the consult's JSON as the user-visible answer).

## Verification (the bar)

- Backend: **4,078 passed / 2 skipped / 0 failed** (15 new pins in `tests/core/test_todo_model_rewrite.py`: the pure diff — rephrase matching, retire-on-drop, closed-rows-never-churn, relisted-closed-arrives-as-new, fresh-id collision avoidance; the gate replan's done-when parsing — split variants, backward compatibility; the loop-level rewrite — diffs-instead-of-replace on the runtime branch, second write diffs against the model list, fresh-list and empty-write legacy paths, rewrite-over-synth-rows, retired-cursor-never-completes, outcome joins the contract and FAILS the gate when the work ignores it, gate-replan contract reaches the added row).
- E2E: **132 passed**. Frontend: **678 passed** (no frontend file changed — the retired-row rendering and revision marker S023 shipped are driven by the same `todo_updated status="retired"` events this work now emits from the model's trigger too).
- Ruff: clean on all touched paths. Eval suite: **13/13 PASS**, 0 unnecessary-question violations.
- Standing harnesses re-run: planner_lane, todo_rewrite (new), done_rules, goal_continuity, turn_close, prompt_structure, greeting_gate, arsenal_fixes, turn_trace — **ALL PASS**. thinking_block, stream_gating, replan_gate are real-provider harnesses (keys at `~/LocalMind/settings.json` / provider env) — unchanged in this sandbox, confirmed NOT a regression of this work by an A/B stash run (fails identically without the chat.py change); their real-provider run remains the standing owner's-box follow-up.

## What was deliberately NOT done

- A dedicated frontend `todo_revised` SSE handler: the panel's revision marker is derived from retired rows (S023's design), so a dedicated consumer would be dead surface today; the `todo_revised` counts ride the generic obs_event wrapper (Observe panel + trace) where S023's gate-path diff already lives. If the panel later wants counts-driven markers, the loop already emits the event.
- No change to `todo_write`'s emission when the model writes a FRESH list (no live rows) — clear + create stays, because there is nothing to diff.
