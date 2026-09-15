# Feature: context-usage-breakdown — per-category share of the model's context window

**Started:** 2026-09-15 · **Status:** COMPLETE (S004 — backend estimator +
loop wiring `c7414ee1`, frontend panel `d3d861c4`, changelog `842d0e7d`;
live-verified on zai/glm-4.5-flash with shares summing exactly to the
provider's prompt total; bankofai primary provider QUOTA-EXHAUSTED at
verification time) · **Sessions:** S004 (implementation)

## What this feature is

The occupancy meter in the chat header shows ONE number: the last model
call's prompt tokens against the model's context window. When the window
fills up, the user can't tell what is consuming it — the system prompt, the
tool schemas, the conversation history, tool results, or the injected turn
context. This feature splits the last-call occupancy into named categories
with token counts and percentage shares, rendered under the existing meter
(pattern borrowed from ZCode's "Context windows" stats panel).

## Scope + invariants

- **Observability only.** The breakdown is computed from the message list and
  tool-schema payload the loop already built for the call. It must never
  alter prompt content, ordering, or tool selection. The `Hi`→zero-provider-call
  boundary and the ADR-34 event order are untouched.
- Categories (parent path): `system_prompt` (stable prompt incl. subgoal
  scratchpad), `turn_context` (dynamic context message: env, memory,
  workspace, todo, goal, task state, attachments), `tool_schemas` (native
  `tools=` payload JSON), `history` (prior user/assistant turns),
  `current_message` (the turn's user message), `tool_results` (role:tool +
  synthetic assistant tool-call messages), `turn_additions` (per-iteration
  injections: thinker block, observation log, synthesis nudges, answer
  directive).
- Token counts are estimates (tiktoken, chars//4 fallback) **scaled
  proportionally to the provider-reported prompt_tokens of that call when
  available**, so shares sum to the real occupancy the meter shows.
- Plumbing: breakdown rides the existing usage dict on `StreamChunk.usage`
  (last-call semantics), surfaces in the `turn_complete` event and the
  `metrics` SSE event, parsed in `useLocalMind`, rendered in `CenterPanel`.

## Files touched

- `backend/src/core/agent/loop.py` — compute breakdown at the call site.
- `backend/src/core/agent_runtime.py` — carry it through turn_complete.
- `backend/src/api/routes/chat.py` — include in metrics event.
- `frontend/src/hooks/useLocalMind.ts`, `frontend/src/components/layout/CenterPanel.tsx`,
  `frontend/src/types/index.ts` — parse + render.
