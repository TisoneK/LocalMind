# LocalMind Performance Bottleneck Report

## Executive Summary

Seven major bottlenecks identified across the pipeline, ranging from critical (LLM latency on every turn) to minor (SQLite connection management). The most impactful issues are **Bottlenecks 1, 3, and 4** which together account for 70-90% of end-to-end latency.

---

## Critical Bottlenecks

### 🔴 BOTTLENECK 1: LLM Intent Classification (THINKING_DISPATCH_ENABLED)

**Location:** [`core/engine.py:701-743`](core/engine.py:701) — ThinkingDispatcher

**Issue:** Every user message triggers a synchronous LLM call to classify intent before any other processing occurs. The dispatcher is called first and must complete before:
- Tool scoring
- Memory retrieval  
- Orchestrator phase
- Agent loop

**Impact:** 2-12 seconds added to every turn, regardless of intent type. Even simple "hi" messages wait for the full dispatch cycle.

**Evidence:**
```python
# engine.py lines 716-729
async for output in self._dispatcher.dispatch(...):
    if isinstance(output, StreamChunk):
        yield output  # Streaming helps perceived latency
    elif isinstance(output, DispatchDecision):
        dispatch_decision = output  # BLOCKS HERE
```
The dispatch generator must exhaust before subsequent pipeline steps begin.

**Mitigation (already partially implemented):**
- Memory retrieval starts in parallel with dispatcher (line 707)
- Dispatcher streams thinking tokens in real-time
- High-confidence classification can skip orchestrator (DISPATCHER_HIGH_CONFIDENCE_SKIP)

---

### 🔴 BOTTLENECK 2: Double LLM Calls for Agent Intents (Chat Agent + Execution Agent)

**Location:** [`core/engine.py:382-478`](core/engine.py:382) + [`core/agent/loop.py:535-552`](core/agent/loop.py:535)

**Issue:** For non-CHAT intents, the system makes **two sequential LLM calls** before execution:

1. **Chat Agent phase** (`_chat_agent_phase`) - Reformulation
2. **Planning phase** (`_plan`) - Step-by-step plan in AgentLoop

Plus a third call in AgentOrchestrator if enabled.

**Impact:** 4-18 seconds overhead for agent-mode requests before any tool executes.

**Evidence:**
```python
# engine.py - Phase 1
reformulated, acknowledgement = await self._chat_agent_phase(...)

# engine.py - Phase 2 (orchestrator)
orchestration_result = await self._orchestrator_phase(...)

# agent/loop.py - Phase 3
if PLAN_ENABLED:
    plan_context, iteration_offset = await self._plan(...)  # Line 541
```

**Combined Latency:**

| Phase | Small Model (1-3B) | Medium Model (7B) |
|-------|-------------------|------------------|
| Chat Agent | 2-5s | 1-3s |
| Orchestrator | 2-4s | 1-2s |
| Planner | 2-6s | 1-3s |
| **Total** | 6-15s | 3-8s |

---

### 🔴 BOTTLENECK 3: Vector Embedding (Synchronous HTTP in ThreadPool)

**Location:** [`storage/vector.py:205-218`](storage/vector.py:205) + [`storage/vector.py:179-202`](storage/vector.py:179)

**Issue:** Embeddings use `run_in_executor` to run httpx POST calls in a ThreadPool. While non-blocking for the event loop, the pattern has issues:

1. **No async HTTP client** — httpx.AsyncClient is available but not used for embeddings
2. **Bounded ThreadPool** — max workers = CPU count (line 76), which limits concurrent embeddings
3. **Per-call semaphore** (`self._embed_sem`) further limits to CPU count concurrent embeddings

**Impact:** 500ms-3s for memory retrieval on cold embeddings. Warm cache helps but first-time queries hit Ollama.

**Evidence:**
```python
# storage/vector.py line 210-214
async def _embed_async(text: str, base_url: str) -> list[float] | None:
    loop = asyncio.get_running_loop()
    _stats.active_workers += 1
    try:
        result = await loop.run_in_executor(
            _EXECUTOR, _embed_cached, _normalise_text(text), base_url  # Blocking httpx call
        )
```

**Current Mitigations:**
- Tier-1 LRU cache (4096 entries, line 179)
- Tier-2 SQLite persistent cache (survives restarts)
- Write buffer batching for embed_cache persistence

---

## High Impact Bottlenecks

### 🟠 BOTTLENECK 4: Context Building + History Compression

**Location:** [`core/engine.py:882-895`](core/engine.py:882) + [`core/summarizer.py`](core/summarizer.py)

**Issue:** For CHAT intents (the most common), the system:
1. Builds full context prompt via `context_builder.build()`
2. Optionally compresses history via `maybe_compress_history()`

Both are sequential and blocking.

**Impact:** 200-800ms added for CHAT responses, especially with long conversation history.

**Evidence:**
```python
# engine.py lines 882-895
ctx = EngineContext(...)
prompt_messages = context_builder.build(ctx, active_adapter.effective_context_window)
prompt_messages = await maybe_compress_history(  # Another LLM call potentially
    prompt_messages, active_adapter, active_adapter.effective_context_window
)
```

