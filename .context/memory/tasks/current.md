# Current Task

**Status:** idle — Session 246 completed (ActionHistory null-duration crash fix).

**Last completed:** Fixed the Actions panel crashing on `Cannot read properties
of null (reading 'toFixed')` — the duration guard only checked `!== undefined`
but the backend can emit `duration: null`, which survives JSON round-tripping
and crashed the whole panel. Guard is now `!= null`. Commit `1b281ec`.

**Open next (deferred, needs live tool-use verification):** compact the verbose
tool schemas (~3.8k scoped tokens — now the biggest per-call line item);
watch for tool-use regressions (B-2026-08-15-14). The caching discount is real
but invisible to our chars//4 `prompt_tokens_approx` — it lands on provider
billing as cache-read tokens.

**Feature:** none
