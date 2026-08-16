# Current Task

**Status:** done — Session 278: between-tool NARRATION streams to the user's chat;
clarified the agent-in-the-middle architecture; parallel tools already work.

**Delivered (`3bcd105`, review-54):** the model's `content` alongside a tool call
is user-facing narration (its chain-of-thought comes separately on the reasoning
channel), but the loop was burying it in the ThinkingBlock and the prompt said
"never narrate". Now the loop streams it to the user's CHAT (single + multi-tool
paths) and the prompt asks for ONE short user-facing line. Live catch on
glm-4.5-flash: it emits 374 thinking tokens then EMPTY content → no narration while
thinking, which per the user is intended ("when thinking the narration is not
there") — the ThinkingBlock is the update during reasoning. Not synthesizing fake
narration. Full suite 1875 pass; prompt trimmed to fit the size budget.

**Architecture clarified:** it is NOT tool-to-tool routing — the AgentLoop is the
orchestrator in the middle (decide → dispatch → observe → Thinker → repeat →
synthesize). "Intent" is a one-time upfront persona/tool-scope pick. Parallel tool
calls already dispatch concurrently (`asyncio.gather`, loop.py:1603).

**Open next / notes:**
1. **B-2026-08-16-10 (the real concurrency win):** as-completed result streaming —
   surface each parallel tool's result the moment it finishes instead of blocking
   on the whole `gather`. (A model still can't generate while awaiting results —
   its turn pauses at the hand-off; this is loop-side progressive surfacing.)
2. **Owed real-app visual check** on a content-emitting model (gpt-oss/gemini)
   where narration is visibly richer (glm-4.5-flash stays silent while thinking).
3. Carried: B-9 (create→FILE_WRITE — re-scoped to reasoning-driven, not a hardcoded
   route); owed live Windows re-run of S264 recipe; owed real-app check of the S274
   todo panel; cerebras synthesis rate-limit (provider cap). Closed: B-4 (S272),
   B-7 (S276), B-5/L3 (S277).

**Feature:** none
