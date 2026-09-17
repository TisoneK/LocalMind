# The memory write path now decides what it keeps, keeps one copy, and proves it

**Session 14 — Buffy (S014) · 2026-09-17 · Windows 11 (Lameck checkout) · core 1.2.0**

## What happened

I picked up the top of the backlog queue — `B-2026-09-15-3` (the typed memory
schema in the write path) together with the `-4` reliability mechanics it gated,
because they are one surface: what a write accepts, what identity it gets, and
what the app is allowed to say about it afterwards.

All three failures in the owner's transcript trace to one root. The store treated
every statement as equally durable, so a live value (the machine's public IP and
its ISP) was stored as a durable default. It gave every write a fresh identity,
so the same fact accumulated near-copies — worst on the plain-text path, which
cannot embed and appended a row per statement. And nothing checked the store
after a mutation, so "Done — I've cleaned up your memory entry" was reported
while the row was still there (and, as this session's live run found, while
deletion was silently failing altogether).

Shipped and live-verified against the previous revision on the same four turns.

## What changed

- **Durability is policy in code, not prompt prose.** `PREFERENCE` and
  `STABLE_FACT` are stored; `VOLATILE` — IP/MAC/IPv6 literals, ISP/carrier,
  live machine readings, explicit "right now" framing — is refused with the
  reason said in plain words. The rule runs in the tool *and* in the autonomous
  extraction paths, or a live value simply arrives by another door (that is
  where the IP came from). Stable facts carry `memory_freshness`
  (`static`/`boot`) and `memory_confidence` so a later boot can refresh them
  instead of trusting a cached claim.
- **One row per fact.** `canonical_key()` names a fact (a single-valued subject
  like `subject:location`, else its leading content words) and that key is
  hashed into the row id. Re-stating a fact replaces its row; a keyed write
  supersedes a near-identical unkeyed row instead of sitting beside it; and the
  degraded plain-text path writes the same keyed id instead of a fresh uuid —
  which is exactly where the duplicates came from.
- **Every mutation is confirmed from a read-back.** A write that cannot be read
  back says so; a removal that did not take says so; a refused write no longer
  answers "Got it — I'll remember that."
- **Deletion finds the fact.** Resolution order is id, id prefix, re-worded
  content, key — a content hash only ever matched the exact wording that stored
  the fact. `forget_by_id` now accepts the short id the list prints, so an id a
  user can read is an id a user can act on.
- **The list names each fact by that short id**, and a bare operation word
  ("list", the shape the tool's own schema invites) dispatches to that operation
  instead of being stored as a fact.

## Two bugs found live, inside this surface

1. **The model's listing call was stored as a memory.** Live, the model called
   `memory_op` with `operation=list`; the dispatcher handed the tool the word
   "list", it missed the listing pattern, fell through to the store path, and
   persisted "list" as a fact — a junk memory and a garbled listing from one
   call. That is the concrete root of the "list garbled" symptom in the
   transcript. Pinned deterministically before/after
   (`scratch/s014/bare-list-before-after.txt`): before wrote `['list']` and
   answered `Remembered: *list*`; after writes nothing and returns the listing.
2. **Deleting never worked on a store without a vector table.** A fact stored
   while the embedder is unavailable has no vector row, and on that store the
   vector table may not exist at all — the delete touched it unconditionally, so
   every delete failed and callers reported "couldn't find that fact" while the
   fact sat right there. Reproduced live through the app's own memory surface
   (DELETE of the listed short id → 404, row still present) and fixed at the
   source: removing the vector row is best-effort, the fact row is what goes.

## Evidence (live, isolated 8766 + scratch home, zai/glm-4.5-flash)

Same four turns, previous revision vs this one:

| check | before | after |
|---|---|---|
| "remember my public IP … and my ISP …" | stored | refused in plain words, 0 such rows |
| the same preference stated twice | 2 rows | 1 row |
| durability tags on the stored row | none | `memory_key`, `memory_kind=preference`, `memory_freshness=static` |
| delete by the short id the screen shows | 404, row stayed | deleted, list empty |
| the model's listing call | persisted the word "list" | `**Stored memory (1 facts):** - #98802f19 …` |

**Live-verified:** the durability refusal end-to-end through the classifier path;
one-row-after-restatement; the model calling `memory_op operation=list` and the
tool returning the id-bearing listing; delete-by-short-id through `/api/memory`;
the before/after table above. **Unit-tested (55 new/updated cases):** the policy
verdicts and keys, the read-back gates (unverified write, refused write, failed
removal), prefix and content deletion, delete without a vector table, the
bare-operation dispatch. **Assumed / not proven:** that the key heuristic
collapses paraphrases *in general* — it collapses re-statements that share a
named subject or leading words; with the embedder down (no semantic dedup) a
genuinely re-worded restatement still creates a second row.

## What is still open

- **Reads and deletes are not on the deterministic path writes are.** The
  runtime routes `is_write` intents straight to the tool; a read or delete
  intent relies on the *model* choosing to call it — which is why a live
  "what do you know about me?" was answered from conversation context
  (naming the IP and ISP the write path had just refused to store) instead of
  from the store. Filed as a finding with the evidence; not fixed here.
- **The freshness tags have no consumer yet.** Tagging a fact `boot` is only
  useful once something re-derives it at startup; that belongs with the parked
  geolocation/context bootstrap row, whose gate this session clears.
- **Stores may hold junk rows** (the word "list" and friends) written by the
  bare-operation bug before today. No cleanup shipped; noted as a promotable row.
- **The edit path (`PATCH /api/memory/{id}`) still needs the vector table** for
  its re-embed insert, so editing on a table-less store fails. The delete half is
  fixed; the edit half is not.

## Recommendation

Next session should wire read/delete intents through the same deterministic route
as writes (small, high value: it is what makes the new list/forget behavior
reachable without depending on the model's tool choice), then hand the freshness
tags to the geolocation bootstrap that is already designed and parked.

## Appendix — session bookkeeping

- Product commits: `9ba42626` (typed/keyed/verified write path), `b1a8aa96`
  (delete without a vector index), `5ed4a22a` (live-trace harness). CHANGELOG
  updated under `[Unreleased]`.
- Artifacts: `scratch/live-memory-write-path/` (per-turn SSE, results JSON,
  server logs; before-side under `before/`), `scratch/s014/`.
- Verification limits stated honestly: zai is a free tier and 429'd repeatedly
  mid-session; one live turn (the tool-side forget) was not captured because of
  it, and the before-pass covered turns 1–3 rather than 1–4. The tool's own
  behavior is covered by unit tests and by the traced list/delete turns.
