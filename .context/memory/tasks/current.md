# Current Task

**Status:** COMPLETE — Session 301 (2026-08-20). Restored the generic direct-conversation boundary instead of keeping the phrase-specific capability response patch.

## Product change
- Removed the capability-specific detector and deterministic capability catalog.
- Short context-backed conversational turns use one normal adapter chat call with recent history and a generic follow-up-aware prompt.
- Evidence-requiring, action-shaped, attachment, and tool-restricted turns remain on the parent/tool loop.
- Preserved lifecycle, stage timings, persistence, metrics, and workspace artifacts.

## Live verification
- Established isolated Claude harness: copied settings into isolated `LOCALMIND_HOME`, z.ai `glm-4.5-flash`, thinking enabled, shell enabled, port 8765, direct SSE/log inspection, cleanup.
- Real GLM generic shapes: `Tell me about yourself` (11.4s / 83 prompt tokens), `I had a long day` (13.5s / 143), and `Can you explain recursion simply?` (15.7s / 171) all used `fast_path=true` and returned useful direct answers.
- Final exact flow: `What can you do?` (14.3s / 83) followed by `Like what` (10.5s / 138) used the same generic path and produced concrete non-repeated examples.
- Real read-only tool request remained `fast_path=false`, `mode=execute`, made four shell calls, adapted paths, and returned the actual listing.

## Verification
- Focused: 112 passed.
- Full CI: 1996 backend passed / 2 skipped; Ruff clean; TypeScript clean; ESLint 0 errors / 71 existing warnings.
- First full-gate run caught five regressions caused by over-broad history follow-up routing; the structural follow-up guard fixed them before the final green run.

**Feature:** none
**Report:** `.context/memory/reviews/2026-08-20-review-70.md`
**Working tree note:** generated untracked `backend/MagicMock/` is excluded.
