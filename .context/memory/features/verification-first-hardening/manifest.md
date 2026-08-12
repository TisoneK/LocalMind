# Feature: verification-first-hardening

Goal: implement **ADR-18** — make "done" a **checkable contract, not a model
assertion**. Code-verified gap behind the user's "it feels like generative AI
rather than agentic AI" observation (Session 152): every per-agent `is_done()`
is a scaffold returning False (`agents/*/is_done.py`), so the loop terminates
on model assertion or the iteration cap; there is no `Goal`/`success_criteria`
object in `backend/src`; the VerifierAgent is an intent-routing destination,
not an acceptance gate; task state is scattered across `ExecutionGraph` /
`AgentTrace` / todo plan / objectives store; nothing writes failure memory at
loop end. ADR-18 builds on ADR-5 (closed loop), ADR-6 (multi-agent), ADR-8
(agent-centric routing), ADR-10 (Observe→Think→Decide→Act→Observe→Verify),
ADR-16 (objective loop), ADR-17 (prompt budget) — it supersedes nothing.

Program phases (each real-model tested per the flaw log before shipping):

- **P0 — Acceptance gate** (highest leverage; next session): (a) planner emits
  typed success criteria alongside the plan; (b) first-class `TaskState`
  (objective, constraints, phase, completed/pending/failed work, evidence,
  budget, success criteria) consolidated + injected into context; (c) real
  `is_done()` implementations replace the stubs — check tests pass, file
  exists with content, git diff contains the expected change, HTTP status, no
  ERROR in output — with the existing evidence-quoting Worker-report gate as
  the non-testable fallback; (d) gate failure → explicit verify→replan,
  bounded by existing iteration caps.
- **P1 — Verifier as a stage, not a destination:** promote VerifierAgent from
  `Intent.VERIFY` routing to a per-run acceptance stage for high-stakes
  intents; implement real `is_verifier_done`.
- **P2 — Failure memory:** append what-failed-and-why at loop end (ADR-7
  learning-step wiring); read back for repeated patterns.
- **P3 — Close remaining transitional wiring:** delegation streaming/UX,
  remaining AgentLoop glue (adr-8 manifest open items).

**Started:** 2026-08-12 (Session 152 — ADR-18 + backlog + this manifest; no
product code)
**Branch:** main
**Status:** P0 IMPLEMENTED (Sessions 155-157, B-2026-08-12-1): TaskState +
verify.py + AgentTrace fields (155, `d55c0e6`); is_done() wired at the
iteration head + success_criteria schemas on dispatcher execution_plan AND
create_plan tool (156, `63dd038`); acceptance gate at the final-answer path
+ explicit time-boxed replan + honest unmet report at cap (157, `e7d7df1`).
Session 173 (`1b348dd`): gate wired into the engine's DIRECT AgentLoop path
(was dead code when agent selection fell through). Full suite 1475 green.
**P1 IMPLEMENTED (Session 174, `adr-18-p1`):** real `is_verifier_done`
replacing the stub, shared `verify.criteria_gate(trace, unmet_label)`
helper (coding + verifier is_done both delegate — no drift), engine
`_acceptance_gate_for(intent)` picks the VERIFIER gate for high-stakes
intents (FILE_WRITE/FILE_EDIT/CODE_EXEC), and the SINGLE_TOOL fast path
records its engine pre-dispatched `initial_tool_result` as a `trace.step`
so fast-path criteria (dir listing, git, URL fetch) can VERIFY —
"list projects in dev" now terminates at the iteration head with zero
model calls and `✓ 1/1 criteria met`. Full suite **1481 green**, ruff
clean. Remaining phases: P2 (failure memory), P3 (transitional wiring).
**No-regression list (must hold after every phase):** iteration caps (8/180s)
+ hit-limit fallback wording (Sessions 31/32); check-before-acting `safety.md`
injection (Session 32); trailing-tool-role + reasoning-only Phase-1 adapter
fixes (Session 31); `_obs.all()` not `drain()` (Session 33); ADR-17 call
collapse + signal fast paths; evidence-quoting Worker-report gate; per-agent
`max_iterations` (8-20) honored by `AgentLoop.run()`.
**Flaw-log rule:** any phase touching the loop/model path MUST be real-model
tested before commit — Zen free tier was 429-rate-limited on 2026-08-11;
attempt the live smoke first, do not ship untested (Session 116 lesson).
**Baseline (Session 152):** backend 1293 tests, ruff clean, tsc clean, eslint
0 errors (61 warnings), frontend 95 tests.
