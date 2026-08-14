# Current Task

- **Session:** 220 (NOT STARTED — resume handoff; user ran out of tokens mid-request)
- **Feature:** fail-fast-provider-errors
- **Agent:** (next agent) | **Platform:** macOS 15
- **Role:** engineer
- **ADR:** **ADR-32** in `.context/memory/plans/decisions.md` — read it first.

## Target (implement ADR-32)

**Fail fast on pre-generation provider errors.** Today, when the provider
returns a free-usage-limit / rate-limit (429), auth (401), or payment
(402) error, the app runs the whole agent-loop lifecycle (>20s) and only
surfaces the error at the end. The user wants the "understanding /
acknowledge the request" step to be a REAL provider call so these errors
surface in the **first round-trip (ms)**, as the canonical error card,
instead of after a dead wait.

## Where it breaks (verified Session 219)
- `backend/src/core/agent_runtime.py:562-563` — the acknowledgement is a
  deterministic lifecycle status emitted BEFORE the first model call.
- First real provider call: `agent_runtime.py:394` and `:639`
  (`clock.start("generate")`).
- `backend/src/core/thinking_dispatcher.py` emits `acknowledgement` from
  ZERO-LLM signal fast-paths (lines 449/476/518) + the profile (329) — so
  signal/cached turns make no provider call until deep in the loop.

## Plan (see ADR-32 for full detail)
1. Read ADR-32, ADR-20 (`adr-20-error-normalization`), ADR-21
   (`adr-21-provider-agnostic-errors`) — reuse the normalizer + provider-
   envelope classifier. Do NOT re-derive error parsing.
2. Classify provider errors: **terminal pre-generation** (429 exhausted /
   401 / 402 / 403) vs **transient/retryable** (keep the existing adapter
   429 retry-with-backoff).
3. Make the first substantive-turn provider round-trip fail fast: when the
   dispatcher/"understanding" call (or a cheap bounded preflight for
   signal/cached fast-paths) raises a terminal pre-gen error, emit the
   canonical error card as a **terminal SSE event immediately** and end the
   turn — do not fall back into the full loop.
4. **Do NOT regress** the deterministic conversational boundary: `Hi` /
   greetings must still make ZERO provider calls (Session 206) — no
   preflight for trivial turns.
5. Regression tests: (a) mocked adapter raising 429 on the first call →
   terminal error SSE within ONE round-trip, not after a full loop;
   (b) `Hi` still makes zero provider calls; (c) a transient error still
   uses the retry path.
6. Full `sh scripts/ci-check.sh`; report in `.context/memory/reviews/`;
   changelog (user-facing: "usage-limit/auth errors now appear instantly").

## Status
- **in progress (handoff)** — ADR-32 written + committed this session; NO
  code written yet. Backend-only change (no frontend — the error card path
  from ADR-20 already renders it).
- Push policy: push to main after each commit.