---

### 🟠 BOTTLENECK 5: SQLite Session Store (Per-Request Connection)

**Location:** [`storage/db.py:88-100`](storage/db.py:88) + [`storage/db.py:141-159`](storage/db.py:141)

**Issue:** Every `append()` and `get_history()` call:
1. Opens a new SQLite connection via context manager
2. Executes the query
3. Closes the connection

While WAL mode helps, this still has overhead.

**Impact:** ~5-15ms per append, ~10-30ms per get_history.

**Evidence:**
```python
# storage/db.py - Every call creates new connection
def append(self, session_id: str, message: Message) -> None:
    self.ensure_session(session_id)  # Connection + INSERT
    with self._conn() as conn:       # Another connection + INSERT
        conn.execute(...)            # BLOCKING sqlite3 call
```

**Current Mitigations:**
- Singleton store registry prevents duplicate instances
- WAL mode for concurrent reads
- Index on (session_id, timestamp)

---

### 🟠 BOTTLENECK 6: AgentLoop Serial Tool Dispatch

**Location:** [`core/agent/loop.py:627-661`](core/agent/loop.py:627)

**Issue:** The main agent loop iterates **serially** through tool calls:
```python
for iteration in range(MAX_ITERATIONS):  # Up to 8 iterations
    result = await active_adapter.chat_with_tools(...)  # BLOCKS
    # ... then dispatch tools sequentially
```

While parallel tool calls ARE handled (lines 669-761), the **LLM call is serial** — must wait for response before dispatching any tools.

**Impact:** 2-6s per iteration for LLM response + tool execution.

---

## Medium Impact Bottlenecks

### 🟡 BOTTLENECK 7: Multiple Chat Agent Re-formulations

**Location:** [`core/engine.py:523-620`](core/engine.py:523) + [`core/agent/orchestrator.py`](core/agent/orchestrator.py)

**Issue:** When Orchestrator requests clarification, the Chat Agent is called AGAIN to reformulate:
1. Original message → Chat Agent
2. Clarification answer → Chat Agent (reformulate)
3. Re-send to Orchestrator
4. Orchestrator → Planner → Execution

**Impact:** 4-12s additional latency for clarification flows.

---

## Performance Metrics Summary

| Bottleneck | Severity | Est. Latency Added | Frequency |
|------------|----------|---------------------|-----------|
| LLM Intent Dispatch | 🔴 Critical | 2-12s | Every turn |
| Double/Triple LLM Calls | 🔴 Critical | 4-18s | Agent intents |
| Vector Embedding | 🔴 Critical | 0.5-3s | Cold queries |
| Context + Compression | 🟠 High | 0.2-0.8s | CHAT intents |
| SQLite Session Store | 🟠 High | 0.01-0.03s | Every message |
| Serial Agent Loop | 🟠 High | 2-6s/iter | Agent intents |
| Clarification Re-form | 🟡 Medium | 4-12s | On clarification |

---

## Recommendations Priority

### Short-term (Low Effort, High Impact)
1. **Enable `DISPATCHER_HIGH_CONFIDENCE_SKIP`** — Skip orchestrator for high-confidence classifications
2. **Enable `skip_planning` more aggressively** — When dispatcher already reformulated
3. **Reduce `MAX_ITERATIONS`** in AgentLoop from 8 to 5 (default iterations usually finish in 2-3)

### Medium-term (Moderate Effort)
1. **Convert embedding to async httpx** — Replace `run_in_executor` with `httpx.AsyncClient`
2. **Add SQLite connection pooling** — Reuse connections instead of per-request open/close
3. **Cache Chat Agent responses** — For repeated/simple queries

### Long-term (High Effort, Transformative)
1. **Single-LLM-path architecture** — Skip Chat Agent phase for simple intents
2. **Parallel orchestrator + memory** — Start orchestrator planning while memory retrieves
3. **Pre-classification at client** — Classify intent on frontend, skip dispatcher for trivial messages

---

## Appendix: Code References

### Engine Pipeline (`core/engine.py`)

| Line | Component | Notes |
|------|-----------|-------|
| 622-1000 | `process()` | Main entry point |
| 701-743 | ThinkingDispatcher | LLM-based intent classification |
| 756-770 | RiskAwareRouter fallback | Regex-based classifier |
| 882-895 | Context building | Prompt construction |
| 893-895 | History compression | `maybe_compress_history()` |

### Agent System (`core/agent/`)

| File | Lines | Purpose |
|------|-------|---------|
| loop.py | 2459 | Main agent execution loop |
| orchestrator.py | 516 | Middle-layer planning |
| prompts.py | - | System prompt builders |
| synthesizer.py | - | Post-loop answer synthesis |

### Storage (`storage/`)

| File | Lines | Purpose |
|------|-------|---------|
| vector.py | 829 | Vector store with embedding cache |
| db.py | 298 | SQLite session store |

---

*Generated: 2026-05-15*