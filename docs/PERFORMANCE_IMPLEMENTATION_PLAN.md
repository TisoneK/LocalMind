# Performance Optimization Implementation Plan

**Document:** Implementation Plan for Performance Bottlenecks
**Source:** `docs/PERFORMANCE_BOTTLENECK_REPORT.md`
**Generated:** 2026-05-15

> ## ⚠️ STATUS: HISTORICAL RECORD (snapshot 2026-05-15)
>
> This plan is kept as a historical record. Several items are now DONE or
> SUPERSEDED — see `docs/PERFORMANCE_BOTTLENECK_REPORT.md` for the full
> banner. The two most important corrections:
>
> - **§1.2 (Reduce MAX_ITERATIONS 8→5) is SUPERSEDED.** Per the Session 32
>   contract, `MAX_ITERATIONS` defaults to 8 (configurable via
>   `LOCALMIND_MAX_ITERATIONS`) and must NOT be lowered below 8 — multi-step
>   tasks (recon + work + verify) need the room.
> - **§1.1 (DISPATCHER_HIGH_CONFIDENCE_SKIP 0.7→0.6) is DONE/removed.** The
>   threshold was set to 0.6, and B-2026-08-09-11 removed the constant from
>   `agent/constants.py` entirely (the skip logic lives in `_pipeline.py`).
> - **Phase 2+ recommendations were NOT status-checked** (async httpx
>   embedding, SQLite connection pooling, Chat Agent response caching) —
>   verify against the current code before acting on them.

---

## Executive Summary

This document provides a prioritized implementation plan to address the 7 performance bottlenecks identified in the performance report. The plan is organized into three phases based on effort vs. impact.

**Key Findings:**
- 3 critical bottlenecks account for 70-90% of end-to-end latency
- Many mitigations are already partially implemented via configuration flags
- Quick wins available through configuration tuning alone

**Expected Total Impact:**
| Phase | Latency Reduction | Effort |
|-------|-------------------|--------|
| Phase 1 (Quick Wins) | 40-60% | 1-2 days |
| Phase 2 (Medium-term) | 25-35% | 1-2 weeks |
| Phase 3 (Long-term) | 10-20% | 2-4 weeks |

---

## Phase 1: Quick Wins (Configuration Changes Only)

### 1.1 Optimize DISPATCHER_HIGH_CONFIDENCE_SKIP (Bottleneck 1)

> ✅ **DONE (superseded by later refactors).** The threshold was set to 0.6,
> and the skip logic moved into `_pipeline.py`; B-2026-08-09-11 removed the
> now-dead constant from `agent/constants.py`. Retained as history.

**Problem:** High-confidence classifications still route through Orchestrator + Planning phases.

**Current State:**
```python
# core/agent/constants.py:308
DISPATCHER_HIGH_CONFIDENCE_SKIP: float = 0.7
```
The dispatcher already classified intent with high confidence, but runs two additional LLM calls.

**Recommended Changes:**

1. **Adjust threshold for more aggressive skipping:**
   ```python
   # core/agent/constants.py:308 — Change from 0.7 to 0.6
   DISPATCHER_HIGH_CONFIDENCE_SKIP: float = 0.6
   ```
   At 0.6, ~60% of intents would skip orchestrator vs ~40% at 0.7.

2. **Add additional skip conditions in `core/engine.py:747`:**
   ```python
   # Add after line 747 — skip orchestrator for trivial CHAT
   _skip_orchestrator = (
       _dispatcher_fast_path or 
       confidence >= DISPATCHER_HIGH_CONFIDENCE_SKIP or
       (primary_intent == Intent.CHAT and confidence >= 0.55 and not _dispatcher_reformulated)
   )
   ```

3. **Streamline fast-path detection in dispatcher** — ensure `dispatch_decision.fast_path` is set correctly for simple queries.

**Estimated Impact:** Save 2-6s per turn for ~40-60% of requests.

**Files to Modify:**
- `core/agent/constants.py:308` — Threshold adjustment
- `core/engine.py:744-760` — Add skip conditions

**Effort:** 1-2 hours

---

### 1.2 Reduce MAX_ITERATIONS (Bottleneck 6)

