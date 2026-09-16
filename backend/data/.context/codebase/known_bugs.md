# Known Bugs (append-only — bugs found and fixed)

Bugs found during early development. Consult this
before investigating a reported issue — it may already be fixed.

- **Silent greeting cost:** trivial inputs ("Hi") burned 11.5s + 4.8k tokens by
  hitting the full ThinkingDispatcher. Fixed: `core/trivial_input.py`
  short-circuits greetings before the dispatcher runs.
- **Greeting titles:** chat titles were "Hi" / "Hello" / "Quick hello" because
  title-gen fired on every first message. Fixed: intent-gated title-gen
  via `should_refine_title()` — waits for a substantive message.
- **Reasoning leak:** model reasoning leaked into chat verbatim, including
  system prompt contents (user name, OS, memory state, values list).
  Root cause: `text = content or reasoning_content` merged reasoning
  into text. Fixed: `_extract_content_and_reasoning()` keeps them
  separate.
- **UnboundLocalError after tool execution:** `UnboundLocalError: prompt_messages` after tool
  execution + duplicate responses (first response replaced by second).
  Fixed: initialize `prompt_messages = []` at top of `process()`;
  moved `return` before cleanup in trivial short-circuit.
- **Cross-session tool stickiness:** tool selection persisted across sessions ("sysinfo
  was for the first chat it just didnt reset") + "thinking forever"
  silent hang. Fixed: reset `selectedTool` on session change (frontend);
  `asyncio.wait_for()` timeout on `chat_with_tools()`.
- **Delete left engine state:** session deletion didn't clean up engine state dicts
  (unbounded growth) + adapter `**kwargs` silently swallowed unsupported
  params. Fixed: `engine.cleanup_session()` + kwargs validation warning.
- **Stub todos + dead orchestrator:** todo API was a stub (returned []), orchestrator
  planner wrote to a scratch dir the UI never saw. Fixed: migration 006
  (todos table), full todo API, engine `_emit_todo_plan()` + SSE bridge.
