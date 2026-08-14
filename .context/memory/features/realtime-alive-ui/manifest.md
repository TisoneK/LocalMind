<!-- Feature manifest — update-in-place. One per feature directory. -->

# Feature: realtime-alive-ui

- **Slug:** realtime-alive-ui
- **Started:** 2026-08-14 (Session 210)
- **Status:** active
- **Owner sessions:** 210–…
- **Ledger:** see `.context/memory/features/ledger.md`

## Goal

The user moved LocalMind off the old pipeline orchestration onto the
parent AgentLoop (Sessions 200–209). The backend now streams rich SSE:
plan todos, actions/tools, terminal output, agent-run tree, thinking,
statuses, and final tokens. But the **frontend still looks and feels
"old"** — dense, static, one-card-per-tool, no motion. The user wants
every surface (actions, todos, terminal, tools, agents, chat, thinking)
to feel **alive and async — things happening at the same time**, with
real-time updates, matching the clean grouped "agent" aesthetic in the
uploaded `ui_improvement/` screenshots (Actions, Thought Process, Todos).

This is a **multi-session** visual overhaul. Each surface gets its own
protocol session; the dark-green brand identity is preserved throughout.

## Session plan (one feature-surface per session)

- [x] **S210 — Live Actions timeline** (done 2026-08-14, `3ba4945`):
  redesigned the chat tool trace (`ToolSteps`) into a grouped, connected,
  animated timeline with a live summary header ("Wrote 1 file, Ran 2
  commands"), per-step framer-motion enter, a pulsing running step, and a
  Done / "Done with errors" / working terminal row. `prefers-reduced-motion`
  honoured; compact mode + all `ToolCall` fields preserved; added
  `ToolSteps.test.tsx` (9 cases). No backend change. Matches Actions*.png.
- [x] **S211 — Thinking stream** (done 2026-08-14, `779eda3`): live
  blinking caret trailing the streamed reasoning, pulsing three-dot
  indicator + brain icon while thinking, framer-motion reveal, idle
  label "Thought process" + elapsed time. `prefers-reduced-motion`
  honoured; step parsing + auto-collapse preserved; removed dead
  `DispatchStep`/`parseDispatchSteps`. Added `ThinkingBlock.test.tsx`
  (5 cases). Matches Thought Process.png.
- [x] **S212 — Todos live** (done 2026-08-14, `cd02072`): active-step
  highlight (spinner + amber ring + bold) from `todo.status`/running
  actions, animated tick-in + row enter (framer-motion), eased progress
  bar. Also fixed `LeftPanel` hiding the Todos section during active work
  — an existing plan now stays visible while tools run. Added
  `TodoList.test.tsx` (6 cases). Matches Todos.png. **All three
  user-screenshotted surfaces (Actions/Thinking/Todos) now shipped.**
- [ ] S213 — Terminal panel realtime feel (`TerminalPanel`).
- [ ] S214 — Agents workspace realtime feel (`AgentWorkspace`).
- [ ] S215 — Shared motion/design polish sweep + reduced-motion a11y.

## Constraints / invariants (do not regress)

- Dark-only, dark-green identity (Session 203 palette). No theme toggle.
- Backend SSE transport unchanged — this is a frontend presentation
  feature. All data already arrives; do not add backend events unless a
  session proves a gap.
- Preserve raw provider/planner reasoning privacy (Sessions 207/209).
- Respect `prefers-reduced-motion`.
- Keep `ToolSteps` `compact` mode export intact (used by types/tests).

## Decisions

- ADR pending if a shared motion primitive is introduced (S215).

## Notes

See `notes.md` for per-session detail.
