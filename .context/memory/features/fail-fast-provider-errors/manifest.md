# Feature: fail-fast-provider-errors

## Goal

Implement ADR-32: provider errors that are terminal before generation must surface in the first substantive-turn round-trip instead of being swallowed into the parent loop or delayed by retries.

## Status

**Complete — Session 220 continuation, 2026-08-14.**

## Commits

- `1762509` — adapter-level permanent quota/billing 429 classification.
- `6014254` — loop/runtime propagation, shared terminal classifier, extra-request correction, and regressions.

## Delivered contract

- Exhausted-quota/free-tier 429, 401, 402, and 403 errors terminate the first provider path.
- Transient per-minute 429s retain adapter retry/backoff behavior.
- Planning no longer swallows terminal provider errors.
- Parent runtime error chunks reach the existing canonical SSE error-card boundary.
- Greetings remain deterministic and zero-provider-call.

## Verification

Backend CI: 1,773 passed / 2 skipped. Frontend: 178 passed; TypeScript/build passed; Ruff clean; ESLint 0 errors / 64 existing warnings. Live provider verification remains deferred until safe credentials are available.
