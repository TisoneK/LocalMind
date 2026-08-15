# Current Task

No active task.

The next session must read `.context/kickoff.md` before starting work.

Last: Session 234 (Buffy / deepseek-v4-flash, local) — resumed the interrupted
Claude title-bar session: Windows is now fully frameless (`frame: false`) so the
custom TitleBar buttons are the window controls; macOS keeps the system traffic
lights (`hiddenInset`); Linux keeps the default frame. Custom buttons render only
on win32 (B-11 had gated on `window.electronAPI`, duplicating native controls).
Added `window-is-maximized` IPC + maximize/unmaximize events (Square↔restore
icon) and double-click-to-maximize. Also fixed pre-existing date-rot in
`test_synthesizer_freshness.py` (hardcoded Aug-14 fixture). Product `1865c74`;
frontend 190 / backend 1,819 pass. Open: B-2026-08-15-3 (defer build_context for
direct turns), B-2026-08-15-4 (ESLint 66-warning drift vs 65 cap).
