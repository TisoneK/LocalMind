# 04 — Implementation Tasks

Tasks are ordered by dependency. Each is independently committable.

---

## TASK-001 — `Engine.process_direct()`

**File:** `core/engine.py`

**Scope:** Add `process_direct()` async generator method to `Engine` class.

**Steps:**
1. Load history via `self._store.load(session_id)`
2. Run `maybe_compress_history(history)`
3. Retrieve memory facts via `MemoryComposer.retrieve(message, top_k=4)`
4. Build prompt: system fragment (`chat.md`) + last N history turns + memory
   facts as a prepended system note + user message
5. Call `self._adapter.chat(prompt_messages, intent="chat")`
6. Filter each chunk with `_filter_system_leaks()`
7. Yield `StreamChunk`
8. Persist user + assistant messages to `self._store`

**Does NOT call:** IntentRouter, tool dispatch, AgentLoop, FlywheelLogger,
MetricsStore, MemoryComposer.store()

**Acceptance:** Unit test in `tests/core/` — mock adapter, assert history
persisted, assert no tool calls made.

---

## TASK-002 — Route branching + `_event_stream_direct()`

**File:** `api/routes/chat.py`

**Scope:**
- Add `chat_mode: str = Form(default="agent")` to `chat()` endpoint
- Add `_event_stream_direct()` async generator
- Branch in `chat()` based on `chat_mode`

**`_event_stream_direct()` emits:**
1. Synthetic `{"intent": "direct", "confidence": 1.0}` SSE
2. Text chunks from `engine.process_direct()`
3. `{"text": "", "done": True}` on completion
4. `{"error": ..., "done": True}` on exception
5. Stage-2 title task (same as `_event_stream`)

**Acceptance:** Manual curl — `chat_mode=direct` returns SSE with
`intent=direct`, no tool SSE events.

---

## TASK-003 — `api.js` — pass `chat_mode`

**File:** `ui/src/lib/api.js`

**Scope:** Add `chatMode = 'agent'` param to `streamChat()`, append to
`FormData`.

**Acceptance:** Network tab shows `chat_mode` field in request payload.

---

## TASK-004 — `useChat.js` — thread `mode` through `send()`

**File:** `ui/src/hooks/useChat.js`

**Scope:**
- `send(text, mode = 'agent')` — second arg
- Pass `chatMode: mode` to `streamChat()`

**Acceptance:** `send('hi', 'direct')` triggers a direct-mode request.

---

## TASK-005 — `App.jsx` — mode state + prop drilling

**File:** `ui/src/App.jsx`

**Scope:**
- `const [chatMode, setChatMode] = useState('agent')`
- Pass `mode={chatMode}` and `onModeToggle={() => setChatMode(m => m === 'agent' ? 'direct' : 'agent')}` to `ChatInput`
- Pass `chatMode` to `handleSend` → `send(text, chatMode)`

**Acceptance:** Toggle in UI switches state; confirmed via React DevTools or
network tab.

---

## TASK-006 — `ChatInput.jsx` — mode toggle button

**File:** `ui/src/components/ChatInput.jsx`

**Scope:**
- Accept `mode` and `onModeToggle` props
- Add `modeBtn` style entry to `S` object
- Render `[A]` / `[D]` button inside `S.inputRow`, left of `FileUpload`
- Update hint line

**Acceptance:** Button visible, toggles green↔amber, label reflects mode.

---

## Order Summary

```
TASK-001  core/engine.py              (no frontend dependency)
TASK-002  api/routes/chat.py          (depends on TASK-001)
TASK-003  ui/src/lib/api.js           (independent)
TASK-004  ui/src/hooks/useChat.js     (depends on TASK-003)
TASK-005  ui/src/App.jsx              (depends on TASK-004)
TASK-006  ui/src/components/ChatInput.jsx  (depends on TASK-005)
```

Backend (001, 002) and frontend (003–006) tracks can be worked in parallel.
