# LocalMind Context Architecture Research — 2026-09-04

**Trigger:** User-provided architecture critique (pasted conversation) directing a research-first approach BEFORE touching LocalMind code. The critique's core thesis: "Never send context merely because it exists. Context is not synonymous with state. The goal is minimum sufficient context, not minimum context possible or maximum available context."

**Method:** 5 parallel research subagents (R-A through R-E) covering: Claude Code + Anthropic (A+F), OpenCode (B), Zed (C), Codex + ChatGPT (D+E), prompt caching + local models (G+L). Plus codebase verification of the research's claims against LocalMind's actual code, plus a live cache-passthrough test on bankofai/qwen3.8-flash.

**Status:** Research only. NO code changes this milestone. This report feeds the Implementation Plan (next milestone).

---

## PART 1 — COMMON PATTERNS (what every mature agent harness does)

Across Claude Code, OpenCode, Zed, Codex, and ChatGPT, five patterns are universal:

### 1. Layered context, not a flat blob

Every mature harness separates context into layers with different stability + mutation rules:

| Layer | Content | Mutates | Cache impact |
|-------|---------|---------|--------------|
| **System** (most stable) | Core instructions, tool definitions | Only when tools/instructions change | Byte-stable prefix → cacheable |
| **Project** (per-session stable) | AGENTS.md/CLAUDE.md, memory, skills catalog | On session start, `/compact`, or file change | Cacheable within a session |
| **Conversation** (grows) | Messages, tool calls, tool results | Append-only every turn | Prefix preserved; new content extends past breakpoint |
| **Just-in-time** (per-call dynamic) | File contents, skill bodies, per-turn environment | Every call | NOT cached — placed at the tail |

**LocalMind today:** ADR-39 (Session 245) already split the environment block out of the cached system prompt — this is the right pattern. But the split is incomplete: `memory_facts`, `intent_history`, and `task_state_refresh` are still injected into the per-iteration context message, and the system prompt still conditionally includes skill fragments + personas + safety sections that vary by intent. The prefix is not fully byte-stable across intents.

### 2. Provider prompt caching is the default cost-reduction mechanism — not "send less"

Every cloud provider (Anthropic, OpenAI, Gemini, DeepSeek, Qwen/Dashscope) offers prefix caching at ~90% discount on cache hits. The architecture question is NOT "how do I send less?" but "how do I keep the prefix byte-stable so the cache hits?"

- **Anthropic:** explicit `cache_control` markers, 4 breakpoints, 5m/1h TTL, 90% off on reads
- **OpenAI:** automatic prefix caching (GPT-5+), 90% off on reads, 30m TTL
- **DeepSeek:** automatic disk-based, 90% off
- **Qwen/Dashscope:** both implicit (20% off) AND explicit `cache_control` (90% off) — same syntax as Anthropic
- **Gemini:** implicit (auto) + explicit (cachedContent objects), 90% off

**LocalMind today (verified this session):**
- `openai_compat.py:1424` sends `cache_control: {type: ephemeral}` markers ✓
- `openai_compat.py:718` captures `cached_tokens` across all 3 provider field names ✓
- `loop.py:3536` logs the cache hit rate per iteration ✓
- **Live test (bankofai/qwen3.8-flash, this session):** call 1 = 0 cached / 1256 prompt; call 2 = **1024 cached / 1256 prompt (81.5% hit rate)**. The cache IS working through bankofai to qwen.

**The gap:** The frontend's "Context %" display uses `prompt_tokens_approx` (a chars/4 estimate of the FULL prompt) — NOT the provider-reported `cached_tokens`. So the user sees the UNDISCOUNTED number. The user's "19.4K prompt / Context 59%" is the undiscounted cumulative; the real inference cost after cache is ~40-50% lower. The cache data exists in the backend but never reaches the UI.

### 3. Compaction = checkpoint + recent tail (not "delete old messages")

Three layers, all confirmed across Claude Code + OpenCode + Zed:

| Layer | Trigger | Mechanism | What's preserved |
|-------|---------|-----------|------------------|
| **Microcompaction** | Per-tool-result size | Offload bulky tool results to disk, keep small hot tail inline | Recent N results verbatim; older as path references |
| **Auto-compaction** | Headroom accounting (not fixed %) | LLM summarizes conversation into structured checkpoint | Summary + recent tail (2-15K tokens) + rehydrated files/todos/plan |
| **Manual `/compact`** | User-initiated | Same as auto, with optional focus hint | Same + focus constraint |

