# Review — Session 10 (Jabari) — cloud embed fallback when Ollama is unreachable

- **Date:** 2026-09-15
- **Agent:** Jabari (VS Code Copilot local) | **Model:** qwen3.8-flash | **Codename:** S010
- **Backlog item:** B-2026-08-20-12 (Low — capability, not stability)
- **Shipped:** `cb69c53b` fix(memory): bind a configured cloud embed backend when Ollama is unreachable (branch `collab/embed-fallback-20260915/jabari-vc-qwen3.8-flash-s010`, integrated to main via refspec)

## Problem

`VectorStore` embedded every fact through local Ollama only. With Ollama not
running, every store silently failed — the exact backlog symptom,
`[embed] Failed: All connection attempts failed` — and memory was dead for
the whole session with no recovery path. Reproduced live before fixing.

## Fix

A second embedding backend — any OpenAI-compatible `POST {base}/embeddings`
endpoint — configurable and bound **at store-init time** when Ollama is
unreachable:

- **Config** (`core/config.py`): `localmind_embed_adapter` (`""` | `"openai"`),
  `localmind_embed_base_url`, `localmind_embed_model`,
  `localmind_embed_key_provider` — settable via `settings.json`
  (`embed_adapter`, `embed_base_url`, `embed_cloud_model`,
  `embed_key_provider`) or `LOCALMIND_EMBED_*` env. Base URL defaults to the
  provider registry's entry when empty. API key reuses `get_api_key()`.
- **Bind-time selection** (`storage/vector.py`): at `_init_db`, if Ollama is
  unreachable and a cloud embedder is configured + reachable (10 s dim probe),
  bind it process-wide (`_USE_CLOUD`). One vec0 index = one embedding space —
  the backend is chosen once and never mixed per call, including for
  `tool_result_index`, which shares the module-level embed path.
- **Space guard:** the bound backend id (`mode|url|model`) persists in
  `vector_meta(embed_backend_id)`. A restart re-binds the same cloud backend
  (continuity); a *different* backend against a populated index **refuses**
  (facts survive, store goes offline with an explicit log) rather than mixing
  vector spaces; an empty index may re-key its dim. The legacy unrecorded
  case (any pre-change DB) keeps working under Ollama unchanged.
- **Cache namespacing:** both cache tiers (process LRU, persistent
  `embedding_cache` rows) key by backend identity, so a backend swap can never
  return a vector produced by the other space.
- **Write guard:** while `_dim_mismatch` is active, `_persist` refuses writes
  (previously a not-ready store could still reach `_set_dim` and silently
  overwrite the index dim).

Default (no cloud config): byte-identical behavior to before — Ollama-only,
graceful offline degradation.

## Verification

- **Unit:** 16 new tests (`tests/core/test_vector_embed_fallback.py`) over a
  fake-httpx harness: default-unchanged (Ollama up; Ollama down + no cloud),
  cloud failover (bind, store, recall, Bearer/model contract, no Ollama calls,
  mid-session Ollama recovery keeps the bound backend, tool-result index
  shares the bound backend), space guard (Ollama-era refuses cloud at same
  dim, cloud-era refuses Ollama, restart continuity, dim-mismatch), cache
  namespacing (LRU + persistent tiers), config parsing (settings.json keys,
  invalid adapter ignored, registry default).
- **Suites:** full `tests/core` + `tests/storage` green except 3 known
  pre-existing failures (cp1252 locale — documented in B-2026-09-15-19,
  clears under `PYTHONUTF8=1`; 2 loop-surface dedup failures owned by the
  vocab-sweep/loop work). None on this surface.
- **LIVE (isolated harness, Ollama genuinely down on this machine):**
  - BEFORE (no cloud config): `POST /api/memory` → **503**, log shows the
    exact backlog line `[embed] Failed: All connection attempts failed`.
  - AFTER (cloud configured vs a local OpenAI-compatible stub): bind warning
    at startup, `POST /api/memory` → **200** ×2, semantic search returns both
    facts with sane relevance; stub log proves every call hit
    `/v1/embeddings` with the configured model + Bearer header; DB records
    `embed_backend_id = cloud|http://127.0.0.1:8766/v1|stub-embed-1`.
  - Restart continuity: server restarted, `VectorStore ready — 2 facts
    stored`, recall works across restart.
- **Honest limits:** the cloud leg is verified against a **local stub**, not a
  real provider (no embedding keys exist on this machine) — real-provider
  behavior (e.g. OpenAI text-embedding-3-small) is contract-tested only.
  The z.ai embedding API mentioned in the backlog was not separately probed.

## Coordination

Collaboration office (Baraka S005 main tree, Tega S009, Imani S008 merged
earlier). Full override path: roster check-in `349317a6`, note + claim events
`ecf55bf2` (paths: vector.py, config.py, new test file — disjoint from peers),
isolated worktree `../LocalMind-s010` with venv junction, release event
`8563ff95`. No coordination branch needed; no collisions.

## Follow-ups worth noting (not filed — judgment calls)

- A real-provider smoke (one call to OpenAI/z.ai embeddings with a user key)
  would close the stub-vs-production contract gap; the backlog row's "z.ai's
  embedding API" alternative remains unprobed.
- The Settings modal could expose the new embed fields (config surface today
  is settings.json/env only).
- The two-tier persistent-cache key derivation (32-hex module tier vs 64-hex
  instance tier over the same table) predates this fix and is preserved
  deliberately — unifying it is a migration, not a drive-by.
