# Feature: adr-19-task-aware-context

Goal: implement **ADR-19** — make context allocation **task-aware** instead of
positional. The user's thread (2026-08-12, Session 159) framed it precisely:
"the same conversation can produce different compressed contexts depending on
the next task." Today LocalMind compresses by position: `context_builder.build()`
trims history oldest-first, `simplify_tool_results()` keeps the newest 4 tool
results verbatim, `maybe_compress_history()` LLM-summarizes the oldest 50%
with ONE generic prompt. Nothing maps `MUST KEEP / SHOULD RETRIEVE /
CAN SUMMARIZE / CAN DISCARD` to the current task type (debug/plan/code/
research/chat/verify). Lossy-compression risk the user named: "user wants
PostgreSQL, rejected MongoDB, wants SQLite locally" collapses to "Database:
PostgreSQL" — a decision-changing constraint silently dropped.

Builds on ADR-17 (prompt budget — ADR-19 is its qualitative complement: cut
the floor AND allocate the remainder by task value), ADR-18 (TaskState —
its `phase` is the natural task-type carrier), ADR-6/ADR-8 (per-agent
context builders). Supersedes nothing.

**Started:** 2026-08-12 (Session 159 — design doc written, no code)
**Branch:** main
**Status:** P0 IMPLEMENTED (Sessions 160-163): context_policy.py + dispatcher
task_type (`17b3624`), policy-aware compactor v2 (`42053dd`), task-aware
summarizer v2 with decision-line preservation (`89f5d77`), loop+engine
wiring default-no-op (`53210be`). Full suite **1407 green**, ruff clean.
Live smoke (Session 164, `scripts/smoke_gate.py` + task_type check)
provider-blocked — Zen 429 FreeUsageLimitError, same as Sessions 151/158;
retry when Zen recovers or install Ollama. Remaining: P1 hierarchy,
P2 cross-session decision ledger, P3 LLM value-scoring (all explicitly out
of P0 in design.md §6).
**No-regression list (must hold after every phase):** ADR-17 static floor
(`test_prompt_size_budget.py`, `test_intent_tool_scoping.py`); ADR-18
TaskState + gate + replan (Sessions 155-157); Session 31/32 iteration caps +
hit-limit wording + check-before-acting; Session 31 adapter fixes; Session
33 `_obs.all()`; `tool_call_id` protocol validity in every compaction path;
summarizer failure semantics (unchanged list on any error); signal fast
paths stay zero-LLM.
**Flaw-log rule:** any phase touching the loop/model path MUST be
real-model tested before commit; Zen free tier was 429-limited on
2026-08-11 and 2026-08-12 — the deterministic compactor phases (1-2) don't
need a live model; the summarizer phase (3) tests with a fake adapter; the
final live smoke reuses `scripts/smoke_gate.py` when a provider recovers.
