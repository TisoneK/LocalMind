# Current Task

**Status:** IDLE — Session 374 fixed the "garbled Approach on 'Hi'" bug: tool-talk recovery is now intent-gated.

## Session 374 outcome — tool-talk recovery gated to agent intents

- **User report:** on a plain "Hi" (deepseek-v4-flash), the chat streamed a garbled "Approach" block — the model's reasoning wrestled with "You described wanting to use a tool but did not call it. You MUST use the tool-calling API directly…", a message the user never sent. Was the thinker or the system prompts corrupted?
- **Diagnosis:** neither. The Approach block is by design (ThinkingBlock renders streamed reasoning). The weird content was the model reacting to a **loop-injected corrective message** (`loop.py` tool-talk recovery, ~4389): the greeting mentioned tools → `_is_tool_talk` tripped → the recovery (NOT intent-gated, unlike the fabrication/forced-tool checks) suppressed the greeting and injected the accusation on a CHAT turn where no tool is required. The small model spiraled reconciling "Hi needs no tool" with "you MUST call a tool".
- **Fix:** gate the tool-talk recovery on `intent in AGENT_INTENTS`. Conversational turns never get the correction; agent-intent behavior unchanged. Regression tests (3) prove CHAT-not-recovered / agent-still-recovers / plain-CHAT-untouched; revert-check confirmed the CHAT test fails pre-fix with the exact `tool-talk detected (recovery 1/2)` log.
- **Verification:** 2444 backend / 335 frontend; ruff clean (2 pre-existing E501s untouched).
- **Next:** check backlog for the next open item (B-2026-08-23-18 file-preview modes, B-2026-08-23-19 custom theme, etc.).
