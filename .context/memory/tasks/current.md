# Current Task

**Status:** IDLE — Session 307 (B-2026-08-20-6) implemented + unit-verified; new finding B-2026-08-20-7 backlogged.

## Session 307 outcome
- Implemented `prose_commits_to_tool_action` detector in `core/agent/loop.py` + wired into `_acceptance_gate_at_final_answer`. Parent-scoped, no-tool-call-guarded, one-shot bounded, iteration-capped.
- 17 new tests (11 detector unit + 6 gate integration); 1003 broad regression pass; ruff clean.
- Live-verified on z.ai/glm-4.5-flash (2 traces): boot + health + tool execution all proven. The detector did NOT fire on either trace because the EXISTING `_is_tool_talk` path (`core/agent/text_tools.py`) caught the prose preamble at the initial-buffer stage first. The new detector is a **backstop** for phrases the existing regex misses (notably "describe" verb + tool name — "Let me first describe the shell tool" doesn't match the existing `(use|call|invoke|run)` verb alternation).
- **New finding (B-2026-08-20-7):** both live traces ended with 0-char final answers despite real tool execution. The recovery cap (2 per turn) is too tight for weak models that need multiple empty-response rescues. Backlogged.
- review-74 records the implementation + live evidence + the backstop finding.

## Next Parent-only implementation slices
- **B-2026-08-20-7 (next session):** fix the empty-final-answer after recovery-cap-exhaustion issue. Options: raise cap to 3-4 for parent turns, add a final synthesis-from-evidence call that doesn't count against the budget, or detect "tools ran but no synthesis" and force one. Live-verify on glm-4.5-flash.
- **B-2026-08-20-6 follow-up:** extend the existing `_is_tool_talk` regex to include "describe" so the pattern is caught earlier (before prose streams to the user).
- **B-2026-08-20-3:** continue maturing the single Parent (ADR-53).
- **B-2026-08-20-4:** frontend should render `parent_ready` / `parent_degraded_reason`.
- **B-2026-08-20-5:** tune ParentSession compaction thresholds.

**Feature:** none (idle)
**ADR:** ADR-54 (ParentSession), ADR-53 (Parent-only), ADR-52 (warm kernel)
**Review:** `.context/memory/reviews/2026-08-20-review-74.md`
