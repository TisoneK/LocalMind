# Current Task

**Status:** IDLE — Session 375 shipped Preview/Edit/Diff modes for the file preview dialog (B-2026-08-23-18 done) and fixed a real edit_file crash the live check exposed.

## Session 375 outcome — preview dialog modes + edit_file crash fix

- **Feature (frontend):** FilePreviewDialog now has a Preview/Edit/Diff switcher. Diff mode renders DiffBlock with the edit_file hunks captured this turn. The hook now handles the previously-dropped `diff` SSE events → session `fileDiffs` map (per path) + `message.diffData` (revives the dead inline chat DiffBlock). Wired WorkspaceLayout → LeftPanel/CenterPanel → ChatMessage.
- **Backend bug found live:** every native `edit_file` call crashed with `UnboundLocalError: tool_result` — `Intent("edit_file")` raises (tool name ≠ Intent value `file_edit`), the outer except marked the tool failed, then the failed-branch emit referenced the unbound var. Fixed: `_intent_for_tool()` mapping at both dispatch sites + `tool_result = None` bound up front + broad `except Exception` in the file_write/edit_file contract branches. The diff SSE path was completely blocked by this.
- **Verification:** 2447 backend / 340 frontend; 3 new loop e2e tests (edit_file edits + emits file_diff obs with hunks/path; malformed payload → clean failure; intent mapping) with revert-check; 4 dialog + 1 hook frontend tests. Live: crash fix proven (failed edit_file → graceful + retry, no turn death).
- **Note:** the free-tier model's edit_file arg schemas are unreliable (content-only, then `old_pattern`/`new_string` instead of `pattern`/`replace`) — candidate for a tool-schema aliasing pass later.
- **Next:** next open backlog item (B-2026-08-23-19 custom theme UI, etc.).
