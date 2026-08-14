<!-- Feature notes — append-only while the feature is alive. -->

# realtime-alive-ui — session notes

---
## Session 210 (2026-08-14) — Live Actions timeline

**Target (from user + `ui_improvement/` screenshots):** the chat tool
trace should read like the reference agent's "Actions" card — a grouped
summary header ("⚡ Wrote 1 files, Ran 1 commands ⌄") over a connected
vertical timeline of sub-steps ending in a "Done" row — and feel alive:
steps animate in as they stream, the running step pulses, the summary
updates live.

**Baseline analyzed:**
- `frontend/src/components/chat/ToolSteps.tsx` — renders one bordered
  card per tool, no grouping, no summary, no timeline, minimal motion
  (spinner + ping dot only). Full mode used only in `ChatMessage.tsx`;
  `compact` mode currently has no live caller (keep for API stability).
- `toolCalls` stream live per assistant message in `useLocalMind.ts`
  (running → done/failed, duration, label, reasoning, todoId). Data is
  already sufficient — no backend change needed.
- Foundation: framer-motion 12.23, tailwind v4 `@theme`, `tw-animate-css`.

**Plan:** rewrite `ToolSteps` full mode as `<ActionTimeline>` — a
grouped card with a live summary header and a connected timeline; each
step keeps the existing expandable detail (why/input/output). Add
framer-motion enter animation, running-step pulse, and a terminal Done
row. Preserve compact mode and all `ToolCall` fields.

**Outcome (Session 210):** shipped. `ToolSteps` full mode is now
`<ActionTimeline>` — grouped card, live summary header (`summarizeCalls`
buckets: write/edit/read/command/search/memory/info), connected
`TimelineRow`s with status dots, framer-motion enter + `useReducedMotion`,
auto-expand while streaming / auto-collapse ~2.5s after, terminal
Done/error/working row. Compact mode untouched. `ToolSteps.test.tsx`
added (was zero coverage). 150 tests / tsc / lint(0 err) / build all green.
Commits `3ba4945` (feat) + `dbcb8e3` (changelog).

**For the next surface session (S211 Thinking):** the same principle
holds — the backend already streams the data (Sessions 205-209); the work
is presentation. Reuse this session's motion vocabulary (framer-motion
enter, `useReducedMotion` guard, auto-expand-while-streaming) so the
surfaces feel like one system. `ThinkingBlock` already parses `[Label]
Detail` step lines and auto-collapses; make the reveal feel like live
reasoning (streaming cursor / smooth token reveal).

---
## Session 211 (2026-08-14) — Live thinking stream

Reworked `ThinkingBlock`: `LiveCaret` (blinking bar at end of streamed
text — thinking content already streams via `thinking_token`), pulsing
`ThinkingDots` + brain icon in header while streaming, framer-motion
reveal + `useReducedMotion`, idle label "Thought process" + elapsed
time. Preserved `[Label] detail` step parsing + auto-collapse. Removed
dead `DispatchStep`/`parseDispatchSteps`. Added `ThinkingBlock.test.tsx`
(5 cases). 155 tests / tsc / lint(0 err) / build green. `779eda3` +
changelog `7f15512`.

Two of the three user screenshots now shipped (Actions S210, Thought
Process S211). Next: S212 Todos (`ui_improvement/Todos.png`) — the
Tasks panel `TodoList` / plan checklist. Same principle: data already
streams; make check-off feel alive (animated tick, progress, current
highlight). Keep the shared motion vocabulary.
