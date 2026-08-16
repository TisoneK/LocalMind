# Current Task

**Status:** done — Session 265: three frontend UX fixes shipped + pushed
(`3970570` `3b7f968` `040bf0e` `4411e2c`):
1. **Context counter cumulative** — the top-bar Context meter now shows
   `sessionStats.promptTokens` (cumulative across the conversation) + the
   in-flight estimate while streaming, matching the bottom-right stats
   corner. Previously it showed only the last turn's prompt.
2. **Empty "Why" blocks hidden** — whitespace-only reasoning (empty
   plan-step label attached as `reasoning`) rendered blank "Why" sections
   in the Actions tab and tool-step cards; all render sites now guard on
   `reasoning?.trim()`.
3. **ThinkingBlock UX** — max-height + scrollbar (`max-h-64` +
   `custom-scrollbar`), a bottom copy button, and auto-scroll to bottom as
   new reasoning streams.

224 frontend tests pass, `tsc -b` + `vite build` clean, eslint 0 errors.

**Open next / notes:** unchanged from before — ADR-37 follow-ups
B-2026-08-15-10/11/12, review-42's `classify_failure` cleanup, owed live
Windows re-run of the Session 264 recipe task, unbounded `reasoning_effort`
default.

**Feature:** none
