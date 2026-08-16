# Current Task

**Status:** idle — Session 245 completed (agent-loop token efficiency, 3 levers).

**Last completed:** Built + live-verified (cerebras) the three loop-efficiency
levers — stable cacheable prefix (env/time moved to a trailing turn-context
message), prompt caching (cache_control for Anthropic-family + auto-cache for
others, degrade-safe), and prompt diet (~570 tok/call off every execute
intent). "hi" 1,089 tok/839ms; tool task 14,537 raw tok/1.6s with shell firing.
Commit `9ee3745`.

**Open next (deferred, needs live tool-use verification):** compact the verbose
tool schemas (~3.8k scoped tokens — now the biggest per-call line item);
watch for tool-use regressions. The caching discount is real but invisible to
our chars//4 `prompt_tokens_approx` — it lands on provider billing as
cache-read tokens.

**Feature:** none
