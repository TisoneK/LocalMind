# ADR-19 Design — Task-Aware Context Management (P0 slice)

**Status:** **LOCKED** (Session 159 — user settled all four decisions): 1. **Full P0 design** (build order steps 1-6: policy + compactor + summarizer + wiring + enablement + live smoke); 2. **Dispatcher emits explicit `task_type`** in the plan (alongside success_criteria — ADR-18 pattern); 3. **Per-task KEEP tables** (each task type overrides its own keep/drop markers); 4. **CAN DISCARD implemented but OFF by default** in P0 (stub-only behavior ships).
**Ledger:** `.context/memory/features/ledger.md` — verification-first-hardening
P0 is done; this is the next active feature.

---

## 1. Problem — the context is assembled positionally, not by task value

The user's thread (2026-08-12) framed the exact gap: "the same conversation
can produce different compressed contexts depending on the next task" — a
debugging agent needs stack traces + recent changes + tool calls verbatim; a
planning agent needs constraints + decisions + architecture; a researching
agent needs sources + claims + evidence. Today LocalMind compresses by
POSITION, not by VALUE:

| Mechanism | Rule today | What it ignores |
|---|---|---|
| `context_builder.build()` | token budgets: system never trimmed; tool result ≤35% of available; file ≤40%; history = leftover, **oldest-first trimmed** | task priority — a 40-token constraint line can be dropped while a 400-token resolved discussion survives |
| `context_compactor.simplify_tool_results()` | keep NEWEST **4** tool results verbatim; stub older (head+marker+tail, 600 chars) | task value — the test run that just failed might be 2 results back |
| `summarizer.maybe_compress_history()` | past **75%** of budget, LLM-summarize OLDEST **50%** with ONE generic prompt ("preserve key facts, preferences, decisions") | task type — debug vs plan vs research get identical summaries; no guarantee decision-changing lines survive |

The concrete lossy-compression risk the user named: a conversation where
"user wants PostgreSQL, rejected MongoDB, wants SQLite locally, production
uses PostgreSQL" collapses to "Database: PostgreSQL" — a constraint that
changes future decisions is gone.

## 2. What exists today (honest baseline)

- **Single assembly point:** `context_builder.build(ctx, model_context_window)`
  — called at `_pipeline.py:1546 / 2696 / 2901`. Budget math in
  `TOOL_RESULT_BUDGET_FRACTION=0.35`, `FILE_CONTENT_BUDGET_FRACTION=0.40`,
  response-reserve capped at 40% of window, history gets the remainder.
- **Deterministic per-tool-result compaction:** `simplify_tool_results()` —
  unconditional, synchronous, idempotent, preserves `tool_call_id`. Wired
  into `AgentLoop.run()` before each iteration's `chat_with_tools`.
- **LLM turn summarization:** `maybe_compress_history()` — 75% threshold,
  oldest 50% → one `[Conversation summary — earlier context]` system message.
- **Memory ≠ context:** `memory.py` `compose()` (intent-gated: only
  `_MEMORY_RELEVANT_INTENTS`; embedding recall; top_k=_MAX_FACTS),
  `warm_start_facts()` (recency 0.4 + importance 0.4 + access 0.2, no
  embedding — baseline for short queries), `consolidate()` (near-dup merge,
  janitor), `extract_facts_with_llm()` (durable-fact extraction, 5/turn cap).
  Retrieved facts are injected as a `## Retrieved memory` system section.
- **Per-agent context:** `agents/*/context_builder.py` (coding/research/
  browser/etc.) — playbook + memory facts (cap 10) + orchestrator plan
  (ADR-6/ADR-8 Phase 2). Workspace-state git/diff snapshot injected by
  `AgentLoop.run()` (Session 16), NOT duplicated here.
- **TaskState (ADR-18, just shipped):** objective / constraints /
  success_criteria / phase / progress / evidence / budget — injected once
  with the criteria contract, refreshed per iteration (`loop.py:1743`).
  **This is the natural carrier for "what task am I doing right now."**
