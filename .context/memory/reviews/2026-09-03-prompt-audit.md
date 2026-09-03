# Prompt Assembly Audit — 2026-09-03 (P0 Context Engineering milestone)

**Trigger:** user's screenshot — 3 trivial turns → 19.5K total tokens, 19.4K
prompt, 164 completion, Context meter 59%. User directive: measure before
re-architecting; Prompt Token Instrumentation is the first component of the
proposed milestone. User also ruled: "the issue is not about direct vs agent
or tools — the issue is input tokens regardless."

## Method

- New env-gated audit hook in `backend/src/adapters/openai_compat.py`
  (`LOCALMIND_PROMPT_AUDIT=<file>`): records the EXACT outgoing payload of
  every model call at the single send funnel (`_send_streaming_with_retry`,
  attempt 0 — before any retry-field mutation), one JSONL line per call with a
  per-section token estimate (chars/4, calibrated against provider-reported
  prompt_tokens), plus the full payload to `.last-payload.json`.
- Runner: `scripts/live_test_prompt_audit.py` (isolated 8765 harness,
  LOCALMIND_HOME scratch, never 8000). Provider: bankofai/qwen3.8-flash.
- Scenario: the user's exact 3 trivial turns in one session, then a real
  research turn for contrast.

## Findings (live, qwen3.8-flash, 2026-09-03 13:19-13:20)

**10 model calls, ~50.3K prompt tokens total across the 4-turn session.**

| Call | Total | System | Tools | History | Current |
|---|---|---|---|---|---|
| pre-init chat (turn 3) | 723 | 505 | 0 | 0 | 218 |
| agent tools iter 1 (turn 3) | 6189 | 2671 | 3332 (18 defs) | 38 | 148 |
| classifier chat | 153 | 149 | 0 | 0 | 4 |
| pre-init chat (turn 4) | 790 | 505 | 0 | 0 | 285 |
| agent tools iter 1 (turn 4) | 6416 | 2775 | 3332 | 120 | 189 |
| agent tools iter 2 | 7292 | 2775 | 3332 | 1069 | 116 |
| acceptance/chat | 874 | 505 | 0 | 0 | 369 |
| agent tools iter 3 | 8200 | 2775 | 3332 | 1977 | 116 |
| agent tools iter 4 | 9764 | 2775 | 3332 | 3541 | 116 |
| agent tools final | 9868 | 2775 | 3332 | 3677 | 84 |

### Where the tokens actually go

1. **Tool schemas: ~3.3K tokens (~3.4%) carried on EVERY agent-loop call.**
   18 tool definitions — the constant per-call floor for any tool turn. With
   ~16 more long-tail tools available only via describe_tool (ADR-40), the
   surfaced 18 are the "core" set; their descriptions average ~185 tokens.
2. **System prompt: ~2.7K per agent call, ~0.5K per direct call.** The
   agent-phase system prompt (8.5KB chars) includes the Parent-Agent Contract,
   safety workflow, capabilities, and tool summaries.
3. **Tool-result history grows fast: 38 → 3677 tokens in 4 agent
   iterations.** Each web_fetch result dumps its full text into history.
   THIS matches the user's screenshot signature: per-call prompt grows each
   turn as history accumulates — 3 turns ≈ 6.4K avg/turn is consistent with
   one research-flavored turn + tool results in history, not with the trivial
   turns themselves.
4. **Trivial turns are already optimal: "Hi"/"How are you" make ZERO model
   calls** (deterministic canned replies, S206 boundary verified live — 0.29s
   and 0.15s). The screenshot's 19.4K cannot come from current-main trivial
   turns; it is either an older build, a non-trivial turn, or per-session
   accumulation across several real turns.

### The compounding pattern (the real P0)

Per-call prompt = 2.7K (system) + 3.3K (tools) + growing history. A single
research turn costs 6.2→9.9K per iteration, and its full tool-result history
is then re-sent on every subsequent turn of the session. The user's
"conversation-centric vs context-centric" framing is confirmed by the data:
everything available is re-sent every call; nothing is selected.

## Reduction targets (priority order, measured impact)

1. **Tool-result history compaction** (~-2→3.5K per call after research):
   tool results older than the immediately-previous iteration should collapse
   to summaries/extracted facts. Largest and fastest win; bounded blast radius
   (tool results are data, not instructions).
2. **Tool schema diet** (~-1.5→2K per call): descriptions of the 18 core
   tools are verbose; ADR-40's describe_tool pattern can extend to more of
   the core (keep web_search/memory_op/shell; push file_task/browse/code_exec
   variants behind on-demand load). Constraint: ADR-40 guardrail — never cut
   schemas without live-verified tool-selection on a weak model.
3. **System prompt diet** (~-0.8→1K per call): audit the agent-phase prompt's
   sections against observed failure modes; several "capability notes" are
   restated in multiple sections.
4. **Session-level context budgeting** (structural): the six-layer model
   request (core system / current task / required capabilities / relevant
   history / relevant memory / task state) — the user's proposed
   Context Budget Manager as a first-class component.

**Targets (user's):** trivial turn ≈ 0 calls (ALREADY MET on main); simple
conversation 300-1K (met: 723-874 pre-init calls, but the agent path costs
6K+); normal question 1-3K; research turn should stay ≤5K/iteration after
(1)+(2) (from 9.9K).

## Infrastructure delivered

- `backend/src/adapters/openai_compat.py`: `_PROMPT_AUDIT_ENV` audit hooks
  (`_audit_enabled`/`_audit_path`/`_audit_tokens`/`_audit_breakdown`/
  `_audit_record`), env-gated, zero-cost when off, never breaks chat (all
  exceptions swallowed at debug level).
- `scripts/live_test_prompt_audit.py`: reproducible audit runner.
- Evidence: `scratch/prompt-audit.jsonl`, `scratch/prompt-audit.jsonl.last-payload.json`,
  `scratch/server-prompt-audit.log` (gitignored).

## Verification

- Live: the table above IS the live verification (the audit ran against the
  real provider in the isolated harness).
- Unit: 121 adapter tests pass; ruff clean (baseline for the file was already
  clean); compile OK.
- Known limitation: token counts are chars/4 estimates. Provider-reported
  prompt_tokens are available per call (log line `[agent.loop] cache:` and
  usage chunks) for calibration; the breakdown proportions are the actionable
  part.

## Decision requested (ADR-57 slice 3 competes)

Adopt **Context Engineering & Prompt Efficiency** as the v0.5.x P0 milestone
(starting with reductions (1)+(2)), per the user's framing. ADR-57 slice 3
(concurrent pre-tool Thinker) remains queued; the Thinker post-tool consult
(5s) is now measurable against this new token-cost lens.
