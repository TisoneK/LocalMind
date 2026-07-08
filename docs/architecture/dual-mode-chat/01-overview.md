# 01 — System Overview: Dual-Mode Chat

## Problem

The current pipeline always runs the full engine: intent classification → tool
scoring → memory retrieval → tool dispatch → agent loop → LLM generate →
memory persist. For a quick conversational exchange this is unnecessary overhead
and causes latency, especially on low-end hardware or small models.

The user needs two distinct paths selectable at runtime:

| Mode | Intent | Speed | Tools | Memory write |
|---|---|---|---|---|
| **Agent** | Full pipeline, current default | Slower | Yes | Yes |
| **Direct** | Raw Ollama stream | Fast | No | No |

## Request Flow Comparison

### Agent Mode (current, unchanged)
```
POST /api/chat  chat_mode=agent
  └─ chat.py._event_stream()
       └─ engine.process()          ← full 10-step pipeline
            ├─ history load
            ├─ intent classify (LLM + rule fallback)
            ├─ tool scoring
            ├─ memory retrieval
            ├─ tool dispatch
            ├─ context build
            ├─ agent loop (if AGENT_INTENTS)  OR  direct stream (CHAT/SYSINFO)
            ├─ memory persist
            └─ history persist
```

### Direct Mode (new)
```
POST /api/chat  chat_mode=direct
  └─ chat.py._event_stream_direct()
       └─ engine.process_direct()   ← thin path
            ├─ history load         ← retained (model needs context)
            ├─ memory retrieval     ← retained (vector read-only)
            ├─ build minimal prompt (system + history + facts + user msg)
            ├─ stream raw Ollama response
            └─ history persist      ← retained (session continuity)
```

Steps **skipped** in direct mode:
- Intent classification
- Tool scoring and dispatch
- Agent loop
- Memory persist (no new facts written)
- Observability tool events (intent SSE event is still emitted as `direct`)

## SSE Contract Change

Direct mode emits a synthetic intent event so the frontend can reflect the mode:

```json
{"intent": "direct", "confidence": 1.0}
```

All other SSE fields (`text`, `done`) are identical to agent mode. The frontend
needs no special handling beyond displaying the mode label.

## Session Continuity

Mode is per-message, not per-session. The user can freely switch mid-session.
History is always written, so a direct-mode message followed by an agent-mode
message works without gaps.
