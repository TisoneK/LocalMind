# Current Task

**Status:** idle — Session 248 completed (New Chat tab/counter reset, live
actions as cards, action-card polish, backend double-persist fix).

**Last completed:** Four fixes shipped (`3564a77`, `405159a`):
1. New Chat resets left panel to Chat, right panel to Agents, and zeroes the
   context counter (new `resetSession()` in `useChat` — the client-side
   session ID never matched a backend session, so the old session-switch
   cleanup never fired).
2. Actions tab no longer shows pills during execution — live actions render
   as the same expandable cards as history.
3. Messages loaded twice after reopening a chat — ROOT CAUSE WAS BACKEND:
   the guaranteed-persist dedup used `get_history(limit=2)` (ASC) so it
   compared against the OLDEST two messages, never the just-saved reply.
   Added `get_recent_history()` (newest-first) + pointed both
   `_guarantee_persist_assistant` impls at it.
4. Action cards: scrollable body, copy buttons per section, stacked step
   number (full-width container), pretty color-coded JSON input.

**Note:** the dup fix repairs NEW replies only — chats already saved with
duplicate rows keep them.

**Open next (recommended):** tool-schema diet `B-2026-08-15-14` (~3.8k
scoped tokens) with live tool-use verification. Also still open from
Session 247: grep for any remaining per-chunk trimming
`_strip_minimax_tool_calls` uses on streaming deltas.

**Feature:** none
