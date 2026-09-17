# Feature: memory-write-path — what may be remembered, under which identity, and with what proof

**Started:** 2026-09-17 · **Status:** ACTIVE (write path shipped and live-verified;
the boot-refresh consumer of the freshness tags is still parked) · **Sessions:** S014

## What this feature is

The memory store accepted every statement as equally durable and gave every
write a fresh identity. Three failures came from that one root, all observed
live in the owner's own transcript: the machine's public IP and its ISP were
stored as durable defaults; the same fact accumulated near-copies (worst on the
plain-text path, which cannot embed and appended a row per statement); and a
cleanup reported success while the row it named was still there.

This feature makes the write path decide three things in code rather than in
prompt prose:

- **Durability** — `PREFERENCE` and `STABLE_FACT` are stored; `VOLATILE` (IP /
  MAC literals, ISP/carrier, live machine readings, "right now" framings) is
  refused with the reason said in plain words. Stable facts carry
  `memory_freshness` (`static` / `boot`) and `memory_confidence` so a later boot
  can refresh them instead of trusting a cached claim.
- **Identity** — `canonical_key()` gives a fact one key (a named subject such as
  `subject:location`, or its leading content words) which is hashed into the row
  id: re-stating the same fact replaces that row. A keyed write supersedes a
  near-identical unkeyed row rather than sitting beside it, and the degraded
  plain-text path now writes the same keyed id instead of a fresh uuid, which is
  where the duplicates came from.
- **Proof** — every mutation confirmation is built from a read-back of the state
  it left. A write that cannot be read back says so; a removal that did not take
  says so. Deletion resolves an id, an id prefix, re-worded content, or a key,
  and the list prints the short id each fact can be acted on.

## Scope + invariants

- No prompt-copy policies: the rules hold regardless of what the prompt says or
  which model runs. The autonomous (non-user-initiated) write paths run through
  the same durability gate, or a live value just arrives by another door.
- Reads and deletes are NOT on the deterministic path writes are — the model
  still decides whether to call the tool for those. Filed as a finding, not fixed
  here.
- Existing behavior preserved: the confirmed-store message is unchanged
  (`Remembered: *…*`), the four-factor retrieval scoring and level filters are
  untouched, and a fact written before this feature keeps working (no key, no
  kind → treated as a durable fact; content-hash ids still delete).

## Files touched

- `backend/src/core/memory_intent.py` — durability verdicts, keys, the volatile
  rule set (next to the existing memory-type classifier).
- `backend/src/tools/memory_tool.py` — the gate, keyed writes, read-back
  confirmations, id-bearing list, forget by id/content with a read-back,
  bare-operation dispatch.
- `backend/src/storage/vector.py` — keyed row identity, supersede-on-first-key,
  robust delete (id / prefix / content / key), read-back helpers, deletes that
  survive a store with no vector table.
- `backend/src/core/memory.py` — key + durability-metadata pass-through.
- `backend/src/core/engine/_memory_mixin.py` — the same durability gate on the
  autonomous extraction paths.
- `scripts/live_test_memory_write_path.py` — the before/after trace harness.
- Tests: `tests/tools/test_memory_write_path.py`,
  `tests/core/test_vector_keyed_upsert.py`, plus the store doubles in
  `tests/core/test_memory_e2e.py` taught the new read-back.

## Evidence

Live, isolated server on 8766 with a scratch home, provider zai/glm-4.5-flash,
same four turns before (previous revision) and after:

| check | before | after |
|---|---|---|
| live value (public IP + ISP) | stored | refused, 0 such rows |
| same preference stated twice | 2 rows | 1 row (keyed) |
| durability tags on stored rows | none | `memory_key`, `memory_kind`, `memory_freshness` |
| delete by the short id the screen shows | 404, the row stayed | deleted, list empty |

The model's listing call was traced live too: it sent the operation word alone
and the tool returned `**Stored memory (1 facts):** - #98802f19 …`, so the
listing names the id that then deleted cleanly. (On the previous revision that
same call persisted the word "list" as a fact — that comparison is pinned
deterministically in `scratch/s014/bare-list-before-after.txt`, since the live
before-pass for that turn was blocked by provider rate limits.)

Artifacts: `scratch/live-memory-write-path/` (SSE per turn, results JSON, server
logs; the before side under `before/`), `scratch/s014/`.

Two live-discovered bugs are part of this feature's own surface: the model's
`operation=list` call used to fall through to the store path and persist the
word "list" as a fact, and every delete failed on a store built by the
plain-text fallback because that store has no vector table.