**Critical:** The durable underlying session history survives compaction. The model sees `[checkpoint_summary, ...recent_tail]`; the UI sees the full history. Compaction only changes the model-facing view.

**LocalMind today:** `context_compactor.py` does microcompaction (S410 tightened it: keep_last=1, stub=400). `maybe_compress_history` does LLM summarization past 75% budget. But there's NO structured checkpoint (the summary is free-form), NO rehydration after compaction (no file/todo/plan restoration), and the durable history is the model-facing history (no separation). This is the biggest gap vs. mature harnesses.

### 4. Tool scoping per call (not all tools every call)

Every harness has moved away from "advertise every tool every call":

- **Claude Code:** Tool Search (Jan 2026) — when MCP tools exceed 10K tokens, defer all; model searches and loads 3-5 relevant tools on demand. ~85% token reduction.
- **OpenCode:** per-agent permission rulesets filter the tool advertisement map. The `explore` agent gets read-only; `compaction`/`title`/`summary` internal agents get `tools: {}` (zero tools).
- **Zed:** agent profiles (`write`/`ask`/`minimal`) filter the globally-registered tool set. `minimal` sends zero tool schemas.
- **Codex:** static-first tool ordering + deterministic tool list (non-deterministic order is a cache-killer).

**LocalMind today:** ADR-40 (Session 252) + S411 moved 22 tools behind `describe_tool`. 11 core tools remain always-present. This is aligned with the pattern. The remaining gap: the 11 core tools still invalidate the entire cache if their schemas change between calls (e.g., when `loaded_tools` set changes mid-run via `describe_tool`).

### 5. Internal maintenance agents get clean context