> ⛔ **SUPERSEDED (Session 32 contract).** Do NOT reduce MAX_ITERATIONS
> below 8 — see the banner at the top of this file. Multi-step tasks need
> the room; the wall-clock cap (`LOCALMIND_MAX_WALL_CLOCK_SECS`, default
> 180s) is the real safety net. This section is retained only as history.

**Problem:** Agent loop allows 8 iterations, but typical tasks complete in 2-3.

**Current State:**
```python
# core/agent/constants.py:11
MAX_ITERATIONS: int = 8
```

**Recommended Change:**
```python
# core/agent/constants.py:11 — Reduce from 8 to 5
MAX_ITERATIONS: int = 5
```

**Rationale:**
- Average completion: 2-3 iterations (85% of tasks)
- 4-5 iterations: ~10% of complex tasks
- 6+ iterations: ~5% (usually indicates confusion, additional iterations don't help)

**Alternative:** Make it configurable:
```python
# core/agent/constants.py:11
MAX_ITERATIONS: int = 5  # Set to 8 only if PLAN_ENABLED=True
# Or in config.py:
localmind_agent_max_iterations: int = Field(default=5, ge=1, le=8)
```

**Estimated Impact:** Save 2-6s per iteration for the 5% of tasks that hit iteration limit.

**Files to Modify:**
- `core/agent/constants.py:11`

**Effort:** 15 minutes

---

### 1.3 Enable More Aggressive skip_planning (Bottleneck 2)

**Problem:** Planning phase runs even when dispatcher already reformulated.

**Current State:**
```python
# core/agent/loop.py:535
if PLAN_ENABLED and intent in AGENT_INTENTS and not initial_tool_result and not skip_planning:
```

**Recommended Changes:**

1. **In `core/engine.py` — pass skip_planning when dispatcher was confident:**
   ```python
   # Around line 900 — add skip_planning parameter
   skip_planning = (
       confidence >= DISPATCHER_HIGH_CONFIDENCE_SKIP or
       _dispatcher_fast_path
   )
   ```

2. **Extend the skip condition in loop.py:535:**
   ```python
   if PLAN_ENABLED and intent in AGENT_INTENTS and not initial_tool_result:
       # Skip planning when dispatcher already did high-quality reformulation
       should_skip = skip_planning or (
           confidence >= DISPATCHER_HIGH_CONFIDENCE_SKIP and
           _dispatcher_reformulated and
           _dispatcher_reformulated != message  # dispatcher changed the message
       )
       if not should_skip:
           # ... planning logic
   ```

**Estimated Impact:** Save 2-6s per agent-mode request when dispatcher was confident.

**Files to Modify:**
- `core/engine.py` — Add skip_planning calculation
- `core/agent/loop.py:535` — Extend skip condition

**Effort:** 1-2 hours

---

### 1.4 Disable CHAT_AGENT for Simple Intents (Bottleneck 2, 7)

**Problem:** Chat Agent reformulates even simple queries unnecessarily.

**Current State:**
```python
# core/agent/constants.py:157
CHAT_AGENT_ENABLED: bool = True
```

**Recommended Changes:**

1. **Make CHAT_AGENT conditional on intent complexity:**
   ```python
   # core/agent/constants.py:157
   CHAT_AGENT_ENABLED: bool = True
   
   # Add new: threshold for disabling chat agent
   CHAT_AGENT_MIN_COMPLEXITY: float = 0.4
   ```

2. **In `core/engine.py:382` — add complexity check:**
   ```python
   async def _chat_agent_phase(..., confidence: float = 0.5):
       # Skip chat agent for high-confidence simple intents
       if not CHAT_AGENT_ENABLED:
           return message, ""
       if confidence >= 0.8 and _is_simple_query(message):
           return message, ""  # Skip reformulation
   ```

3. **Add simple query detection:**
   ```python
   def _is_simple_query(message: str) -> bool:
       """Detect queries that don't need reformulation."""
       simple_patterns = [
           r'^(hi|hello|hey|help|thanks|thank you)',
           r'^(what is|what are|how do|how does)',
           r'^(yes|no|ok|okay|sure)',
       ]
       return any(re.match(p, message.lower()) for p in simple_patterns)
   ```

**Estimated Impact:** Save 2-5s per simple query that triggers agent mode.

**Files to Modify:**
- `core/agent/constants.py:157-170` — Add configuration
- `core/engine.py:382-478` — Add complexity check

**Effort:** 2-3 hours

---

### 1.5 Phase 1 Summary

| Change | Impact | Effort | Risk |
|--------|--------|--------|------|
| Lower DISPATCHER_HIGH_CONFIDENCE_SKIP to 0.6 | 2-6s saved on 40-60% requests | 15 min | Low |
| Reduce MAX_ITERATIONS to 5 | 2-6s saved on 5% of agent tasks | 15 min | Low |
| Pass skip_planning from engine | 2-6s saved on 30% of agent tasks | 1 hour | Medium |
| Skip CHAT_AGENT for simple queries | 2-5s saved on 15% of requests | 2 hours | Low |

**Phase 1 Total Estimated Improvement:** 40-60% latency reduction on typical workloads

---

## Phase 2: Medium-term Optimizations

### 2.1 Convert Embedding to Async HTTP (Bottleneck 3)

**Problem:** Embeddings use blocking `run_in_executor` with bounded thread pool.

**Current State:**
```python
# storage/vector.py:205-218
async def _embed_async(text: str, base_url: str) -> list[float] | None:
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        _EXECUTOR, _embed_cached, _normalise_text(text), base_url
    )
```

**Recommended Change:**

1. **Replace blocking httpx with async httpx:**
   ```python
   # storage/vector.py:205-218 — Replace with async implementation
   import httpx
   
   # Add at module level
   _async_client: httpx.AsyncClient | None = None
   
   async def _get_async_client() -> httpx.AsyncClient:
       global _async_client
       if _async_client is None or _async_client.is_closed:
           _async_client = httpx.AsyncClient(timeout=_EMBED_TIMEOUT)
       return _async_client
   
   async def _embed_async(text: str, base_url: str) -> list[float] | None:
       """True async embedding — no thread pool needed."""
       norm_text = _normalise_text(text)
       
       # Check LRU cache first (sync, fast)
       cached = _embed_cached(norm_text, base_url)
       if cached:
           return list(cached)
       
       # Check SQLite persistent cache
       persistent = _get_persistent_cache(norm_text, base_url)
       if persistent:
           return persistent
       
       # True async HTTP call — no thread pool blocking
       client = await _get_async_client()
       embed_model = _get_embed_model()
       
       try:
           response = await client.post(
               f"{base_url.rstrip('/')}/api/embeddings",
               json={"model": embed_model, "prompt": norm_text}
           )
           if response.status_code == 200:
               embedding = response.json().get("embedding")
               if embedding:
                   # Store in caches asynchronously
                   _safe_persist_async(norm_text, base_url, tuple(embedding))
                   return embedding
       except Exception as e:
           logger.warning(f"Async embedding failed: {e}")
       
       return None
   ```

2. **Remove ThreadPoolExecutor (optional, for cleaner architecture):**
   ```python
   # storage/vector.py:73-76 — Comment out or remove
   # _EXECUTOR = ThreadPoolExecutor(max_workers=os.cpu_count() or 4)
   ```

3. **Keep the bounded concurrency via asyncio.Semaphore instead:**
   ```python
   _embed_sem = asyncio.Semaphore(8)  # Allow 8 concurrent embedding requests
   
   async def _embed_async(text: str, base_url: str) -> list[float] | None:
       async with _embed_sem:
           # ... embedding logic
   ```

**Estimated Impact:** 
- Remove thread pool context-switching overhead
- Increase concurrent embedding capacity from CPU-count to 8+
- Save 50-200ms per cold embedding

**Files to Modify:**
- `storage/vector.py:205-218` — Async implementation
- `storage/vector.py:73-76` — Remove or repurpose executor

**Effort:** 4-6 hours

**Dependencies:** None (self-contained)

---

### 2.2 Add SQLite Connection Pooling (Bottleneck 5)

**Problem:** Every `append()` and `get_history()` opens/closes a new connection.

**Current State:**
```python
# storage/db.py:87-100
@contextmanager
def _conn(self) -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(str(self._path))
    # ...
    conn.close()  # Closed immediately
```

**Recommended Changes:**

1. **Add connection pool:**
   ```python
   # storage/db.py:245-248 — Add pooling
   from queue import Queue, Empty
   
   class _ConnectionPool:
       """Lightweight connection pool for SQLite."""
       def __init__(self, db_path: str, max_connections: int = 4):
           self._db_path = db_path
           self._max_connections = max_connections
           self._pool: Queue[sqlite3.Connection] = Queue(max_connections)
           self._lock = threading.Lock()
       
       def _create_connection(self) -> sqlite3.Connection:
           conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
           conn.row_factory = sqlite3.Row
           conn.execute("PRAGMA foreign_keys = ON")
           conn.execute("PRAGMA journal_mode = WAL")
           return conn
       
       def get_conn(self) -> sqlite3.Connection:
           """Get a connection from the pool, creating if needed."""
           try:
               return self._pool.get_nowait()
           except Empty:
               with self._lock:
                   # Create new connection if under limit
                   if self._pool.qsize() < self._max_connections:
                       return self._create_connection()
                   # Block and wait
                   return self._pool.get(timeout=5.0)
       
       def return_conn(self, conn: sqlite3.Connection) -> None:
           """Return connection to the pool."""
           try:
               self._pool.put_nowait(conn)
           except Exception:
               conn.close()  # Pool full, close it
   
   # Module-level pool
   _db_pools: dict[str, _ConnectionPool] = {}
   _pools_lock = threading.Lock()
   
   def _get_pool(db_path: str) -> _ConnectionPool:
       with _pools_lock:
           if db_path not in _db_pools:
               _db_pools[db_path] = _ConnectionPool(db_path)
           return _db_pools[db_path]
   ```

2. **Update SessionStore to use pool:**
   ```python
   # storage/db.py:82-100 — Update __init__ and _conn
   class SessionStore:
       def __init__(self, db_path: str = "./localmind.db"):
           self._path = Path(db_path)
           self._path.parent.mkdir(parents=True, exist_ok=True)
           self._pool = _get_pool(str(self._path))
           self._init_db()
       
       @contextmanager
       def _conn(self) -> Generator[sqlite3.Connection, None, None]:
           conn = self._pool.get_conn()
           try:
               yield conn
               conn.commit()
           except Exception:
               conn.rollback()
               raise
           finally:
               self._pool.return_conn(conn)
   ```

**Estimated Impact:** Save 5-10ms per append, 10-20ms per get_history.

**Files to Modify:**
- `storage/db.py:80-100` — Add pooling class and update SessionStore

**Effort:** 3-4 hours

---

### 2.3 Cache Chat Agent Responses (Bottleneck 2, 7)

**Problem:** Repeated or simple queries still trigger full Chat Agent reformulation.

**Recommended Changes:**

1. **Add LRU cache for Chat Agent responses:**
   ```python
   # In core/engine.py — add module-level cache
   from functools import lru_cache
   from hashlib import sha256
   
   _chat_agent_cache: LRUCache[str, tuple[str, str]] = LRUCache(maxsize=256)
   
   def _get_cache_key(message: str, intent: Intent) -> str:
       """Create cache key from message and intent."""
       return sha256(f"{intent.value}:{message[:200]}".encode()).hexdigest()
   
   async def _chat_agent_phase(...):
       # Check cache first
       cache_key = _get_cache_key(message, intent)
       if cache_key in _chat_agent_cache:
           return _chat_agent_cache[cache_key]
       
       # ... existing logic ...
       
       # Cache successful responses
       _chat_agent_cache[cache_key] = (reformulated, acknowledgement)
       return reformulated, acknowledgement
   ```

2. **Add cache invalidation on model change:**
   ```python
   # In core/engine.py — on model change
   def _on_model_change():
       _chat_agent_cache.clear()
   ```

**Estimated Impact:** Save 2-5s for repeated queries (15-25% of requests).

**Files to Modify:**
- `core/engine.py` — Add cache logic

**Effort:** 2-3 hours

---

### 2.4 Phase 2 Summary

| Change | Impact | Effort | Risk |
|--------|--------|--------|------|
| Async embedding with httpx | 50-200ms saved on cold embeds | 6 hours | Medium |
| SQLite connection pooling | 5-20ms saved per operation | 4 hours | Low |
| Chat Agent response caching | 2-5s saved on 15-25% requests | 3 hours | Low |

**Phase 2 Total Estimated Improvement:** 25-35% additional latency reduction

---

## Phase 3: Long-term Architectural Changes

### 3.1 Single-LLM-Path Architecture (Bottleneck 1, 2)

**Problem:** Simple intents still go through multiple LLM calls (dispatcher → chat agent → orchestrator → planner).

**Recommended Change:**

1. **Add "instant" intent detection:**
   ```python
   # core/engine.py — Add fast-path detection
   INSTANT_INTENTS = frozenset({Intent.CHAT})
   INSTANT_CONFIDENCE_THRESHOLD = 0.85
   
   async def _try_fast_path(message: str, ...):
       """Attempt single-LLM path for simple intents."""
       # Check if message is "trivial"
       if _is_trivial_message(message) and confidence >= INSTANT_CONFIDENCE_THRESHOLD:
           return True  # Skip to direct chat
       return False
   
   def _is_trivial_message(message: str) -> bool:
       """Detect messages that don't need agent processing."""
       # Less than 20 chars, no tool-like keywords
       if len(message) < 20:
           keywords = ['search', 'write', 'read', 'file', 'code', 'execute', 'run']
           if not any(k in message.lower() for k in keywords):
               return True
       return False
   ```

2. **Short-circuit the pipeline:**
   ```python
   # core/engine.py:700-770 — Add fast path check
   if THINKING_DISPATCH_ENABLED:
       # ... existing dispatcher logic ...
       
       # NEW: Fast path for trivial high-confidence CHAT
       if (
           primary_intent == Intent.CHAT and
           confidence >= INSTANT_CONFIDENCE_THRESHOLD and
           _is_trivial_message(message)
       ):
           # Skip to direct context building + chat
           _skip_stages = ['chat_agent', 'orchestrator', 'planner']
           logger.info("[engine] Fast path: trivial CHAT, skipping to direct response")
   ```

**Estimated Impact:** Save 4-12s for trivial messages.

**Files to Modify:**
- `core/engine.py` — Add fast-path logic

**Effort:** 8-12 hours

---

### 3.2 Parallel Orchestrator + Memory (Bottleneck 1, 4)

**Problem:** Orchestrator waits for memory retrieval to complete.

**Current State:**
```python
# core/engine.py — Sequential
memory_facts = await self._memory.compose(...)  # 500ms-2s
orchestration_result = await self._orchestrator_phase(...)  # 2-4s
```

**Recommended Change:**

1. **Run orchestrator planning in parallel with memory:**
   ```python
   # core/engine.py — Parallel execution
   async def _run_orchestrator_with_memory(...):
       # Start both tasks
       memory_task = asyncio.create_task(
           self._memory.compose(query=message, intent=intent, session_id=session_id)
       )
       orchestrator_task = asyncio.create_task(
           self._orchestrator_phase(reformulated_message, intent, session_id, obs, [], intent_history)
       )
       
       # Memory needs orchestrator context for filtering
       # So we can't fully parallelize, but can overlap the LLM call with I/O
       
       # Wait for orchestrator first (it's the longer task)
       orch_result = await orchestrator_task
       
       # Then get memory with context
       memory_facts = await memory_task
       
       return orch_result, memory_facts
   ```

2. **Refactor memory to not need orchestrator context:**
   - Instead of waiting for intent, use message directly for retrieval
   - Post-filter results based on intent

**Estimated Impact:** Save 500ms-2s for agent-mode requests.

**Files to Modify:**
- `core/engine.py` — Parallel execution
- `core/memory.py` — Refactor memory composition

**Effort:** 8-12 hours

---

### 3.3 Pre-classification at Client (Bottleneck 1)

**Problem:** Even "hello" triggers a full dispatcher LLM call.

**Recommended Change:**

1. **Add frontend simple classification:**
   ```typescript
   // ui/src/hooks/useLocalMind.ts — Add client-side classification
   const SIMPLE_PATTERNS = [
     /^(hi|hello|hey|help|thanks)/i,
     /^[\s\W]+$/,  // Only whitespace/punctuation
     /^.{0,10}$/    // Very short messages
   ];
   
   function classifyIntent(message: string): 'simple' | 'complex' {
     for (const pattern of SIMPLE_PATTERNS) {
       if (pattern.test(message)) {
         return 'simple';
       }
     }
     return 'complex';
   }
   
   // In chat handler:
   const intent = classifyIntent(message);
   if (intent === 'simple') {
     // Send with header: X-LocalMind-Intent: CHAT, X-Intent-Confidence: 1.0
     // Server skips dispatcher
   }
   ```

2. **Add server-side support:**
   ```python
   # core/engine.py — Check for client-provided intent
   async def process(...):
       # Check for client pre-classification
       client_intent = request.headers.get('X-LocalMind-Intent')
       client_confidence = request.headers.get('X-Intent-Confidence', 0.5)
       
       if client_intent and float(client_confidence) >= 0.9:
           # Skip dispatcher
           primary_intent = Intent(client_intent)
           confidence = float(client_confidence)
           # Still run dispatcher for display purposes (streaming)
           # But don't wait for it
   ```

**Estimated Impact:** Save 2-12s for trivial messages (10-20% of total).

**Files to Modify:**
- `ui/src/hooks/useLocalMind.ts` — Client classification
- `core/engine.py` — Server-side header handling

**Effort:** 6-8 hours

---

### 3.4 Phase 3 Summary

| Change | Impact | Effort | Risk |
|--------|--------|--------|------|
| Single-LLM-path for trivial messages | 4-12s saved on 10-20% requests | 12 hours | High |
| Parallel orchestrator + memory | 500ms-2s saved on agent requests | 12 hours | Medium |
| Client-side pre-classification | 2-12s saved on trivial messages | 8 hours | Medium |

**Phase 3 Total Estimated Improvement:** 10-20% additional latency reduction

---

## Implementation Roadmap

### Week 1: Quick Wins
- Day 1: Adjust `DISPATCHER_HIGH_CONFIDENCE_SKIP` threshold
- Day 2: Reduce `MAX_ITERATIONS` to 5
- Day 3: Implement `skip_planning` propagation
- Day 4: Add simple query detection for Chat Agent
- Day 5: Testing and validation

### Week 2: Medium-term
- Day 1-2: Async embedding implementation
- Day 3: SQLite connection pooling
- Day 4: Chat Agent caching
- Day 5: Integration testing

### Week 3-4: Long-term
- Day 1-3: Single-LLM-path architecture
- Day 4-5: Parallel orchestrator + memory
- Day 6-7: Client-side pre-classification

---

## Configuration Changes Summary

| Setting | Current | Phase 1 | Phase 2 | Phase 3 |
|---------|---------|---------|---------|---------|
| `DISPATCHER_HIGH_CONFIDENCE_SKIP` | 0.7 | 0.6 | - | - |
| `MAX_ITERATIONS` | 8 | 5 | - | - |
| `CHAT_AGENT_MIN_COMPLEXITY` | N/A | 0.4 | - | - |
| `_BATCH_CONCURRENCY` (vector) | 4 | - | 8 | - |
| Connection pool size (db) | N/A | - | 4 | - |
| Chat Agent cache size | N/A | - | 256 | - |

---

## Testing Strategy

### Performance Benchmarks
1. **Measure baseline:** Record latency for each intent type before changes
2. **Incremental testing:** Measure after each change
3. **Target metrics:**
   - CHAT intent: < 500ms p95
   - Agent intents: < 5s p95
   - Vector embedding: < 200ms p95

### Regression Testing
- Ensure quality doesn't degrade with faster responses
- Test clarification flows still work correctly
- Validate agent loop still produces correct outputs with fewer iterations

### Load Testing
- Test concurrent embedding requests
- Test connection pool under load
- Validate cache hit rates

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Lowering thresholds causes quality issues | Keep configurable, add monitoring |
| Fewer iterations causes incomplete answers | Track iteration count in metrics |
| Connection pool causes stale reads | Use WAL mode, proper isolation |
| Cache causes stale responses | Add TTL, invalidate on model change |

---

*Document Version: 1.0*
*Last Updated: 2026-05-15*