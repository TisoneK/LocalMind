# Current Task

**Status:** DONE — Session 289: three local-first bugs (Windows/Ollama,
phi4-mini) + a token-consumption concern. 5 product commits + changelog +
review-57. All pushed. NOT live-verified on Ollama — see B-2026-08-17-2.

**Shipped:**
- `bef1eb2` Bug 3 — context meter 64%: detect real window via Ollama /api/show;
  user-configurable num_ctx (0=auto); "mini" size-tier; backend settings plumbing
  (ADR-44).
- `6887440` Bug 2 — "Hi" runs tool loop + times out: slow providers get the chat
  budget for the parent init call so the classify finishes and returns `direct`
  (ADR-45). Stays in agentic control — no intent routing.
- `8e2bca4` Bug 1 — Settings modal: active-model + embedding-model + context-window
  controls (+ /api/settings/local, /api/models/embeddings).
- `20fff03` Token — compact env for the classify call; "Hi" ~731 vs ~5,211 tokens.

**Open next:**
1. B-2026-08-17-2 — user verifies on Windows/Ollama (meter %, "Hi" no-tools, Settings).
2. B-2026-08-17-1 — progressive tool-schema disclosure (ADR-43 Phase 3): the
   dominant remaining execute-mode token cost; needs live-verification on a weak
   model (ADR-40 guardrail).
3. Carried (S288): delegate_parallel as-completed streaming, BLOCKED_COMMANDS
   substring audit, Windows re-run of S264, z.ai empty-final retry.

**Feature:** none
