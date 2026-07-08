# 03 — Frontend: Mode State, Toggle, API

## State Location

Mode state lives in `App.jsx` (same level as `currentSessionId`).

```jsx
const [chatMode, setChatMode] = useState('agent')  // 'agent' | 'direct'
```

Passed down to `ChatInput` as a prop. `useChat` does not own it — mode is a
UI concern, not a chat state concern.

```
App.jsx
  chatMode, setChatMode
    └─ ChatInput.jsx  (mode, onModeToggle)
         └─ renders toggle button
```

`handleSend` in `App.jsx` passes `chatMode` through to `send()`:

```jsx
const handleSend = useCallback((text) => {
  send(text, chatMode)           // ← mode added as second arg
  if (currentSessionId === null) { setCurrentSessionId(sessionId); refreshSessions() }
}, [send, currentSessionId, sessionId, refreshSessions, chatMode])
```

---

## `useChat.js` — `send()` signature change

```js
const send = useCallback((text, mode = 'agent') => {
  ...
  const abort = streamChat({
    message: text,
    sessionId,
    file: currentFile,
    chatMode: mode,          // ← new field
    ...
  })
}, [isStreaming, sessionId, file])
```

The `AGENT_INTENTS` / `THINKING_INTENTS` sets remain unchanged. For `direct`
mode the incoming intent event will be `"direct"` — neither set contains it,
so `isAgent` will be `false` and the thinking block will not render. This is
correct behaviour.

---

## `api.js` — `streamChat()` change

```js
export function streamChat({
  message,
  sessionId,
  file,
  chatMode = 'agent',    // ← new param
  ...
}) {
  const form = new FormData()
  form.append('message', message)
  form.append('session_id', sessionId)
  form.append('chat_mode', chatMode)   // ← appended
  if (file) form.append('file', file)
  ...
}
```

---

## Toggle UI — `ChatInput.jsx`

A compact pill rendered left of the file upload icon inside `S.inputRow`.

### Props added
```jsx
// ChatInput({ onSend, isStreaming, onStop, file, onFile, mode, onModeToggle })
```

### Visual spec

```
┌─────────────────────────────────────────────┐
│ >  [⊞]  [A|D]  textarea…              [↵]  │
└─────────────────────────────────────────────┘
         ↑ file  ↑ mode toggle
```

- **`[A]`** — Agent mode, colour: `#39d353` (accent green)
- **`[D]`** — Direct mode, colour: `#e8a420` (amber)
- Width: `28px`, same height as send button (`30px`)
- Font: monospace, `11px`, `700` weight
- Title attribute: `"Agent mode — full pipeline"` / `"Direct mode — fast chat"`
- Click toggles between the two values

### Style object (inline, consistent with existing C/S pattern)
```js
modeBtn: (mode) => ({
  flexShrink: 0,
  width: '28px',
  height: '30px',
  borderRadius: '3px',
  border: `1px solid ${mode === 'agent' ? C.accent : C.amber}`,
  background: mode === 'agent' ? '#0d2a0d' : '#1a0d00',
  color: mode === 'agent' ? C.accent : C.amber,
  cursor: 'pointer',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  fontSize: '11px',
  fontFamily: C.mono,
  fontWeight: 700,
  letterSpacing: '0.04em',
  transition: 'all 0.12s',
})
```

### Hint line update
```
enter to send · shift+enter for newline · [A] agent  [D] direct
```

---

## StatusBar / ObservabilityPanel

No changes required. The `intent` field in `observabilityData` will display
`"direct"` as-is when in direct mode. No special casing needed.
