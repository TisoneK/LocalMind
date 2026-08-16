# Current Task

**Status:** idle — Session 249 completed (z.ai/GLM-4.5-flash triage).

**Last completed:** Diagnosed the 3 GLM-4.5-flash issues live. Incomplete
output {HIGH} is a MODEL limitation (terse; provider reports 28 completion
tokens; max_tokens + a 2.7k input cut both changed nothing) — reported
honestly, no code fix claimed. Input bloat {MEDIUM}: the tool catalog was
sent 3× — removed the redundant text injection (verified 16,763→14,098
tok/call) + fixed a latent stream-tail drop. Latency {LOW} = model 0.48
tok/s. `a5c0a0b`; review-39.

**Open next (need a provider with quota to live-verify):**
1. `B-2026-08-15-14` — scope tools to the intent ("analyze" sent all 30;
   the `tools` param alone is ~6.3k tok/call) + stop duplicating the tool
   list inside the agent system prompt.
2. Issue #1 mitigation: a synthesis-prompt nudge for a complete, structured
   final answer (count + first N items) and/or richer (less-truncated)
   evidence for listing tasks. GLM terseness is a model property → coaxing,
   not a guaranteed fix; live-verify.

**Feature:** none
