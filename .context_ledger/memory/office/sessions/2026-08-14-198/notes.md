# Session 198 notes

The user's screenshot showed a weather answer for Kitengela that cited August 8 even though the request was made on August 14 and the search output included a same-day August 14 result. The repository clock and Git state were current; the defect was that the synthesis layer had no deterministic freshness gate.

Implemented freshness-aware extraction in `backend/src/core/agent/synthesizer.py`. Time-sensitive queries are detected, explicit dates are parsed from numbered search-result blocks, and stale dated blocks are excluded when a same-day block is available. If every dated block is non-current, the synthesizer returns a gap report instead of presenting old evidence as current. Non-time-sensitive and undated searches retain the existing behavior.

Added `tests/core/test_synthesizer_freshness.py`: four focused regression tests cover filtering, synthesis prompt contents, and stale-only refusal. Full CI passed with 1752 backend tests, Ruff clean, frontend TypeScript clean, and ESLint 0 errors / 64 existing warnings. No real-model call was needed because this is a deterministic post-search evidence-selection boundary; the reported output was reproduced from the captured search result.
