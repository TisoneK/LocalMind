# Current Task

**Status:** IDLE — Prompt Assembly Audit delivered (Session 409 addendum 4,
P0 Context Engineering milestone, step 1 of the user's plan). The EXACT
outgoing payload of every model call is now instrumented (env-gated adapter
hook) and measured live: ~50.3K prompt tokens across a 4-turn session;
trivial turns already make ZERO model calls (S206 holds); the real bloat is
the fixed ~6K/call floor (3.3K tool schemas + 2.7K system prompt) plus
monotonic tool-result history growth (38 -> 3677 tokens in one research
turn, re-sent on every subsequent call). Report:
`.context/memory/reviews/2026-09-03-prompt-audit.md`. Awaiting user decision
on the milestone + reduction order (report's "Decision requested").

**Feature:** none

## Notes for the next session

- **If the user green-lights reductions:** start with tool-result history
  compaction (largest, bounded blast radius), then tool-schema diet (extend
  ADR-40 describe_tool to more core tools — CONSTRAINT: ADR-40 guardrail,
  live-verify tool SELECTION on a weak model after any schema cut), then
  system-prompt diet. Re-run `scripts/live_test_prompt_audit.py --adapter
  bankofai` before/after — the audit harness IS the verification tool for
  this milestone.
- **Prompt-audit usage:** set `LOCALMIND_PROMPT_AUDIT=scratch/prompt-audit.jsonl`
  in the harness env; JSONL per model call + `.last-payload.json` full dump;
  `[prompt-audit]` lines appear in the server log. Zero cost when unset.
- **Live-test providers (2026-09-03, re-probed):** bankofai free models =
  **hy3, glm-5.3-flash, qwen3.8-flash** (`--adapter bankofai --model X`);
  everything bigger 403s "Deposit required"; deepseek-v4-flash 429s (paid).
  **gemini-2.5-flash: one full agent turn consumes the per-minute quota** —
  space A/B runs ~5min+. chutes auth OK but $0; zai 401; cerebras 403.
- **ADR-57 slice 3 (serial->concurrent Thinker) is queued but competes** with
  the P0 milestone; the user's framing says P0 first. The Thinker's remaining
  post-tool consult (~5s) should be re-measured under the token lens too.
- Standing: ~41 unattributed full-suite failures + 34-error ruff baseline
  still need a peer pass (S405-407); live-test port 8010 for the user app
  backend (never 8000). GitHub Dependabot: 3 vulns on main (2 high) still
  untriaged.