Claude Code, OpenCode, and Zed all run title/summary/compaction as internal agents with:
- `tools: {}` (zero tool advertisement — zero tool-schema tokens)
- `system: []` (empty system array — only the agent's own prompt)
- A cheaper/smaller model (e.g., Haiku for title)
- Forked/async — don't block the main loop, don't share its message stream

**LocalMind today:** Title generation + classification use a "chat" call path (no tools), but they still carry the ~500-token chat system prompt. There's no "zero system, zero tools, small model" internal-agent pattern. The compaction summarizer (if wired) would inherit the full agent context.

---

## PART 2 — ANTI-PATTERNS (what mature harnesses stopped doing)

### 1. "Trivial vs agent" routing as the solution to context bloat

The critique explicitly warned: "trivial-vs-agent routing can still exist later as an optimization, but it should sit above or alongside the Context Engine — not be the solution to the 6K baseline." S410-S412 (my prior work) operated INSIDE the dump-everything architecture — they reduced the dump size but didn't change the architecture from "dump everything" to "select relevant context." This is the anti-pattern the critique flagged.

### 2. Re-sending state because it exists

Every harness distinguishes "state" (what the app knows) from "model context" (what the model needs for THIS call). LocalMind's pipeline sends `memory_facts` + `intent_history` + `observation_log` + `task_state_refresh` on EVERY iteration — these are state, not per-call context. A mature agent retrieves relevant memory per request (via a memory tool or retrieval step), not dumps all memory every call.

### 3. Mutating the prefix mid-session

Claude Code: "CLAUDE.md edits mid-session don't apply — they're loaded once at session start, so editing them mid-session neither invalidates the cache nor applies the change." OpenCode: instruction epoch — "render once, freeze, replay verbatim." Codex: "static content first; mutations are append-only."

LocalMind's `build_agent_system_prompt` rebuilds the system prompt every call from `base.md` + intent fragment + safety section + persona + agent_context + plan + orchestrator hint. If any of these vary between calls (different intent → different persona → different safety section), the prefix changes and the cache misses.

### 4. Treating the token meter as the cost

The critique: "Logical context ≠ Serialized request ≠ Fresh input tokens ≠ Cached input tokens ≠ Actual inference work." LocalMind's `Context: 59%` display conflates all of these. The 19.4K is the cumulative serialized request across chained calls; the actual inference cost (after cache) is much lower; the "logical context" (what the agent knows) is a different number entirely.

### 5. OpenCode's documented anti-pattern: all MCP tools every call

OpenCode's V1 code exposes every connected MCP server's tools every call — the V2 docs flag this as a known limitation. LocalMind should NOT replicate this; the `describe_tool` pattern (ADR-40) is the right approach.

---

## PART 3 — DESIGN PRINCIPLES (derived from the patterns)

1. **Context is not synonymous with state.** The fact that LocalMind knows something does not mean Qwen needs to receive it. Every context source must justify its inclusion per-call.

2. **Minimum sufficient context, not minimum possible or maximum available.** The target is the minimum context required to perform the current operation correctly. Sometimes that's 15K tokens (complex research); sometimes it's 200 (a greeting).

3. **Byte-stable prefix is the highest-leverage invariant.** Cache hits are 90% off; cache misses are full price + 1.25× write premium. The prefix must be deterministic across calls within a session.

4. **Append-only mutation.** Never edit earlier messages. New context is appended at the tail. Changes to system/tools/instructions are explicit epoch-advance events, not silent re-renders.

5. **Durable history ≠ model context.** The full session history survives in storage (for the UI, for search, for replay). The model sees only `[checkpoint, ...recent_tail]`. Compaction changes the model-facing view, not the durable store.

6. **Tools are the context-management mechanism for files.** Don't pre-load file contents into the prompt; give the model tools to fetch what it needs (Codex's `apply_patch` pattern, Claude Code's glob/grep).

7. **Memory is structured records selected into the prompt, not raw transcript replay.** ChatGPT's `bio` tool writes structured facts to a database; the prompt injects selected facts with timestamps. Not "dump all memory every call."

8. **Internal agents get clean context.** Title/summary/compaction run with `tools: {}`, `system: []`, a cheap model, forked from the main loop.

9. **Context observability must distinguish cached vs fresh vs logical.** The user needs to see: logical context / serialized request / fresh input / cached input / equivalent inference work. A single "Context %" obscures the distinctions that matter for optimization.

10. **The harness, not the model, owns context.** "The assembled model context is treated as a dynamic request artifact rather than simply being equivalent to the application's entire state." (OpenCode's context hook principle.)

---

## PART 4 — LOCALMIND ARCHITECTURE (proposed)

### Current state (verified this session)

| Component | Status | Evidence |
|-----------|--------|----------|
| Prompt-cache markers | ✓ wired | `openai_compat.py:1424` sends `cache_control: {type: ephemeral}` |
| Cache-hit capture | ✓ wired | `openai_compat.py:718` normalizes `cached_tokens` across providers |
| Cache-hit logging | ✓ wired | `loop.py:3536` logs `iter=N cache: X/Y prompt tokens hit (Z%)` |
| Live cache through bankofai | ✓ working | Live test: 1024/1256 = 81.5% hit on call 2 |
| Byte-stable system prefix | partial | ADR-39 moved env block out; but intent-dependent persona/safety/skill sections still vary |
| Tool scoping (describe_tool) | ✓ wired | ADR-40 + S411: 11 core + 22 long-tail |
| Microcompaction | ✓ wired | S410: keep_last=1, stub=400 |
| Auto-compaction (LLM summarize) | partial | `maybe_compress_history` past 75%; no structured checkpoint, no rehydration |
| Durable history ≠ model context | ✗ missing | Compaction mutates the model-facing list; no separation |
| Context Budget Manager | ✗ missing | No per-call selection; everything available is sent |
| Context observability in UI | ✗ missing | Frontend uses `prompt_tokens_approx` (undiscounted estimate); cache data not surfaced |
| Internal agents (clean context) | partial | Title/classify use chat path (no tools) but carry full system prompt |

### Proposed architecture (6 components, in priority order)

#### Component 1: Context Budget Manager (the critique's #1 ask)

A first-class component that, before each model call, produces the **minimum sufficient model context** from available state.

```
Available State (memory, history, tools, workspace, task state)
       ↓
Context Budget Manager
       ├── Priority (what MUST be included)
       ├── Relevance (what's needed for THIS request)
       ├── Token budget (system reservation + output reservation + remainder)
       └── Selection (cut oldest history first, then stub, then summarize)
       ↓
Selected Context
       ↓
Prompt Assembly (byte-stable prefix + dynamic tail)
       ↓
Model
```

**Responsibility:** "Given current request + system state + conversation + memory + tools + workspace + agent state, produce minimum sufficient model context."

**This is the architectural change S410-S412 didn't make.** S410-S412 tuned parameters inside the existing dump; this component replaces the dump with selection.

#### Component 2: Instruction Epoch (OpenCode pattern)

Store instructions as durable deltas; render the baseline once per epoch; freeze update text as chronological System messages. Compaction advances the epoch (currently-admitted values become the new initial baseline).

**Why:** Today, every compaction invalidates the cache because the post-compaction prefix differs. The epoch pattern re-stabilizes the prefix after compaction, preserving cache hits across summarization boundaries.

#### Component 3: Checkpoint Compaction (Claude Code + OpenCode pattern)

Replace `maybe_compress_history`'s free-form summary with a structured checkpoint:
- **Template:** Objective / Important Details / Work State (Completed/Active/Blocked) / Next Move / Relevant Files
- **Recent tail:** preserve 2-15K tokens verbatim (configurable)
- **Rehydration:** after compaction, re-read ≤5 most-recently-modified files, restore todo list + plan state, inject continuation message
- **Durable history:** the full session survives in storage; only the model-facing view changes

#### Component 4: Context Observability UI (the critique's UI ask)

Replace the single `Context: 59%` with a breakdown:

```
Context Efficiency
─────────────────────
Available state:          48,200 tokens
Selected context:          6,240 tokens
Useful context:             4,910 tokens
Redundant context:          1,330 tokens

Context utilization:        78.7%
Context overhead:           21.3%

Per-call (last call):
  Fresh input:    1,156 tokens
  Cached input:   5,100 tokens (81.5% hit)
  Cache write:        0 tokens
  Output:           84 tokens
  Equivalent work: 2,266 tokens  (after cache discount)
```

Surface `cached_tokens` (already captured in backend) to the frontend. Show per-call + cumulative-across-N-calls.

#### Component 5: Memory Retrieval Gate (the critique's memory ask)

Replace "inject all memory_facts every call" with:
- **Memory Store** (already exists: sqlite-vec)
- **Candidate Retrieval** (per-request, top-K by relevance to the current user message)
- **Relevance filtering** (drop below threshold)
- **Token budget** (cap memory section to e.g. 500 tokens)
- **Selected memories** → prompt

This is the "memory as database, not giant prompt" pattern.

#### Component 6: Internal Agent Pattern (Claude Code + OpenCode pattern)

Title, summary, compaction, and classification run as internal agents with:
- `tools: {}` (zero tool schemas)
- `system: []` (only the agent's own prompt)
- A cheaper model (e.g., qwen3.8-flash for title, even if main agent uses a bigger model)
- Forked/async — don't block the main loop

**Why:** Today, title generation carries the ~500-token chat system prompt. Zero-system + zero-tools gives ~10× context savings on maintenance calls.

---

## PART 5 — IMPLEMENTATION PLAN (priority order, multi-session)

This is a plan, not a commitment. Each step is a separate session with live-verification on bankofai/qwen3.8-flash (weak model) per the ADR-40 guardrail.

### Step 1 (highest leverage, smallest blast radius): Surface cache data to the UI
- The backend already captures `cached_tokens` and logs the hit rate. The frontend just doesn't display it.
- Wire `cached_tokens` from `provider_usage` → SSE → frontend `PerformanceMetrics`.
- Show: per-call fresh/cached/write/output split; cumulative across N calls; equivalent inference work (after 90% cache discount).
- **Live-verify:** the user's "Context 59%" should drop to ~"Context 30% (81% cached)" after this change, with NO code change to the agent loop.
- **Estimated session count:** 1

### Step 2: Byte-stabilize the system prefix
- Audit `build_agent_system_prompt`: which sections vary by intent? (persona, safety, skill fragment all do.)
- Split into: durable baseline (byte-stable across all intents) + intent-specific tail (placed AFTER the cache breakpoint).
- The cache breakpoint goes at the end of the durable baseline, before the intent-specific + dynamic sections.
- **Live-verify:** run the audit harness before/after; cache hit rate should increase on intent-switching turns.
- **Estimated session count:** 1-2

### Step 3: Memory Retrieval Gate
- Replace "inject all memory_facts" with per-request top-K retrieval (sqlite-vec already exists).
- Cap memory section at 500 tokens; drop below relevance threshold.
- **Live-verify:** run a multi-turn conversation with memory; verify memory facts are still recalled (CAT3/CAT5 benchmark categories) but token count drops.
- **Estimated session count:** 1-2

### Step 4: Checkpoint Compaction
- Replace `maybe_compress_history`'s free-form summary with the structured template (Objective/Work State/Next Move/Relevant Files).
- Add rehydration: re-read ≤5 most-recently-modified files, restore todos + plan state.
- Separate durable history (DB) from model-facing view (compacted list).
- **Live-verify:** run a long conversation (>10 turns) that triggers compaction; verify the agent continues coherently post-compaction (CAT5 benchmark).
- **Estimated session count:** 2-3

### Step 5: Context Budget Manager
- The structural component. Before each call, SELECT what's relevant; don't dump.
- Composes: memory retrieval gate (step 3) + tool scoping (already done) + history selection (recent tail + checkpoint) + task state.
- Enforces a per-call token budget: system reservation + output reservation + remainder split across history/memory/tools.
- **Live-verify:** full benchmark suite (lm_benchmark.py) before/after; verify no behavioral regression + token reduction.
- **Estimated session count:** 2-3

### Step 6: Instruction Epoch
- Store instructions as durable deltas; render baseline once per epoch; freeze updates as System messages.
- Compaction advances the epoch.
- **Live-verify:** cache hit rate should survive compaction events (it doesn't today).
- **Estimated session count:** 2-3

### Step 7: Internal Agent Pattern
- Title/summary/compaction/classification run with `tools: {}`, `system: []`, cheap model.
- **Live-verify:** title generation latency + token cost should drop ~10×.
- **Estimated session count:** 1

### What S410-S412 were (in this plan)

S410 (compactor keep_last 4→1) = a parameter tune inside Step 4's microcompaction layer. Net-positive, compatible with the plan.
S411 (6 tools → long-tail) = extends ADR-40's tool scoping, which Step 5's Budget Manager orchestrates. Net-positive, compatible.
S412 (stale-ref fixes + dynamic tier list) = bug fixes. Necessary.

They're groundwork, not the architectural change. The architectural change starts at Step 1.

---

## PART 6 — VERIFICATION (what was live-verified this session)

- **bankofai/qwen3.8-flash cache passthrough:** ✓ live-verified. Call 1: 0 cached / 1256 prompt. Call 2: 1024 cached / 1256 prompt (81.5% hit). The cache IS working through bankofai to qwen; LocalMind's `cache_control` markers ARE reaching the upstream.
- **Backend cache-field capture:** ✓ code-verified. `openai_compat.py:718` normalizes `cached_tokens` across DeepSeek/OpenAI/Anthropic field names. `loop.py:3536` logs the hit rate per iteration.
- **Frontend display gap:** ✓ code-verified. `useLocalMind.ts:1293` uses `prompt_tokens_approx` (chars/4 estimate of FULL prompt) for the "Context %" display — NOT the provider-reported `cached_tokens`. The cache data exists in the backend but doesn't reach the UI.
- **Benchmark behavioral baseline (post-S410-S412):** ✓ live-verified. CAT1 (basic understanding) 6/6 PASS. CAT2 (clarify routing) 5/5 PASS. Cybercafe (duplicate-answer regression) PASS. No behavioral regression from S410-S412.

## PART 7 — GAPS / OPEN QUESTIONS

1. **bankofai key rotation stickiness:** The live test showed 81.5% cache hit on call 2 — but this was 2 calls in quick succession. If bankofai rotates upstream API keys per-request, longer sessions may see cache misses. Needs a longer session test (10+ calls) to confirm sticky routing.
2. **OpenCode V2 source code:** The V2 docs describe the instruction epoch in detail, but the V2 runner source wasn't findable on the dev branch. V1's transitional code is the verified implementation.
3. **ChatGPT's exact compaction algorithm:** Not publicly documented. Inferred from shared Responses API infrastructure.
4. **Whether LocalMind's OpenAI-compat path sends 1 or 2 system messages:** ADR-39 fixed `_chat_anthropic` to JOIN system messages, but the OpenAI-compat path may still send 2. Needs code verification before Step 2.
5. **OLLAMA_KEEP_ALIVE / num_ctx defaults in LocalMind's Ollama adapter:** Not verified this session. For local-model sessions, these affect KV cache reuse.

---

## DECISION REQUESTED

The critique said: "I would NOT let the coding agents implement anything yet. First produce the research. Then extract: COMMON PATTERNS → ANTI-PATTERNS → DESIGN PRINCIPLES → LOCALMIND ARCHITECTURE → IMPLEMENTATION PLAN. Only after that should we touch LocalMind code."

This report is that research. The Implementation Plan (Part 5) proposes 7 steps across ~10-14 sessions, starting with Step 1 (surface cache data to UI — 1 session, smallest blast radius, immediately actionable).

**Awaiting user direction on:**
1. Does this architecture match your intent, or should a component be reprioritized/removed?
2. Should Step 1 (UI cache display) start next session, or do you want to adjust the plan first?
3. Should S410-S412 be kept (they're compatible groundwork) or reverted (they're symptom-level optimizations)?

No code will be touched until you confirm.