- **Context-window meter (Session 150):** frontend shows used/total — the
  budget accounting exists; value-based allocation doesn't.
- **ADR-17 discipline:** `test_prompt_size_budget.py` + `test_intent_tool_scoping.py`
  lock the static floor. Any ADR-19 change to prompt composition must keep
  those green.

## 3. Design — the Context Planner

```
  TASK TYPE  (TaskState.phase + Intent, computed at the loop head)
        │
        ▼
  CONTEXT POLICY  (pure, deterministic — context_policy.py)
     per task type: MUST KEEP / SHOULD RETRIEVE / CAN SUMMARIZE / CAN DISCARD
        │
        ├──► selective compactor v2   (deterministic; stubs or DROPS by policy)
        ├──► task-aware summarizer v2 (LLM, per-task prompt + decision-line KEEP)
        └──► context_builder.build()  (budget allocation unchanged; KEEP list
                                        protected from the oldest-first trim)
        │
        ▼
        LLM
```

### 3.1 `context_policy.py` — pure data, no behavior change in P0

```python
@dataclass(frozen=True)
class ContextPolicy:
    task_type: str                    # debug | plan | code | research | chat | verify
    keep_markers: tuple[str, ...]     # content signals that MUST stay verbatim
    drop_markers: tuple[str, ...]     # signals that can be removed with a notice
    summary_prompt: str               # task-specific compression instruction
```

`policy_for(task_type) -> ContextPolicy`, seeded per task type:

| task_type | keep_markers (examples) | summary emphasis |
|---|---|---|
| debug | `Traceback`, `Error`, `failed`, `assert`, `exit code` | stack traces, recent code changes, tool calls, exact error text |
| plan | `constraint`, `must`, `cannot`, `rejected`, `decided`, `choose` | requirements, constraints, decisions, open questions |
| code | `diff`, `git`, file paths, `success_criteria` | current file state, conventions, verify-after-write |
| research | `source`, `claim`, `evidence`, URLs | sources, claims, evidence, dates |
| chat | — | preferences, facts about the user |
| verify | `pytest`, `test`, `criteria`, `passed/failed` | what was run, what passed/failed, unmet criteria |

Task type resolution: `TaskState.phase` (plan→plan, verify→verify) +
`Intent` (SHELL/CODE_EXEC→code, WEB_*→research, DEBUGGING-ish→debug,
CHAT→chat). Default: today's positional behavior — **P0 ships with
`policy_for` defaulting to the legacy keep-last-4 / oldest-50% rules, so
wiring it in is a no-op until a task type is explicit.**

### 3.2 Selective compactor v2 (`context_compactor.py`)

Extend `simplify_tool_results()` with a `policy: Optional[ContextPolicy]`:

