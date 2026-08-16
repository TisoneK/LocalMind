# Current Task

**Status:** done — Session 276: shipped B-2026-08-16-7 — reasoning handling is now
provider-generic, so the Thinker (which made glm-4.5-flash efficient/precise)
reaches ALL capable models, not just z.ai/GLM.

**Delivered (`b3f489d`, review-52):** live-probed cerebras/gpt-oss-120b (keys only)
— reasoning arrives in a `reasoning` field, not `reasoning_content`/`<think>`, so
`_extract_content_and_reasoning` missed it. And `thinking_enabled` returned False
for every non-zai provider — and the loop gates the mid-loop Thinker consult +
thinking-aware timeout on it, so the Thinker NEVER ran for gpt-oss/cerebras. Fix:
extraction reads `reasoning` too; `thinking_enabled` True for all capable providers
(z.ai keeps its GLM-5.3 force-enabled logic; tunable via `LOCALMIND_THINKING`); the
z.ai `thinking` request param + one-shot override gated to zai. LIVE-VERIFIED on
cerebras/gpt-oss-120b (per system/live-testing.md): Thinker consulted
(agent_thinker_start/done — never before), reasoning streamed to the thinking
channel not chat, model ran a tool. 31 adapter + 366 agent/loop tests pass.

**Open next / notes:**
1. **cerebras rate-limits the final synthesis call** — a provider tokens/min cap
   (in the user's original trace too), so tasks don't fully COMPLETE on its free
   tier. Orthogonal to reasoning; a headroom/paid provider shows full completion.
2. **Still-open tools work:** B-2026-08-16-5 (L2 right-tool steering + L3 redundant
   read-back).
3. **B-2026-08-16-8 (prompt overhead) — DEPRIORITIZED per user:** "we already saw
   how the thinker made the agent efficient and precise even on lesser model — so
   [token cost] shouldn't be a question." The Thinker is the efficiency lever; the
   ~9k system-prompt overhead is not the priority.
4. Carried: ADR-37 follow-ups B-2026-08-15-10/11/12; review-42 `classify_failure`
   cleanup; owed live Windows re-run of the S264 recipe task; owed real-app visual
   check of the S274 todo panel.

**Feature:** none
