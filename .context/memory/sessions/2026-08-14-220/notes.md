# Session 220 — ADR-32 completion notes

The prior Claude Code session committed the adapter-level permanent-quota 429 classifier as `1762509` and ran out of tokens during closeout. This continuation completed the loop-level remainder.

## Root cause

`AgentLoop._plan_stream()` logged provider error chunks and continued. If the parent loop later received an error chunk with `done=True`, `AgentRuntime` skipped it as an internal completion marker and produced the generic no-usable-answer fallback. The canonical error normalizer already existed at the API boundary; the missing work was preserving the error until that boundary.

## Implementation

- Added `is_permanent_quota_429()` and `is_terminal_pre_generation_error()` to `core/error_normalizer.py`, reusing ADR-21 envelope extraction and ADR-20 normalization.
- Added `TerminalProviderError` to `AgentLoop`; terminal planning errors propagate instead of being swallowed. Transient planning errors retain the existing recovery path.
- Updated `AgentRuntime` to forward `StreamChunk.error` immediately and to convert a propagated terminal provider exception into an error chunk.
- Corrected the adapter's permanent-429 response handling so it does not issue an extra request after the first permanent failure.
- Added focused loop, runtime, and classifier regressions.

## Validation

`sh scripts/ci-check.sh`: 1,773 backend tests passed, 2 skipped; Ruff clean; frontend TypeScript clean; ESLint 0 errors / 64 warnings. Frontend Vitest: 178 passed. Production build passed. Focused ADR-32 tests: 70 passed.

No live-provider smoke was possible because credentials were unavailable. The existing `Hi` zero-provider-call test remains green.
