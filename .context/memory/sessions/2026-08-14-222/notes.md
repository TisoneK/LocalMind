# Session 222 notes — model-owned parent initialization

The user correctly rejected Session 221's addressed-greeting matcher as a real
solution. The architectural defect was that `AgentRuntime` made a prompt-shaped
routing decision before LocalMind's parent agent existed.

## Before

```text
message → deterministic trivial/conversational shortcut OR parent runtime
```

This meant the model was not asked what the request meant for an entire class of
messages. It also made each new missed phrase look like a new regex bug.

## After

```text
message
  → AgentRuntime acknowledgement/lifecycle
  → ParentAgent → AgentLoop initialization LLM call
  → { direct | clarify | execute }
  → direct answer OR visible acknowledgement/plan/todos
  → parent tool call
  → observation/evidence back into parent
  → verify/replan/synthesize
```

`InitializationDecision` is deliberately structured and bounded. It carries no
hidden chain-of-thought. Malformed model output fails open to execute mode rather
than selecting a tool from deterministic keywords.

## Product validation

- Focused initialization, routing, stage, workflow, and legacy-helper tests: green.
- Full backend CI: 1,784 passed, 2 skipped.
- Frontend: 178 passed.
- TypeScript/build/Ruff: passed.
- ESLint: 0 errors, 64 pre-existing warnings.

No live-provider smoke was possible because credentials were unavailable. The next
real-model check should use a free provider and exercise: `Hi`, a direct factual
question, current weather, a shell/file task, and a failing provider call. Verify
first initialization call ordering and the visible event sequence.
