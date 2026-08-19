# Current Task

**Status:** IDLE — Session 298 done (2026-08-19). Recovery arc complete + live-
verified. No task in progress.

## Recovery arc shipped (root-cause, not symptom patches)
- ADR-50 (`764b0a8`) — general model-agnostic tool-error recovery (classify every
  error_type → concrete [RECOVERY] directive).
- `b69329e` (B-2026-08-18-10) — shell surfaces timeout/nonzero-exit as a real
  error so the recovery layer engages.
- `0bb0126` (B-2026-08-18-11) — capture the reasoning channel + synthesize a real
  answer from reasoning+evidence instead of empty_response (user's hypothesis
  confirmed live); shell timeout now a configurable Settings field (default 45).

## Next (open, no user decision pending)
- B-2026-08-18-4 (guaranteed weather card), -6 (synthesis grounding).
- §40 efficiency roadmap: B-2026-08-17-8..12.

**Feature:** none
