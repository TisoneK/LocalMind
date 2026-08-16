# Current Task

**Status:** idle — Session 253 completed (research + handover, no code).

**Last completed:** Found + documented the real cause of GLM-4.5-flash's
terse/incomplete output: our adapter UNCONDITIONALLY disables the model's
thinking on z.ai (`_add_provider_params` ~L687, `thinking:disabled`) for a
reason (the ThinkingDispatcher's 10s timeout) that was DELETED in Session
239. The model is capable (Copilot does full agentic work with thinking
ON); our harness cripples it. Retracted the S249/S252 "weak model"
conclusion. Handover written: ADR-41, review-43, backlog B-2026-08-16-3.

**Open next (implementation — its own session, HANDOVER READY):**
B-2026-08-16-3 per ADR-41 — remove the unconditional thinking-disable
(default ON for reasoning models); investigate a z.ai thinking BUDGET/effort
level; make `PER_CALL_TIMEOUT_SECS` (constants.py:64) thinking-aware so a
slow free tier doesn't truncate mid-thought; keep the fail-fast for a model
that only thinks. Reasoning already routes to the ThinkingBlock. **MANDATORY
live before/after verify on z.ai/glm-4.5-flash — do NOT claim from theory.**

**Feature:** none
