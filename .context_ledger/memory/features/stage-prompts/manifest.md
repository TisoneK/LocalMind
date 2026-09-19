# Feature: stage-prompts

Goal: stage-aware model input — the FULL system prompt only where the model must learn who it is and
what it can do (the cold-start act call); a small STRICT STRUCTURED instruction (Stage / Goal / Done so
far / one positive Decision, only the tools that decision needs) for every later stage (continue,
recover, answer). Owner intent (2026-09-19): quality first, token consumption second, time third.

**Started:** 2026-09-19 (S024, Imani)
**Status:** **BACKLOGGED — resume when a second model/provider is available** (owner call, 2026-09-19).
Only glm-4.5-flash is available now, and z.ai throttles (~5 x 429 per run), which removed the power
to compare answer quality.

## Shipped from this feature's groundwork (on main)
- `6899023a` structured stage cards replace the paragraph nudges and the per-iteration SYNTHESIS
  REMINDER; removes a nonexistent tool name (`file_read`) and a describe_tool contradiction from them.
- Input-quality fixes found by capturing real requests: `bddf663a` (user message sent once, not twice),
  `90cda747` (Thinker receives the user's real request, not a recovery nudge).
- `d61d1d12` root cause of "empty response after reasoning" on glm (whitespace content delta made the
  adapter drop the tool call); `2a5b3877` post-answer services share a 90 s budget; `e024a05a` git tool
  honors `path`.

## What the experiment established (glm-4.5-flash, fixed fixture, serial, n = 4/5/5)
- System prompt 11.3k -> 4.5k chars (-60%); tool schemas -31% (one-sentence descriptions).
- Prompt tokens per run: 39.9k -> 27.2k (compact system, -32%) -> 24.5k (+ compact schemas, -39%).
  Suggestive (perm p 0.07 / 0.14), not conclusive.
- Quality: evidence gathered was 100% for folders and commit in every variant; count reached ~40% in
  every variant; evidence-all-correct 2/4 vs 2/5 vs 1/5. No sign compact hurts, none that it helps.
- NOT proven: that compact strict input improves quality. Not built: the product assembler (variants
  were emulated by rewriting requests in the harness).

## To resume
1. Run `harness/` with N >= 10 per variant on a non-throttled provider (a second model/provider, or
   off-peak); score clean finals only; also run a different task shape (write/edit) so one prompt does
   not overfit.
2. If compact wins (or ties at lower token cost): build a stage-aware prompt assembler behind a setting —
   full prompt at the cold-start act call, compact strict card afterwards, identity + safety core in every
   stage. Live-verify tool SELECTION (ADR-40) on a flash-tier model AND a second model; respect ADR-41
   (do not disable GLM thinking), ADR-46 (never fail open to execute), ADR-53 (Parent only), ADR-61.
3. Owner-visible rollout (ADR-64 spirit): no silent prompt swaps.

Related: see `office/reviews/2026-09-19-review-s024-decision-core-survey.md`
(survey + traces + experiment) and backlog `B-2026-09-19-6`.
