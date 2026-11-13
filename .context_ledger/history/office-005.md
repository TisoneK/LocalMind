# Office 005 — accomplishments record (permanent)

- Opened: 2026-11-02
- Closed: 2026-11-13
- Sessions: 21

The frozen office lives at history/office-005/ until it is zipped into
archive/office-005.tar.gz. This record stays in history/ forever — even after
the tarball is garbage-collected, the office is never forgotten. Not read at
session start; deliberate lookback only.

## Accomplished

- **The Planner lane on the production path:** every task turn now draws the
  real `{todo, outcome}` plan by model before the loop (fail-open lane,
  thinking-off, 12s; social / open-question / goal / sequence turns step
  aside). `plan_outcomes` seed both the panel's step contracts and the
  acceptance gate's criteria; `plan_objective` renders as the UNDERSTANDING
  context. The production runtime had passed `skip_planning=True` since the
  warm-kernel change, so the panel was showing `syn-` tool echoes instead of a
  plan — that dead branch is gone.
- **Plans that evolve:** a gate-triggered replan diffs into the live todo list
  instead of full-replacing it — dropped open rows gain `retired` status
  carrying the discovery, new work appends, closed rows never churn, and
  `todo_revised {added, retired, kept}` is emitted once per actual revision.
  A bounded objective-fidelity judge at the close returns FAITHFUL/DRIFTED and
  may issue one nudge — it never blocks.
- **The model's own plan rewrite** (`todo_write` mid-turn): diffs against the
  live panel (model list → planner rows → syn- fallbacks) on stable ids
  instead of silently full-replacing; revised steps carry outcomes
  (`expected_outcome` joins the acceptance contract, the replan prompt asks
  for per-step done-when), and `todo_write` is excluded from the gate's
  evidence because a checklist cannot verify itself.
- **Rehearsal hygiene:** the Thinker's fenced JSON rehearsal is stripped from
  the visible reasoning across chunk boundaries.
- **Formatting contract on every answer surface:** the response-formatting
  section previously existed only on the scoped-agent registry, so ordinary
  turns (parent warm-kernel, chat) carried none and the renderer had nothing
  to render — the owner's "the UI shows plain text" report. It now registers
  at the shared slot 405 on all three surfaces, after the tool index (so a
  SOCIAL contiguous-suffix cut can never drop it) and before style examples,
  with an explicit GFM pipe-table rule.
- **Renderer resilience:** two conservative repair passes for GLM-degraded
  shapes — full-width pipe/dash normalization scoped to leading-pipe rows and
  missing-delimiter-row insertion; well-formed tables are never re-delimited.
  A wire harness proved the transport was already clean (SSE + history
  byte-exact) before the contract work began.
- **Found live, filed:** the zero-tool forced-replan storm — an analyze-intent
  turn with a drawn plan whose model answers in prose measured 20 forced
  provider calls before the honest stop. Filed as a bounded-work item.
- **Fixed live:** the chat drain bridged every todo event twice (two
  independent bridge sites); one bridge per event now.
- **Standing live harnesses added:** `scripts/live_test_todo_rewrite.py` and
  `scripts/live_test_markdown_render.py`, both wired into the harness table in
  `system/live-testing.md`.
- **Housekeeping:** while closing the office, a prior session's ledger close
  that a crash had left uncommitted was committed and pushed, so no memory
  work was lost.

## Decisions still in force

- **ADR-41** — thinking policy on the answer path (per-call override; aux
  calls may run thinking-off).
- **ADR-66b** — turn-bus attribution: an answer is final when the reply is
  final; post-turn bookkeeping runs as detached lanes, never holding the
  transport; the user must never see "Working" after the answer is on screen.
- **ADR-67** — confirmable refusal: refuse only on a verified fact, name the
  fact and the confirming flag; never guess.
- **ADR-69 as amended** — explicit `fallback_to` only (no implicit
  keyed-provider tail); record the switch `{from, code, to}`; persisted
  identity stamps name the adapter that actually served the turn.
- **ADR-70** — where commands run and where installs land are user settings.
- **ADR-71** — the state engine is built beside the classic parent, importing
  only stable capabilities; the engine owns state, the model proposes moves;
  simulation is real read-only probing; hard budget with an honest `stopped`;
  read-only by construction in slice 1; every step is an `EngineEvent`;
  `Auto` is deliberately not built first.
- **ADR-72** — the state engine is environment-agnostic and owns its own
  architecture; LocalMind is its first adapter; no engine import of LocalMind.
- **Working agreements:** the live-testing bar is mandatory for loop / tool /
  adapter changes (`system/live-testing.md`; report live-verified vs
  unit-tested vs assumed); cure the disease, not single prompts; model- and
  environment-agnostic fixes — "there is no weak model", neutral terms only; a
  defect triggered by different wording gets a semantic or state check, never
  a wording list; push to main after each commit; two-surface commit prefixes,
  never mixed; explicit `git add` paths; roster check-in every session; never
  port 8000 (the owner's app runs there) — isolated 8765 + `LOCALMIND_HOME`
  only; no secrets in tracked files, ever; closeout leaves `git status` clean.

## Open threads

- **Re-seeded actionable backlog:** the state-engine follow-ons (in-app State
  Explorer + engine selector; execute-behind-confirmation slice with a second
  `Environment` adapter and persisted state; the Classic-vs-State benchmark);
  confirmable-refusal rollout; perspective/speaker-identity consistency; the
  zero-tool forced-replan storm bound; turn-bus lane expansion (Decider,
  parallel read-only lanes, per-provider concurrency budget); provider-health
  UI and per-provider budget; learning transfer at decision time;
  anti-sycophancy guard; turn economy for verification-heavy tasks;
  association-level grounding judge; feedback-turn routing; trajectory
  projection completion (`message.toolCalls` live vs reload shape);
  mode-gating mixed-intent effecting tools; reflective/identity turns must not
  reach for meta-tools; LocalMind as a consumer of the public engine repo.
- **Standing follow-up:** real-provider runs of the new harnesses
  (`live_test_markdown_render.py`, `live_test_todo_rewrite.py`) and the
  standing eval scoring run (`scripts/eval_suite.py --provider real`) on the
  owner's box — every sandbox run used deterministic fake providers because no
  key lives there. The open questions are whether glm-4.5-flash actually emits
  GFM tables under the strengthened contract and how often the degraded shapes
  still appear.
- **Knowledge worth keeping (not queue):** the prompt-size budget table
  requires a justification line per increase; renderer repair passes must stay
  conservative (only leading-pipe rows and missing delimiter rows are touched);
  a todo/stream event must be bridged exactly once per event, and a live
  harness is how that class of double-bridge is caught; a checklist cannot
  serve as evidence for its own acceptance gate.
- **Resolved this office (do not re-litigate):** the dead planner branch on
  the production path (fixed by the Planner lane); silent full-replace of the
  todo list (fixed by the diff rewrite); the missing formatting contract on
  ordinary answer surfaces (registered on all three).
