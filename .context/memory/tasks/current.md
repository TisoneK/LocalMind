# Current Task

**Status:** IDLE — Session 354 shipped the first-action tab-switch fix (`B-2026-08-23-5` done).

## Session 354 outcome — the first action now switches chat → actions

- The user's finding: "The first action almost never switches from chat tab to actions tab automatically until the second action kicks in."
- **Root cause (traced live):** backend was fine — live SSE capture (bankofai, isolated 8765) showed the FIRST tool event arrives as a dedicated `tool_call` with `status="started"`, which the frontend dispatches `localmind:tool-call-started` → `setActiveTab('actions')`. The miss was a **stale-flag race in LeftPanel**: `forceChatTab` (set by New Chat) was consumed only when `activeTab !== 'chat'` — clicking New Chat while already on Chat left it true. First tool event → switch to Actions → forceChatTab effect re-runs (activeTab is a dep) → **yanks back to Chat** → only the second action stuck.
- **FIX (`LeftPanel.tsx`):** the forceChatTab effect consumes the flag ALWAYS (even on Chat), ref-guarded to fire once per activation. Flag is gone before the first tool event can race it.
- **VERIFIED:** 1 new regression test (New Chat while on Chat → flag consumed → first Actions switch not fought); updated the pre-existing forceChatTab test to mirror production wiring. Frontend **274 passed**; tsc clean; eslint zero new.

## Next

- **B-2026-08-23-6 (Medium):** after creating a file, render it in the UI (docx, pdf, excel, ...).
- **B-2026-08-23-7 (Medium):** filetask information in the summary after the agent finishes creating/editing a file.
- **B-2026-08-23-9 (Medium):** action pills in chat should have tooltips when hovered.

**Feature:** none (single-session frontend race fix)
**Session:** 354 (logged in `.context/memory/agents/sessions.md`)
