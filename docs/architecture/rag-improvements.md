# Architecture — RAG Improvements

> Phase 1 output. Reference doc for embedding and retrieval improvement directions.

---

## Purpose

LocalMind already has a working RAG pipeline — `nomic-embed-text` for embeddings, `sqlite-vec`
for storage, and `tools/file_reader.py` for document ingestion. This document captures four
concrete directions to make that pipeline faster, more accurate, and more accessible.

---

## Directions

---

### 1. Remote Embedding, Local Inference

**Idea:** Use a powerful remote model (e.g. Claude, OpenAI `text-embedding-3-large`) to embed
documents once during indexing. At query time, use the local `gemma3:1b` only for reasoning over
the retrieved chunks — not for understanding the full document.

**Why it helps:**
- Embedding quality directly affects retrieval accuracy
- Small local models produce weaker embeddings than large remote ones
- The expensive work (embedding) happens once and is stored — not repeated per query
- Local model only sees a small, pre-filtered context window → faster, cheaper inference

**Affected files:**
| File | Change |
|------|--------|
| `storage/vector.py` | Add support for externally-produced embedding vectors |
| `tools/file_reader.py` | Allow embedding provider to be swapped at ingestion time |
| `core/config.py` | Add `EMBED_PROVIDER` config key (`local` / `openai` / `anthropic`) |

**Trade-off:** Requires internet + API key at index time. Query time stays fully local.

---

### 2. Improved Chunk Quality in `file_reader.py`

**Idea:** Replace fixed-size token chunking with structure-aware chunking — split at paragraph,
section, or sentence boundaries instead of arbitrary token counts.

**Why it helps:**
- Current chunking can cut mid-sentence or mid-thought, degrading retrieval
- Semantic chunks retrieve as complete ideas — the LLM gets better context
- Overlap strategy can be tuned per document type (code vs prose vs tables)

**Affected files:**
| File | Change |
|------|--------|
| `tools/file_reader.py` | Replace fixed chunking with structure-aware splitter |
| `storage/vector.py` | Store chunk metadata (source section, page, type) alongside vectors |

**Suggested approach:**
- Prose: split at paragraph breaks, target 300–500 tokens per chunk
- Code: split at function/class boundaries
- Tables/CSV: one row-group per chunk with header repeated

**Trade-off:** More complex ingestion logic. Significant retrieval quality gain expected.

---

### 3. Dedicated Ingestion Endpoint

**Idea:** Expose a `POST /api/ingest` endpoint that accepts documents and indexes them into the
vector store directly — without going through chat.

**Why it helps:**
- Currently the only way to embed a document is to send it through a chat message
- A dedicated endpoint enables batch ingestion, scripted pipelines, and pre-loading
- Separates indexing from querying — cleaner architecture

**Affected files:**
| File | Change |
|------|--------|
| `api/routes/` | Add `ingest.py` — new route file |
| `api/app.py` | Register the new router |
| `storage/vector.py` | Expose a clean `ingest(chunks, metadata)` interface |
| `tools/file_reader.py` | Refactor to return chunks independently of the LLM call |

**Endpoint sketch:**
```
POST /api/ingest
Content-Type: multipart/form-data

file: <binary>
collection: "default"          # optional namespace
embed_provider: "local"        # optional override
```

**Trade-off:** Requires refactoring `file_reader.py` to decouple parsing from LLM dispatch.

---

### 4. RAG Benchmark

**Idea:** Measure whether RAG actually reduces context size and improves response latency on the
local setup — with real numbers.

**Why it matters:**
- Without measurement, improvements are guesses
- Benchmarks reveal whether `gemma3:1b` benefits meaningfully from retrieval or is bottlenecked elsewhere
- Establishes a baseline before making changes in directions 1–3

**What to measure:**

| Metric | Without RAG | With RAG |
|--------|-------------|----------|
| Tokens sent to model per query | Full document | Retrieved chunks only |
| Time to first token (ms) | — | — |
| Response quality (manual score 1–5) | — | — |
| Memory retrieval precision (top-3 hit rate) | — | — |

**Affected files:**
| File | Change |
|------|--------|
| `scripts/` | Add `benchmark_rag.py` |
| `core/metrics.py` | Expose token count and latency per request |

**Suggested test set:** 10 documents × 5 questions each. Compare answers with and without retrieval active.

---

## Recommended Order

| Priority | Direction | Effort | Impact |
|----------|-----------|--------|--------|
| 1 | Chunk quality (`file_reader.py`) | Medium | High |
| 2 | Ingestion endpoint | Medium | High |
| 3 | Benchmark | Low | Foundational |
| 4 | Remote embedding | Low–Medium | High (quality) |

Start with chunk quality — it improves everything downstream and requires no new infrastructure.

---

## Open Questions

- [ ] Is `nomic-embed-text` sufficient for the target document types, or is a remote model needed?
- [ ] Should the ingestion endpoint be authenticated (e.g. local API key)?
- [ ] What document types are most common in the target use case?
