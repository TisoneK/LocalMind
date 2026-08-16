# Current Task — AGENT-LOOP TOKEN EFFICIENCY (the real loop fix)

**This is the cure, not a single-prompt patch.** (User, Session 244:
"you fixed 1 prompt from 25s to 2s — that is not the real fix. Claude Code
runs 3 min with many tools in few tokens, yet our 'hi' consumes 11k.")
Build all three levers in ONE go, then live-verify on gemini (user changed
the gemini API key → fresh quota for verification).

## The disease (measured, Session 244)
Every model call in the agent loop re-sends the WHOLE prefix, uncached:
- **~3,000 tokens** static agent system prompt (`build_agent_system_prompt`).
- **~2,000–5,000 tokens** tool schemas (`TOOL_DEFINITIONS`, 29 tools; ~18 after
  per-intent scoping).
- \+ full conversation history + observations.
So a 4-tool task re-bills ~8–10k **four times** ≈ 40k; a trivial turn ≈ 11k.
Three root causes:
1. **No prompt caching at all** — grep of `openai_compat.py` for
   `cache_control` / `ephemeral` / `anthropic-beta` → nothing. Every call
   pays full freight.
2. **Dynamic content in the cacheable prefix** — `_build_environment_context`
   bakes `now.strftime("%H:%M")` (current time) INTO the system prompt, so the
   prefix changes every minute and even providers that auto-cache identical
   prefixes (OpenAI, Anthropic) MISS on every call.
3. **Fat prefix** — ~3k prompt (anti-fabrication rules appear twice, verbose
   per-intent personas + self-checks) + ~5k tool schemas.

## Why Claude Code is efficient (the reference)
Prompt caching: the big static system+tools prefix is written to cache once
(full price), then READ at ~10% on every subsequent call in the session. A
long multi-tool run reuses a ~10k prefix at ~1k effective tokens/turn. We have
zero caching AND we mutate the one thing that must stay byte-stable.

## The cure — build all three in one go
- **Lever 1 — Stabilize the cacheable prefix (ENABLER).** Move time/cwd and any
  other per-call/dynamic content OUT of `build_agent_system_prompt` into a tiny
  trailing per-call message (appended AFTER the cacheable system+tools block).
  The system prompt + tool defs must be byte-identical across iterations of a
  turn. Test: assert no timestamp/date in the built system prompt; dynamic env
  rides in its own trailing block.
- **Lever 2 — Wire prompt caching.** In `openai_compat.py`, mark the stable
  prefix (system message + tool definitions) with `cache_control:
  {type: "ephemeral"}` for Anthropic-backed models (zen proxies Anthropic;
  needs the anthropic-beta/prompt-caching path if the endpoint requires it);
  OpenAI-backed models auto-cache the now-stable prefix (no marker needed).
  Gate by provider/model family; degrade cleanly if the field is rejected
  (same 400-retry pattern as tool_choice). Unit-test that the marker lands on
  the right block and that non-supporting providers omit it.
- **Lever 3 — Prompt diet.** Cut the ~3k system prompt: de-duplicate the
  anti-fabrication block (currently in BOTH the CHAT branch and the execute
  path), trim persona self-check scaffolding, move rarely-needed rules to
  per-tier. Compact tool-schema descriptions. Keep load-bearing behavior
  (the anti-fabrication + mkdir-safety rules fixed real bugs — validate no
  regression). Target ~3k → ~1.5k. Stay under the 2,500-char INIT budget test
  and add/keep an execute-prompt budget guard.

## Verification
- Offline: byte-stable-prefix test, prompt-budget char counts, payload-shape
  unit tests for cache_control, full backend suite.
- **Live (gemini, user's new key):** trace harness `LOCALMIND_PORT=8765
  LOCALMIND_HOME=<isolated copy> LOCALMIND_ADAPTER=gemini` (or the user's
  active settings if gemini is active), `curl -N /api/chat`, parse
  `turn_complete.prompt_tokens_approx`. Compare a trivial turn and a
  multi-tool turn BEFORE vs AFTER. Expected: multi-tool ~40k → ~10k first call
  + cheap reads; trivial ~11k → ~1k. NEVER touch port 8000 (user's app) or
  their real `~/LocalMind/settings.json` (copy to an isolated LOCALMIND_HOME
  for traces; keys preserved, never printed).

## Guardrails
- Providers are free-tier and quota-tight (zen shared free quota, gemini
  per-minute, cerebras 402). Keep live traces minimal.
- Don't regress the streaming-whitespace, empty-response, or tool-force
  recovery contracts. Full suite must stay green (4 pre-existing env-gated
  `test_shell.py` failures are known/unrelated).
