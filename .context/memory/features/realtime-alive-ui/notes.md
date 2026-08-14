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

---
## Session 212 (2026-08-14) — Live plan checklist

`TodoList`: active-step highlight (`isActive` = not completed AND
(`todo.status` running/started/in_progress OR a running action under it))
→ spinner + amber ring + bold amber text; framer-motion tick scale-in +
row enter + eased progress bar; `useReducedMotion`; `data-testid=todo-row`
+ `data-active` for tests. Fixed `LeftPanel` gate that hid Todos during
active tools — now shows when idle OR `todos.length > 0`. Added
`TodoList.test.tsx` (6). 161 tests / tsc / lint(0 err) / build green.
`cd02072` + changelog `3f1368a`.

**All three user screenshots now shipped** (Actions S210, Thought Process
S211, Todos S212). Remaining feature surfaces (not screenshotted, same
treatment): S213 `TerminalPanel`, S214 `AgentWorkspace`, S215 shared
motion/a11y polish (extract the repeated framer-motion enter + reduced-
motion guard into a shared primitive; consider an ADR). Each still needs
a live-app visual pass once a provider credential is available.

---
## Session 213 (2026-08-14) — Alive left-panel action trace

`ActionHistory`: framer-motion `AnimatePresence` enter per chain row,
running-step emphasis (amber card ring + pulsing numbered badge),
status-colored badges (green done / red failed), `useReducedMotion`,
`isRunning()` helper. Grouping logic untouched. Added
`ActionHistory.test.tsx` (4). 165 tests / tsc / lint(0 err) / build green.
`7392c73` + changelog `3da8f72`.

Triaged the remaining user-named surfaces: `TerminalPanel` (721 lines,
already streams) is broad → backlogged as B-2026-08-14-4 (its own
session). Remaining feature sessions: S214 `AgentWorkspace`, S215 shared
motion primitive + a11y (extract the repeated `motion.div` enter +
`useReducedMotion` guard now duplicated across ToolSteps/ThinkingBlock/
TodoList/ActionHistory into one component/hook; consider an ADR).

---
## Session 214 (2026-08-14) — Alive agent workspace

`AgentWorkspace`: framer-motion `AnimatePresence` enter for parent/child
`RunNode`s + tool rows + root list, running-run amber ring,
`useReducedMotion` (called in RunNode). Run-tree logic unchanged. +1
test (running-run assertion). 166 tests / tsc / lint(0 err) / build green.
`b2bd48e` + changelog `0594961`.

**Feature status:** 5 alive surfaces shipped (S210 chat Actions, S211
Thinking, S212 Todos, S213 panel action trace, S214 Agents). All 3 user
screenshots + panel twins done. Remaining: B-2026-08-14-4 Terminal (own
session), S215 shared motion primitive (the `motion.div` enter +
`useReducedMotion` guard is now duplicated in ToolSteps/ThinkingBlock/
TodoList/ActionHistory/AgentWorkspace — extract into e.g. `<MotionItem>`
+ `useEnterMotion()`; consider an ADR), and live-app visual verification
(provider credential needed).

---
## Session 215 (2026-08-14) — Live terminal cursor (closes B-2026-08-14-4)

`TerminalPanel`: idle prompt block cursor (`!isRunning && input===''`),
live "executing…" cursor line at output bottom while `isRunning`,
auto-scroll effect now also depends on `isRunning`. CSS `.terminal-cursor`
blink in globals.css with a `prefers-reduced-motion` steady override —
NOT framer-motion (this is a high-frequency component). **Deliberately no
per-line output animation** — terminal output is high-volume and must not
stutter; the liveness cue is the cursor + run-state, not the stream.
Added `TerminalPanel.test.tsx` (4). 170 tests / tsc / lint(0 err) / build
green. `21f88db` + changelog `662ff85`.

**Every user-named surface now alive** (S210 Actions, S211 Thinking, S212
Todos, S213 panel actions, S214 Agents, S215 Terminal). Remaining: S216
shared motion primitive (DRY refactor — the `motion.div` enter +
`useReducedMotion` guard is duplicated in 5 components; extract into e.g.
`<MotionItem>` + `useEnterMotion()`, consider an ADR) and live-app visual
verification (needs a provider credential).

---
## Session 216 (2026-08-14) — Shared motion primitive (feature complete)

`useEnterMotion()` in `lib/localmind/motion.ts` returns `{ reduce, enter }`;
`enter({x,y,duration})` → spreadable `initial/animate/transition`
(`initial:false` under reduced motion). Adopted in ToolSteps,
ThinkingBlock, TodoList, ActionHistory, AgentWorkspace (dropped their
`useReducedMotion` imports). Behaviour-preserving. ADR-30. +3 tests
(`motion.test.ts`; note: mock framer-motion with `vi.hoisted` + `vi.mock`
— ESM exports can't be `vi.spyOn`'d). 173 tests / tsc / lint(0 err) /
build green. `fb86e25`.

**FEATURE IMPLEMENTATION COMPLETE (S210-216).** Every user-named surface
is alive & async; motion is unified + reduced-motion by construction.
The only open item is a live-app visual verification vs
`ui_improvement/*.png` — needs a provider credential (standing gap since
S201). If a future agent gets a Zen/local key: run a real turn, watch the
Actions timeline / thinking caret / todos check-off / agents tree /
terminal executing cursor, and confirm they match the screenshots' feel.
