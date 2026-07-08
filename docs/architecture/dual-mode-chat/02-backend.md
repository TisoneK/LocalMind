# 02 — Backend: Engine & Route

## Engine: `process_direct()`

New async generator on `Engine`. Lives in `core/engine.py` alongside the
existing `process()` method.

### Signature
```python
async def process_direct(
    self,
    message: str,
    session_id: str,
    file: bytes | None = None,
    filename: str | None = None,
    content_type: str | None = None,
    obs: ObsCollector | None = None,
    original_path: str | None = None,
) -> AsyncIterator[StreamChunk]:
```

### Steps

```
1. load_history(session_id)             — same call as process()
2. maybe_compress_history(history)      — same summariser gate
3. memory.retrieve(message, top_k=4)    — vector read, no write
4. build_prompt()                       — system + history + facts + user msg
                                          uses core/prompts/chat.md fragment
                                          same as CHAT intent path in process()
5. _adapter.chat(prompt_messages)       — raw stream, no tool schema injected
6. _filter_system_leaks(chunk.text)     — same safety filter as process()
7. yield StreamChunk(text, done)
8. store.append(session_id, user_msg)   — history persist
9. store.append(session_id, asst_msg)   — history persist
```

### What is NOT called
- `IntentRouter` / `RiskAwareRouter`
- `best_tool()` / `score_tools()`
- `dispatch()` / `AgentLoop`
- `FlywheelLogger` tool outcome recording
- `MemoryComposer.store()` (no write)
- `MetricsStore` tool tracking

`ObsCollector` is still passed in so the route can emit the synthetic `direct`
intent event before streaming starts.

---

## Route: `api/routes/chat.py`

### New form field
```python
chat_mode: str = Form(default="agent")   # "agent" | "direct"
```

### Branching

```python
if chat_mode == "direct":
    generator = _event_stream_direct(message, sid, is_first, ...)
else:
    generator = _event_stream(message, sid, is_first, ...)   # unchanged
```

`_event_stream_direct()` is a new private async generator in the same file.
It emits the synthetic intent SSE immediately, then delegates to
`engine.process_direct()`.

### `_event_stream_direct()` skeleton
```python
async def _event_stream_direct(message, session_id, is_first, ...):
    # Stage 1 title placeholder — identical to _event_stream
    if is_first:
        ...

    # Synthetic intent event — lets the UI show "direct" badge
    yield _sse({"intent": "direct", "confidence": 1.0})

    try:
        async for chunk in _engine.process_direct(message, session_id, ...):
            if chunk.error:
                yield _sse({"error": chunk.error, "done": True})
                return
            if chunk.done:
                yield _sse({"text": "", "done": True})
            elif chunk.text:
                yield _sse({"text": chunk.text, "done": False})
    except Exception as exc:
        yield _sse({"error": str(exc), "done": True})

    # Stage 2 title refinement — identical to _event_stream
    if is_first:
        asyncio.create_task(refine_title_async(session_id, message))
```

---

## API Contract

```
POST /api/chat
Content-Type: multipart/form-data

message:    str       (required)
session_id: str       (optional, uuid)
chat_mode:  str       (optional, default "agent")  ← NEW
file:       file      (optional)
```

No response shape changes. The `intent` SSE field will be `"direct"` for
direct-mode messages instead of a classified intent string. Confidence is
always `1.0` for direct mode (it is not inferred).
