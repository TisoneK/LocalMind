# Current Task

**Status:** IDLE — Session 368 shipped the embed-model missing guide in chat (follow-up to B-2026-08-23-14).

## Session 368 outcome — chat guide when the default embed model isn't available

- **User request:** if the default embed model isn't in Ollama but another is, guide the user in chat to set it — Settings already has the field, just needs a guide pointing there.
- **Changes:** `GET /api/models/embeddings` now returns `configured_available` (tag-insensitive match against pulled models) + `suggested` (first pulled embed-capable alternative); CenterPanel shows a dismissible amber banner when the configured model is missing but an alternative exists — "Set it to Y in Settings → Embedding model" with an Open Settings button (reuses `localmind:open-settings` event) and a session-persistent dismiss. Removed a pre-existing unused `hasToolCalls` var in CenterPanel.
- **Verification:** 3 backend + 5 frontend new tests; 2429 backend / 315 frontend; ruff/tsc/eslint clean. Live (isolated 8765, real Ollama): `configured: nomic-embed-text, configured_available: False, suggested: mxbai-embed-large:latest` — exactly the missing-model case.
- **User's one-click next step:** Open Settings → Embedding model → mxbai-embed-large (or `ollama pull nomic-embed-text`).
- **Next:** B-2026-08-23-15 (auto-switch between Terminal/Agents/Memory tabs) or B-2026-08-23-16 (deeper Files browser) — both open in backlog.
