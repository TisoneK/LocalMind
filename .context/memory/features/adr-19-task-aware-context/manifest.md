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
**Status:** **COMPLETE — ALL PHASES SHIPPED (Sessions 160-163, 177-179).**
  - P0 (160-163): context_policy.py + dispatcher task_type (`17b3624`),
    policy-aware compactor v2 (`42053dd`), task-aware summarizer v2 with
    decision-line preservation (`89f5d77`), loop+engine wiring default-no-op
    (`53210be`). Full suite **1407 green**.
  - P1 hierarchy + level-aware retrieval (Session 177, `5f4f8a8`):
    MEMORY_LEVELS (turn/session/project/long_term), level_priorities(),
    store(level=)/compose(levels=)/retrieve_for_task(), near-free level-
    aware re-retrieval after the pre-started parallel recall. 18 tests.
  - P2 cross-session decision ledger (Session 178, `c348633`):
    decision_ledger table (no FK to sessions — decisions outlive the
    session), record_decision (7-day dedup, 180-day prune),
    task-filtered recall_decisions, summarizer decision_sink write path,
    engine read path into memory_facts. 15 tests.
  - P3 LLM value scoring opt-in (Session 179, `e2caafb`):
    LOCALMIND_LLM_VALUE_SCORING flag (default off), score_messages()
    bounded call (8s/40-msg/400-char, any failure → deterministic
    fallback), summarizer compresses lowest-value slice, 8+ message
    pre-gate so small chats never pay the scoring call. 14 tests.
  - **Final: full backend suite 1550 green**, ruff clean.
Live smoke (Sessions 164/177-179) provider-blocked — Zen 429
FreeUsageLimitError, same as Sessions 151/158; retry when Zen recovers
or install Ollama. P1 is deterministic (no new LLM calls), P2's read
path is deterministic + fake-adapter summarizer tests, P3's fallback
contract is fake-adapter tested — per the flaw log, live E2E remains the
only pending item and is blocked on provider availability, not code.
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

**Session 186 hardening (2026-08-13, post-close):** ADR-19 x ADR-22 re-key — level-aware memory retrieval + decision-ledger recall + decision sink + summarizer policy now key off the task type the agent settles on during planning (`resolve_task_type(hint, intent)`), not the dispatcher hint (demoted by ADR-22). Explicit canonical hints still win except a 'chat' hint on non-CHAT routing. Full backend 1635 green.
