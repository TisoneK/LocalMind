# Current Task

**Status:** IDLE — Session 353 shipped shell-state awareness (`B-2026-08-23-4` done).

## Session 353 outcome — the agent knows shell is off BEFORE it picks tools

- The user's finding: "The system should be aware if shell is active or off before even running shell tool… take alternative routes like using python scripts instead… also a ui guide that helps the user to open settings and toggle shell on/off."
- **Root cause:** shell was gated ONLY at execute time — the model saw the shell schema and advertised list even when disabled, called it, and got rejected (wasted iterations + blocked-tool card).
- **FIX:** `_build_environment_context` (compact init + full execute) reports the live shell state + fallback guidance ("use CODE_EXEC / FILE_TASK / FILE_WRITE; if it genuinely needs a shell command, tell the user to enable Shell in Settings") and drops the `- shell:` line from the Available Tools prose when off. `loop.py` removes `shell` from the model's tool surface when disabled (`_shell_tool_enabled()`, defaults on). Frontend: a blocked shell call now shows a `ShellDisabledTip` with an **Open Settings** button (window event → RightPanel opens the existing SettingsModal with the Session 292 toggle).
- **LIVE (bankofai, isolated 8765, shell off):** "List the files in /tmp using shell commands" → tools run `['code_exec', 'code_exec']` (Python), zero shell calls, formatted /tmp table. The schema wasn't there to call.
- **Tests:** 8 backend + 4 frontend new. Backend **2350 passed / 2 skipped**; frontend **273 passed**; tsc clean; zero new lint.

## Next

- **B-2026-08-23-5 (Medium):** the first action almost never switches the chat tab to the actions tab automatically until the second action kicks in.
- **B-2026-08-23-6 (Medium):** after creating a file, render it in the UI (docx, pdf, excel, ...).
- **B-2026-08-23-7 (Medium):** filetask information in the summary after the agent finishes creating/editing a file.

**Feature:** none (single-session shell-awareness fix)
**Session:** 353 (logged in `.context/memory/agents/sessions.md`)
