# Feature: stage-prompts

Goal: stage-aware model input — the FULL system prompt only where the model must learn who it is and
what it can do (the cold-start act call); a small STRICT STRUCTURED instruction (Stage / Goal / Done so
far / one positive Decision, only the tools that decision needs) for every later stage (continue,
recover, answer). Owner intent (2026-09-19): quality first, token consumption second, time third.

**Started:** 2026-09-19 (S024, Imani)
**Status:** **ACTIVE again 2026-09-20 — DeepSeek (deepseek-chat) is available** (was backlogged 2026-09-19 for lack of
a second model; glm-4.5-flash on z.ai throttles ~5 x 429 per run). First DeepSeek round done, see below.

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

## DeepSeek round (2026-09-20, S024) — 90 serial interleaved runs, N=15 per cell, no rate limits
Frozen-snapshot code (`eedb787d`), fixed fixture, two task shapes. A = current input, C = compact strict
system prompt, D = C + compact tool schemas.
- **Lookup (3-part read-only): A 13/15 vs C 0/15 vs D 0/15 (Fisher p < 0.001).** The compact prompts
  narrate the next step and END THE TURN ("I have the folder list. Now I need the commit and the count.").
  My compact head dropped the original prompt's explicit multi-part rule ("not done until EVERY part is
  answered; act instead of announcing"): it is load-bearing. **Compaction by trimming is refuted; compaction
  that preserves the rules is untested.**
- **Write (create file + read back): A 15/15, C 14/15, D 15/15** — no quality difference; input chars -12% (C, n.s.)
  and -24% (D, p = 0.008); D/C ~2 s slower (n.s.).
- **A byproduct beat both variants:** A's FINAL answers were right only 5/15 although its evidence was right 13/15 —
  `simplify_tool_results` cut older tool results mid-list (415-char folder listing). Fixed in `28c7eaae`
  (budget-gated stubbing): final answers 5/15 -> 14/15 (p = 0.0017), turn 9.8 s -> 6.4 s, input -21%. Two models
  had shown symptoms (glm invented `theta`, DeepSeek reported 4 folders).

## Next (revised)
1. Rebuild C keeping EVERY load-bearing rule of the full prompt (multi-part completion, act-not-announce,
   anti-hedging, tool-selection hints, safety) and compress only wording/duplication; re-run lookup + write
   (+ a third shape: multi-step edit) on DeepSeek, N >= 15. Success = no loss on lookup AND fewer tokens.
2. Only then consider the stage-aware assembler (seam: `_iter_tools` / `iteration_messages` per call in `loop.py`,
   next to the ADR-61 answer-only call; the stable system prompt is deliberately byte-identical for provider caching).

## Original resume notes (pre-DeepSeek)
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
