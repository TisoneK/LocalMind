# Current Task

**Status:** IDLE — Session 369 shipped the one-click embed-model fix in the chat guide.

## Session 369 outcome — one-click auto-fix (no Settings detour)

- **User request:** make the chat guide auto-fix the embed model with one click instead of opening Settings.
- **Change (frontend only):** CenterPanel's banner primary button is now **"Use <suggested>"** → `setLocalSettings({ embedModel })` (the exact endpoint the Settings modal uses) → spinner → green confirmation "✓ Embedding model switched to X — memory can be saved now" → session-dismissed → collapses after 1.5s. Failure shows an inline error and keeps the banner. Dismiss X remains.
- **Verification:** 2 new CenterPanel tests (fix applies + confirms + marks session; failure keeps banner). 316 frontend, tsc/eslint clean, backend untouched (2429 pass from Session 368). Live (isolated 8765): `nomic-embed-text` available=False → one-click POST applies `mxbai-embed-large:latest` → available=True → persisted to settings.json.
- **Next:** B-2026-08-23-15 (auto-switch between Terminal/Agents/Memory tabs) or B-2026-08-23-16 (deeper Files browser) — both open in backlog.