1. **MUST KEEP** — tool results whose content matches `keep_markers` are
   preserved verbatim regardless of age (bounded: max `keep_last` protected
   results, so a pathological stream can't fill the window).
2. **CAN STUB** — everything else falls back to today's head+marker+tail.
3. **CAN DISCARD** — tool results matching `drop_markers` AND already acted
   on (older than the model's last tool-call round-trip) are replaced with a
   one-line `[tool result omitted — resolved]` notice. Discard is the ONLY
   new destructive behavior; it must be off unless a policy explicitly
   enables it (safest: P0 enables stub, leaves discard off).

Invariants preserved: `tool_call_id` always matches; already-stubbed
results stay stubbed (idempotent); small results untouched; no await.

### 3.3 Task-aware summarizer v2 (`summarizer.py`)

`maybe_compress_history(..., policy=...)`:

1. Use `policy.summary_prompt` instead of the single generic prompt.
2. **Decision-line preservation:** before summarizing the oldest slice,
   scan it for lines matching `keep_markers` (constraints, decisions,
   rejections — the PostgreSQL/MongoDB case). Those lines are extracted
   verbatim into a `[Preserved decisions]` block prepended to the summary
   message — compression becomes lossless **for decision-relevant content**.
3. Keep the 75% / oldest-50% trigger; the summary SYSTEM message stays a
   single `[Conversation summary — earlier context]` message so the rest of
   the pipeline (role handling, `_rough_token_count`) is untouched.

### 3.4 Builder wiring (`context_builder.py`)

Smallest-change rule: `build()`'s budget math stays. The policy only
(1) protects KEEP-listed history messages from the oldest-first trim
(they're moved ahead of the trim loop), and (2) if P0 ships discard,
filters drop-listed messages with the notice. The context-window meter
(Session 150) reports used/total as today; optionally gains a
`policy: task_type` line for observability.

### 3.5 Loop wiring (`AgentLoop.run()` + `_pipeline.py`)

- At the iteration head (next to the ADR-18 `is_done_fn` call / TaskState
  refresh), compute `policy = policy_for(task_state.phase, intent)` once per
  iteration and pass it to `simplify_tool_results()` (already called there)
  and `maybe_compress_history()` (already called at `_pipeline.py:1547/2697`).
- Default policy == legacy behavior, so Sessions 155-158 regression surface
  is zero until policies are explicitly enabled.

## 4. Build order (each step deterministic + unit-testable; live smoke last — flaw log)

1. `context_policy.py` — pure dataclasses + `policy_for()` + task-type
   resolution from `TaskState.phase`/`Intent` + default-to-legacy + tests.
2. Selective compactor v2 — `simplify_tool_results(policy=...)` keep/stub/
   discard + protocol-invariant tests (keep-last-4 as default fallback).
3. Task-aware summarizer v2 — per-task prompts + decision-line preservation
   + tests with a fake adapter (no real model needed).
4. Wire policy through `AgentLoop.run()` + `_pipeline.py` (default no-op)
   + regression: full suite.
5. Enable policies per task type (start: debug + verify — highest evidence
   value) + targeted tests.
6. Real-model smoke — reuse `scripts/smoke_gate.py` pattern; Zen still 429
   as of 2026-08-12 (Session 158); Ollama would unblock.

## 5. No-regression list (must hold)

- ADR-17 static floor: `test_prompt_size_budget.py`, `test_intent_tool_scoping.py`.
- ADR-18: TaskState injection + acceptance gate + replan (Sessions 155-157).
- Session 31/32: iteration caps + hit-limit wording + check-before-acting
  injection. Session 31 adapter fixes (trailing tool-role, reasoning-only
  Phase 1). Session 33 `_obs.all()`.
- `tool_call_id` protocol validity in every compaction path.
- `test_signal_fast_paths` / dispatcher cache — policy must not add an LLM
  call or slow the fast paths (pure Python, no awaits in the compactor).
- Summarizer failure semantics: any summary-generation failure returns the
  message list unchanged (existing behavior preserved).

## 6. Explicitly out of P0 (later slices)

- **Hierarchy (turn → session → project → long-term) with retrieval-by-level**
  — needs memory-level metadata + a level-aware retriever. P1.
- **Cross-session decision ledger** — durable store of "decisions that must
  never be compressed away." P1/P2.
- **LLM-guided value scoring** of every message — too slow for free-tier;
  the deterministic marker approach is the P0 trade (cheap, predictable).

## 7. Locked decisions (Session 159 — user answered all four)

1. **P0 scope: FULL P0 design** — implement build order steps 1-6,
   including per-task policy enablement and the live smoke.
2. **Task-type source: dispatcher emits explicit `task_type`** — added to
   the `execution_plan` JSON alongside `success_criteria` (same ADR-18
   parse path), stored on `OrchestrationPlan.task_type`, threaded into the
   loop. Fallback when absent: `TaskState.phase` + `Intent` → default
   (legacy no-op) policy.
3. **KEEP priority: PER-TASK TABLES** — `policy_for(task_type)` returns a
   policy whose keep/drop markers are task-specific; a global default
   table seeds each, per-task overrides win.
4. **Discard: OFF by default in P0** — the capability is implemented and
   tested, but no task type enables it until a real-model smoke shows it
   safe. P0 ships stub-only behavior.
