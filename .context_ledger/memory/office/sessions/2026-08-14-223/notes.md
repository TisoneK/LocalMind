# Session 223 notes — parent-first realtime workspace contract

## User requirements translated into architecture

- Replace default Electron chrome with a deliberate LocalMind title-bar shell.
- Keep tool detail in Actions/Terminal/Agent Workspace, not duplicated as the
  assistant's chat answer.
- Make the first model-owned thinker visible through safe public lifecycle
  fields, while keeping hidden chain-of-thought private.
- Acknowledge before work; do not let memory/context preparation create a
  silent first phase.
- Return tool evidence to the parent model first; parent decides what belongs in
  the final response.
- Activate Agents automatically when initialization starts.
- Retire Observe and move its useful telemetry into dynamic agent nodes.
- Remove product-facing intent concepts rather than adding more intent routes.
- Remove the normal-chat Autonomous work block; preserve background objective
  runtime until its product fate is decided separately.
- Reduce prompt size and call count so the first public decision is targeted at
  under five seconds when the provider is healthy.

## Current implementation facts

- `AgentRuntime._process_unlocked()` emits a status acknowledgement before
  memory/context work, but the parent initialization model call occurs after
  memory retrieval, attachment parsing, and `build_context()`.
- `AgentLoop._initialize_parent()` parses a typed decision, but the decision is
  buffered before public fields are emitted.
- `RightPanel` defaults to `observability`; `Agents` exists but has no automatic
  activation event.
- `LeftPanel` activates Actions on a tool-start event, while `ChatMessage`
  continues to render `ToolSteps` in the transcript.
- `AgentWorkspace` renders run/tool nodes but not plan/evidence/verification
  lifecycle state.
- `ObservabilityTab` renders the old pipeline and intent classification.
- `electron/main.js` uses BrowserWindow defaults; no custom title-bar options or
  drag region are configured.
- `ObjectivesPanel` renders the `Autonomous work` label in the normal sidebar.
- ADR-17 already measured the serial-call/static-prompt problem; ADR-33 fixed
  ownership of interpretation but not the bootstrap ordering or workspace UX.

## Decision boundaries

- Deterministic transport acknowledgement is acceptable only as an immediate
  “received” signal; it must not be presented as model thinking.
- The thinker output is a public execution summary, not raw reasoning.
- Tool evidence can stream to UI nodes immediately, but the assistant bubble's
  final content is owned by parent synthesis.
- Internal legacy `Intent` values can remain temporarily for compatibility, but
  no routing/UI/stage design may depend on them after migration.
- Stage clocks remain useful backend instrumentation; “Observe” as a user-facing
  pipeline is removed.

## Suggested event/state vocabulary for implementation

`turn_received`, `agent_initialization_started`, `agent_understanding`,
`agent_acknowledgement`, `plan_created`, `agent_activated`, `tool_started`,
`tool_evidence`, `tool_completed`, `verification_started`, `verification_result`,
`replan`, `agent_synthesizing`, `turn_complete`, `turn_failed`.

These are design names, not product changes in this session. The implementation
should use one normalized reducer so Agents, Actions, Todos, Terminal, and chat
cannot each invent a separate lifecycle.

## Open implementation questions

- Whether the fast thinker uses the same model with a compact prompt or a
  separately routed low-latency model; measure real provider behavior before
  finalizing.
- Whether the custom title bar is Electron-only or also a browser-safe shell.
- Whether background objectives get a separate workspace after the label is
  removed from normal chat.
- How to preserve terminal output visibility while preventing it from becoming
  the assistant's final answer.
