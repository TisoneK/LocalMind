# Current Task

**Status:** IDLE — Session 372 shipped auto-switching between Terminal/Agents/Memory tabs (B-2026-08-23-15 done).

## Session 372 outcome — auto-switch right panel on activity, no fight with manual choice

- **Task:** shell/code_exec → Terminal, parent turn → Agents, memory_op → Memory; must not fight the user's manual tab choice.
- **Changes (frontend only):** new `forceMemoryTab` (set on active `memory_op` tool call, auto-uncollapses panel); all three force flags in RightPanel converted to the **unconditional-consume** pattern (forceChatTab fix) — the old guarded consume left flags set when already on the target, so later events could re-fire and yank the panel. Backend needed no change (memory_op already emits tool_call SSE).
- **Verification:** new RightPanel.test.tsx (5: per-tab switch + the consume-when-already-there regression + no-flag default) + 2 WorkspaceLayout wiring tests; 329 frontend, tsc/eslint clean. Live (isolated 8765): a real turn emitted `memory_op` tool_call events (Memory signal) alongside `terminal_event`/`tool_call`/`todo_created`.
- **Next:** B-2026-08-23-16 (develop the Files tab into a fuller browser) or B-2026-08-23-19 (per-session workspaces already done) — check backlog for the next open item.
