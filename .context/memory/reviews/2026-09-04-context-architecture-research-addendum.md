# LocalMind Context Architecture Research — Addendum: Claude Context Engine + Context Mode MCP

**Date:** 2026-09-04
**Trigger:** User follow-up — "Do more research on Claude Context Engine and this Context Mode" (after the Better Stack video on Context Mode MCP)
**Status:** Research only. NO code changes. This is an addendum to `2026-09-04-context-architecture-research.md`.
**Method:** 2 parallel research subagents (R-F Claude Context Engine, R-G Context Mode MCP) + source verification.

---

## FINDING 1: "Claude Context Engine" is not an official Anthropic product

**DOCUMENTED:** Searching Anthropic's docs (platform.claude.com, docs.anthropic.com, anthropic.com/engineering, claude.com/blog) for the exact phrase "Context Engine" returns **zero official hits**. The phrase appears only in:
- Third-party blog headlines that conflate it with the 1M-token-window GA news (onai2.com — a community mislabel; Anthropic's actual figure is 1M, not 10M)
- Informal usage like "Claude's context engine automatically unloads idle skills" (descriptive, not a product)
- A community MCP server named "Context Mode" (unrelated to an Anthropic product)

**The real Anthropic taxonomy:**
- **"Context engineering"** — the *discipline* (introduced in the *Effective context engineering for AI agents* blog, Sep 29 2025). Defined as "the set of strategies for curating and maintaining the optimal set of tokens during LLM inference."
- **"Context management"** — the *API feature family* (`context_management.edits[]` field, launched Sep 29 2025). The product blog is titled *Managing context on the Claude Developer Platform*.

**Recommendation for LocalMind docs:** Drop the term "Claude Context Engine" — it's a misnomer. Use Anthropic's own taxonomy: *context engineering* (discipline) and *context management* (the `context_management.edits[]` API family).

---

## FINDING 2: The real "system" is one API field with three composable strategies

**DOCUMENTED:** Anthropic's `context_management.edits[]` API field accepts three strategies, all behind beta headers:

| Strategy | Beta header | What it does | Trigger |
|----------|-------------|--------------|---------|
| `compact_20260112` | `compact-2026-01-12` | LLM-summarizes conversation into a structured checkpoint; drops all content before the compaction block | `input_tokens` threshold (min 50K, default 150K) |
| `clear_tool_uses_20250919` | `context-management-2025-06-27` | Auto-clears oldest tool results (chronological, not semantic); replaces with placeholder text | `trigger` (default 100K input tokens or `tool_uses` count); `keep` (default 3 recent pairs); `clear_at_least` (min tokens to clear — guards against cache-thrash); `exclude_tools` (never-clear list) |
| `clear_thinking_20251015` | `context-management-2025-06-27` | Clears/manages extended-thinking blocks | Model-class-dependent defaults |

**Anthropic's own recommendation (DOCUMENTED, important update):** *"For most use cases, server-side compaction is the primary strategy for managing context in long-running conversations. The strategies on this page [context editing] are useful for specific scenarios where you need more fine-grained control."* So: compaction is the default; context editing is the scalpel.

**The four-approach composition table (DOCUMENTED):** Anthropic explicitly says these compose:

| Approach | Reduces | When |
|----------|---------|------|
| Tool search | tool definitions loaded upfront | 20+ tools, most unused per turn |
| Programmatic tool calling | tool_result roundtrips | chains that run as one script |
| Prompt caching | cost of repeated tool definitions | stable toolset, many requests |
| Context editing | old tool_result blocks in history | long convos, stale results |

*"These approaches compose. A long-running agent might use tool search to keep the toolset lean, prompt caching to amortize the cost of the remaining definitions, and context editing to trim stale results as the conversation grows."* Recommended starting order: caching day 1 → tool search past ~20 tools → context editing once conversations run long → programmatic tool calling for repetitive chains.

**Key takeaways for LocalMind:**
- LocalMind doesn't need to invent a "Context Engine" — the pattern is: compaction (primary) + context editing (fine-grained) + memory tool (persistence) + tool search/scoping (hygiene) + prompt caching (cost). All composable.
- LocalMind already has: prompt caching (ADR-39, verified working), tool scoping (ADR-40 + S411). Missing: compaction (has a weak version), context editing (none), memory tool (has memory_op but not the file-based pattern).

---

## FINDING 3: Context editing is server-side, deterministic, and cache-aware

**DOCUMENTED:**
- **Server-side:** *"Context editing is applied server-side before the prompt reaches Claude. Your client application maintains the full, unmodified conversation history. You do not need to sync your client state with the edited version."*
- **Deterministic (not semantic):** *"When activated, the API automatically clears the oldest tool results in chronological order. The API replaces each cleared result with placeholder text indicating to Claude that it was removed."* — "stale" = oldest past the threshold, not semantically irrelevant.
- **Cache-aware:** *"Tool result clearing: Invalidates cached prompt prefixes when content is cleared. To account for this, clear enough tokens to make the cache invalidation worthwhile. Use the `clear_at_least` parameter… You'll incur cache write costs each time content is cleared, but subsequent requests can reuse the newly cached prefix."*

**Eval numbers (DOCUMENTED, not replicable):** *"On an internal evaluation set for agentic search… combining the memory tool with context editing improved performance by 39% over baseline. Context editing alone delivered a 29% improvement. In a 100-turn web search evaluation, context editing enabled agents to complete workflows that would otherwise fail… while reducing token consumption by 84%."* No public dataset/methodology — treat as directional, not a benchmark.

**Key takeaways for LocalMind:**
- Context editing is essentially what LocalMind's `context_compactor.py` does (S410: keep_last=1, stub=400) — but LocalMind's version is client-side and lossy (stubs to head+tail). Anthropic's version is server-side and replaces with a placeholder. The LocalMind version is actually MORE information-preserving (head+tail) than Anthropic's placeholder, but it's client-side so it doesn't benefit from the provider's cache-awareness.
- The `clear_at_least` parameter is a clever cache-economic lever — clear enough to make the cache break worthwhile. LocalMind's compactor doesn't have this concept; it stubs unconditionally.

---

## FINDING 4: The memory tool is file-based, client-side, and the model self-invokes it

**DOCUMENTED:**
- API: `{"type": "memory_20250818", "name": "memory"}` — the name MUST be `memory`; no input schema (the tool description is baked in). No beta header. Available on all Claude 4+ models.
- **Client-side:** Claude emits `tool_use` requests (view/create/str_replace/insert/delete/rename); your app executes them against a `/memories` path you map to real storage. Claude never sees the raw filesystem.
- **Auto-check:** *"When the memory tool is enabled, Claude automatically checks its memory directory before starting a task."* — the model self-invokes `view /memories` at task start.
- Differs from ChatGPT's memory (hosted key-value) and Claude app's Memory (hosted preference store). The API tool is "the model writes its own NOTES.md" — Anthropic explicitly cites this as the manual equivalent.

**Claude Code does NOT use the API memory tool** — it uses its own CLAUDE.md (user-written) + auto-memory (Claude-written Markdown in `.claude/`). This is a strong signal: the file-based pattern is more portable (works on Bedrock/Vertex/Foundry, not just the Claude API) and more auditable (Markdown files are human-readable).

**Key takeaways for LocalMind:**
- LocalMind's `memory_op` tool is closer to ChatGPT's hosted key-value than to Anthropic's file-based memory. The file-based pattern (model writes/reads structured files in a memory directory) is more aligned with the mature-harness approach.
- The "model auto-checks memory at task start" behavior is interesting — it's a trained behavior, not a prompt instruction. LocalMind can't replicate this on non-Claude models, but it CAN inject a memory-read at task start in the agent loop.

---

## FINDING 5: Context awareness is a model behavior, not an API toggle

**DOCUMENTED (partially):** *"Claude Sonnet 4.5 enhances both capabilities with built-in context awareness—tracking available tokens throughout conversations to manage context more effectively."* There is no API parameter to enable/disable it. It's a trained model capability.

**REASONABLE INFERENCE:** "Context awareness" = the model receives accurate post-tool-call token-usage signals and is trained to reason about remaining headroom. It does NOT autonomously trigger API-level server-side compaction (that's gated by your `context_management.edits` config). What it CAN do: proactively write to the memory tool, summarize, or wind down a task gracefully. The boundary between "model decides" and "API enforces" is real: awareness is advisory, compaction/editing are enforced server-side.

**Key takeaways for LocalMind:**
- LocalMind can't rely on "context awareness" because it runs on qwen3.8-flash (not Sonnet 4.5+). The agent loop must enforce context limits itself.
- But LocalMind CAN give the model accurate token-usage signals (it already captures `cached_tokens` + `prompt_tokens` per call). The model could be coached to self-manage if it knows the context budget.

---

## FINDING 6: Context Mode MCP is real, verified, and the claims are (mostly) accurate

**Repo:** github.com/mksglu/context-mode (20,342 stars, ELv2 license — NOT MIT; forbids hosted/managed-service use. Actively maintained, commits daily through Sep 2026.)

**Claims verified against source:**

| Video claim | Source evidence | Verdict |
|-------------|-----------------|---------|
| 56 KB → 299 bytes (99%) | `BENCHMARK.md:39`, fixture in `tests/fixtures/playwright-snapshot.txt` (57,521 bytes) | ✅ Exact match. BUT: the 299 B is the **model's own code's `console.log()`** (the model writes JS that processes the 56 KB snapshot in a sandbox and prints a summary). Context Mode only generates its own ~150 B pointer when output >100 KB. The headline 99% requires the model to write good summarizing code. |
| ~99% reduction generally | `BENCHMARK.md:39,47,48` (99%, 100%, 99%) | ✅ Verified |
| 30 min → 3 hr session | `README.md:1472`, blog (anecdotal) | ⚠️ **Derived, not measured.** If context fills 6× slower (98% reduction), session lasts 6× longer. No controlled benchmark. Author's blog: "I noticed I could work 6x longer" — anecdotal. |
| 5,000-line access.log | Better Stack article (synthetic 5,000-line demo) | ✅ In article. Repo fixture is 500 lines/45.1 KB. The article's "5,000 lines → 20.1 KB" math is inconsistent (5K lines should be ~400 KB). |
| 1,200+ tokens saved | Article: "4.9 KB kept in sandbox" ÷ 4 ≈ 1,225 tokens | ✅ Math checks out (derived, not stated) |
| SQLite FTS5 indexing | `src/store.ts:475` `USING fts5(...)` | ✅ Verified |
| Custom hooks (PreCompact etc.) | `hooks/precompact.mjs`, `README.md:86` | ✅ All 6 hooks registered (PreToolUse, PostToolUse, UserPromptSubmit, PreCompact, SessionStart, Stop) |
| ~2KB priority-tiered snapshot | `hooks/auto-injection.mjs` (500 tokens ≈ 2 KB, P1–P4) | ✅ Exact match |
| "Virtualization/sandbox layer" | PreToolUse hook + `routePreToolUse()` redirect | ✅ It's a hook, not a true VM |

---

## FINDING 7: Context Mode's architecture — the dual-FTS5 + PreToolUse hook pattern

**The SQLite FTS5 schema (verified from `src/store.ts:464-504`):**
- `sources` table — metadata (label, chunk_count, indexed_at, file_path, content_hash)
- `chunks` virtual table — FTS5 with `porter unicode61` tokenizer (Porter stemming + Unicode-aware word tokenization → BM25-ranked word search)
- `chunks_trigram` virtual table — FTS5 with `trigram` tokenizer (3-char sliding window → substring/fuzzy matching)
- `vocabulary` table — word index
- **No vector store / no embeddings / no semantic similarity.** Confirmed by the author on HN: *"No LLM calls, purely algorithmic: SQLite FTS5 with BM25 ranking and Porter stemming."*

**The interception mechanism:** A **PreToolUse Claude Code hook** (`hooks/pretooluse.mjs`), not a proxy or wrapper. The hook calls `routePreToolUse()` which returns one of: `allow` / `deny` / `modify` / `redirect`. The redirect decision tells Claude Code to call a Context Mode sandbox MCP tool (`ctx_execute`, `ctx_execute_file`, `ctx_batch_execute`, `ctx_index`, `ctx_fetch_and_index`) instead of the original tool. The raw output never enters context; only a pointer + the model's own summarizing code's output enters.

**The minimal confirmation returned to the LLM (verified from `src/server.ts:1967-1970`):**
```
Indexed {totalChunks} sections ({codeChunks} with code) from: {label}
Use ctx_search(queries: ["..."]) to query this content.
Use source: "{label}" to scope results.
```
The `ctx_search(queries: [...])` call is **embedded in the pointer** — the model doesn't have to guess how to retrieve; the pointer hands it the exact query.

**The checkpoint pattern (verified from `hooks/precompact.mjs` + `hooks/auto-injection.mjs`):**
- **PreCompact hook** fires before compaction → builds a full XML "table of contents" (uncapped, stored for `--resume`) via `buildResumeSnapshot()`. Each section ends with a runnable `ctx_search()` call.
- **SessionStart hook** with `source: "compact"` fires after compaction → injects a ~2 KB priority-tiered block via `buildAutoInjection()`. Priority: P1 role (behavioral_directive) → P2 decisions (rules) → P3 skills (active_skills) → P4 intent (session_mode). Hard cap: 500 tokens (~2000 chars).
- **No LLM call in either snapshot builder.** Both are deterministic structured extraction from the SQLite SessionDB. Fast (sub-20 ms) and free.

**Key takeaways for LocalMind:**
- **Dual FTS5 indexes (porter + trigram) is a clever pattern** — porter for BM25 word search, trigram for substring/fuzzy. LocalMind's sqlite-vec store handles semantic but is weak on exact-string recall; adding a parallel FTS5 table would close that gap.
- **The sandbox layer is just a pre-tool-call interceptor + a redirect decision.** No proxy, no monkey-patching. LocalMind could implement the same with a pre-tool-call interceptor in `backend/src/core/agent/tool_dispatch.py`.
- **The embedded `ctx_search(...)` call in every pointer is the key UX trick.** The model doesn't have to invent queries — the pointer hands it the exact query. LocalMind should do the same.
- **The two-tier snapshot (full TOC for resume + small injection for compact) is the right pattern.** LocalMind's `maybe_compress_history` currently does LLM summarization — expensive and lossy. A deterministic TOC would be cheaper and more predictable.

---

## FINDING 8: Context Mode is the most AGGRESSIVE variant of the JIT pattern — LocalMind should NOT go this far

**The JIT (just-in-time) context loading pattern is universal across mature harnesses, but they differ in how aggressive the "on-demand" side is:**

| Tool | What's kept inline | What happens to old content | Retrieval |
|------|-------------------|----------------------------|-----------|
| **Context Mode** | ZERO (just pointer) | Indexed to FTS5 (lossless) | Explicit `ctx_search()` tool call |
| **Claude Code microcompaction** | Hot tail (recent N messages) | LLM-summarized (lossy) | None — once summarized, raw is gone |
| **Anthropic context editing** | Recent tool results (keep=3) | Dropped (placeholder) | None |
| **Zed progressive disclosure** | Skill catalog (name+desc, ≤50 KB) | Body fetched on-demand | Explicit `skill(name)` tool call |
| **LocalMind (S410)** | Newest 1 result verbatim | Stubbed to 400 chars (head+tail) | None |

**Context Mode is unique in keeping ZERO inline and requiring explicit search.** Every other tool keeps some hot tail. Context Mode's bet: the model will know to search, and the search will be relevant enough that not having the full output inline doesn't hurt.

**The tradeoffs (verified):**
- **Latency:** each `ctx_search` is a tool-call round-trip (~16 ms SQLite query + ~200-500 tokens overhead + API latency). For a 5-iteration research turn with 2 searches/iter = 10 extra round-trips = ~20s added latency.
- **Recall risk:** if the model doesn't search, it forgets the output entirely — worse than stubbing (which leaves a head/tail hint). Context Mode mitigates by embedding `ctx_search()` calls in every pointer + the TOC snapshot, but it's imperfect.
- **FTS5 weakness on semantic queries:** "error" matches "errors" (Porter stemming) but NOT "exception" or "failure." LocalMind's research agents ask semantic questions that FTS5 can't answer.
- **Prompt-cache impact:** redirecting tools mid-session changes the tool list, which can invalidate the cached prefix. Context Mode doesn't document cache-hit-rate impact.

**Key takeaways for LocalMind:**
- **Do NOT go full Context Mode (zero inline).** The recall risk is too high for an agent that does multi-step research. A hybrid is better: keep the 400-char stub (S410's pattern) AND add a pointer + search tool for large results. The stub tells the model the result exists; the search lets it retrieve details.
- **LocalMind's hybrid advantage:** it already has sqlite-vec for semantic search. A hybrid FTS5 (keyword) + vec0 (semantic) would handle both exact-match and semantic queries — strictly better than Context Mode's FTS5-only approach.
- **Gate the index-and-pointer path on output size.** Context Mode uses 5 KB (`INTENT_SEARCH_THRESHOLD`) for intent-search and 100 KB (`LARGE_OUTPUT_THRESHOLD`) for auto-pointer. Below 5 KB, the indexing overhead exceeds the savings. LocalMind should do the same.

---

## UPDATED ARCHITECTURE RECOMMENDATION

Based on this addendum, the proposed architecture from the prior report (`2026-09-04-context-architecture-research.md`) is **confirmed and refined**. The Context Budget Manager (Component 1) should incorporate:

### New Component: Tool-Result Index + Search (the Context Mode pattern, adapted)

**What it is:** A hybrid FTS5 + vec0 index of tool results, with a pointer+search-tool pattern for large outputs.

**How it works:**
1. After each tool call, if `tool_result.content` > 5 KB:
   - Chunk it (markdown headings if applicable, else fixed 4 KB chunks)
   - Insert into `tool_result_chunks` FTS5 table (porter + trigram tokenizers) + `tool_result_embeddings` vec0 table (using LocalMind's existing Ollama embeddings)
   - Replace the in-context tool result with: `[stub: head 200 chars]…\n[Indexed N chunks. Search with search_tool_results(query="...") for full content.]`
2. Add a `search_tool_results` tool: `{ queries: [...], tool_name?: str, session_id?: str, limit?: int }` → hybrid FTS5 (BM25) + vec0 (cosine) search → merge results → return matching chunks.
3. The pointer embeds a pre-built query (like Context Mode) so the model doesn't have to invent one.

**Why hybrid (not FTS5-only like Context Mode):**
- FTS5 (porter + trigram): fast, exact, deterministic. Handles "find the error with 'ConnectionError'" (exact keyword).
- vec0 (sqlite-vec): semantic. Handles "what did I learn about network failures?" (paraphrase).
- LocalMind already has the vec0 half. Adding FTS5 is one migration.

**Why keep the stub (not zero-inline like Context Mode):**
- The 400-char stub (S410's pattern) is a recall hint. Without it, the model doesn't know what to search for.
- Context Mode's zero-inline works for Claude Code (strong model, coached by the tool description) but is risky for LocalMind (qwen3.8-flash, weaker model).

**Estimated impact:** ~80% reduction in tool-result context for research-heavy turns (the 91→4228-token growth becomes 91→~500 with pointers). Plus: old results become fully retrievable (FTS5+vec0) instead of lossy-stubbed.

**Estimated effort:** ~300 lines of Python (FTS5 schema migration + indexer + search tool + hybrid merge). 2-3 sessions.

### Refined Implementation Plan (priority order)

This refines the 7-step plan from the prior report. The new Tool-Result Index + Search component slots in as Step 4 (after the UI cache display, byte-stable prefix, and memory retrieval gate; before the Context Budget Manager).

1. **Step 1:** Surface cache data to the UI (1 session) — unchanged
2. **Step 2:** Byte-stabilize the system prefix (1-2 sessions) — unchanged
3. **Step 3:** Memory Retrieval Gate (1-2 sessions) — unchanged
4. **Step 4 (NEW):** Tool-Result Index + Search — the Context Mode pattern adapted for LocalMind (2-3 sessions)
5. **Step 5:** Checkpoint Compaction (2-3 sessions) — refined: use the deterministic TOC pattern (Context Mode's `buildResumeSnapshot` + `buildAutoInjection`) instead of LLM summarization
6. **Step 6:** Context Budget Manager (2-3 sessions) — unchanged
7. **Step 7:** Instruction Epoch (2-3 sessions) — unchanged
8. **Step 8:** Internal Agent Pattern (1 session) — unchanged

**Total:** ~12-18 sessions, refined from the prior ~10-14.

---

## DECISION REQUESTED (updated)

The prior report asked 3 questions. This addendum adds context:

1. **Does the proposed architecture match your intent?** — The Context Mode research confirms the JIT pattern is the right direction, but argues for a HYBRID (stub + pointer + FTS5+vec0 search) rather than Context Mode's zero-inline approach. Does the hybrid sound right?

2. **Should Step 1 (surface cache data to UI) start next session?** — Still the highest-leverage, smallest-blast-radius step. Unchanged.

3. **Should S410-S412 be kept or reverted?** — The Context Mode research VALIDATES S410's stub pattern (keep a hint inline, don't go zero-inline). S410 should be kept. S411 (tool scoping) is also validated (Context Mode's PreToolUse redirect is a more aggressive form of the same pattern). S412 (stale-ref fixes) is necessary. All three are compatible groundwork.

**New question from this addendum:**
4. **Should LocalMind adopt the deterministic-TOC compaction pattern (Context Mode's `buildResumeSnapshot` + `buildAutoInjection`) instead of LLM summarization?** — This is cheaper (no LLM call), faster (sub-20 ms), and more predictable. But it's less flexible (the model can't rewrite the summary). The hybrid: deterministic TOC as the base + optional LLM refinement for complex sessions.

No code will be touched until you confirm. The full research record (R-A through R-G) is in `.context/memory/reviews/` + the worklog.
