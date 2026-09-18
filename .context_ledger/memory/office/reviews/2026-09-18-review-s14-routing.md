# Review — Session 14 (extended): deterministic memory read/delete routing

**Agent:** Buffy (S014, Freebuff desktop) · **Date:** 2026-09-18 · **Core:** 1.2.0
**Task:** backlog head `B-2026-09-17-1` — route memory READS and DELETES through
the deterministic path like writes, then live-verify the answer comes from the
store. Follow-up to the typed write path shipped the previous day
(`9ba42626`/`b1a8aa96`).

## What shipped

`58ffec18` (8 files, +812/−111), `75638e75` (live harness), `aff07f49` (CHANGELOG).

- **Runtime routing** (`backend/src/core/agent_runtime.py`): `is_read` and
  `is_delete` turns dispatch straight to `memory_op` — the model never sees the
  turn. Reads answer with the store's own id-bearing listing (or an honest
  "nothing stored yet"); deletes apply and confirm from a read-back; a failed
  store replies "nothing was changed/removed" instead of raising the turn. Both
  paths leave the full trail through a shared `_finish_memory_turn` epilog:
  user row persisted before the reply (existing seam), assistant row, runtime-done,
  turn-complete, observation — so history, exports, and the anomaly checks stay
  truthful for turns that made no provider call.
- **Classifier gates** (`backend/src/core/memory_intent.py`): a read cue means
  "the stored facts about me" — a lookahead rejects an "about <anything but
  me/my>" tail, so "What do you know about Python?" reaches the model. A delete
  cue must name a removable fact: bare "delete that"/"remove this" is ordinary
  file-and-code language, and a punctuation-pinned demonstrative ("forget that,
  let's move on") references the prior turn — both fall through. A write cue
  still outranks a delete cue ("remember to delete that file tomorrow" stores a
  reminder).
- **Tool operation contract** (`backend/src/tools/memory_tool.py`): `memory_op`
  takes an explicit `operation` that WINS over re-reading the sentence for cues
  (the class that once persisted the word "list" as a fact), normalises the
  aliases the schema and the model use (delete/remove→forget,
  search/find→recall, facts/memory→list), and falls back to the sentence only
  on an unrecognised value. The keyword-recall matcher became a shared helper.
- **Delete matching tier** (`backend/src/storage/vector.py`,
  `_matching_ids_in_rows`): under the exact/prefix/key tiers, a conservative
  word-overlap tier — every content word the user named must sit on the row,
  and the row may add at most two content words the target never mentioned
  (the app's voice tail, "…in their editor"). A row describing something more
  specific than the target names is left alone; a vague one-word target
  matches nothing. The module-level ladder is shared with the tool-level fake
  store, so tool tests resolve deletes exactly like the real store.

## Live bug found by the live bar

The first "after" pass failed turn 3: "forget that I prefer dark mode" →
"Nothing in memory matches" while the seeded row sat right there — because the
store writes "The user prefers dark mode in their editor" and `matching_ids`
needed the exact wording. The word-overlap tier is that fix; the same turns
were re-run after it (`afterfix` pass), which is the pass that proves the
shipped state.

## Live verification (verification bar satisfied)

Harness: `scripts/live_test_memory_routing.py` — isolated `LOCALMIND_HOME` on
port 8766, provider zai/glm-4.5-flash via the real `/api/chat` SSE path, store
seeded (REST store 503s with the embedder down, so the seed is a direct
equivalent insert into `vector_facts`; verified visible through `/api/memory`),
before/after on the same three turns. "Before" ran from a worktree at the
pre-session revision.

| turn | before (HEAD) | after (shipped) |
|---|---|---|
| "What do you know about me?" | 15.5 s, provider call, model improvised from injected context — recited the public IP the write path refuses to store as a remembered fact | 4.5 s, **zero provider calls**, the store's id-bearing listing |
| "list my memories" | 105.6 s agent loop, rate-limited before it could show anything | 4.3 s, same listing, zero calls |
| "forget that I prefer dark mode" | 18.2 s, turn error, **row still in the store** | "Removed from memory", row read-back-gone, zero calls |

Server-log discriminators (`deterministic memory-read/delete`), the done
event's absent `provider_usage`, and the SQL row census back each cell.
Evidence: `office/sessions/2026-09-17-14/evidence/routing/` (before/after
results JSON, server logs, turn-1/turn-3 SSE captures).

## Unit verification

- 57 tests across the two new files (`test_memory_intent_routing.py`,
  `test_memory_runtime_routing.py`): store-vs-general-knowledge read routing,
  named-target vs discourse delete routing, write priority, both runtime
  routes, the full turn trail, failure honesty, and the fall-through to the
  model.
- `test_memory_resolution.py`: two fake-signature updates for the new
  `operation` kwarg.
- `test_memory_write_path.py`: the fake store's `matching_ids` now delegates
  to the shared ladder; 3 new cases (re-worded forget removes the stored row;
  a more-specific row is not loose-matched; a vague one-word target matches
  nothing).
- Wider sweep green: 317 memory/persist/fastpath core tests, 72
  vector/api/memory-adjacent tests. Full-suite run against the exit-gate
  baseline: see the session entry's gate note.

## Assumed, not proven

- The ≤2-app-voice-tail allowance: stores whose facts were written by much
  longer template sentences may need the allowance re-tuned (the guard only
  ever narrows, never deletes a row the target did not name).
- The embedder-present dedup path was not exercised live (no cloud key, Ollama
  down); it is unit-covered.

## Coordination

Nia (S015) was live the whole session on the AI-connections layer — disjoint
claimed paths, one note exchanged, no conflicts. Her `_provider_name`→
`_provider_key` fix sat uncommitted in the shared tree at my wrap-up; not
mine, left untouched, flagged on the trail.

## Open items

- Junk rows written by the pre-2026-09-17 bare-operation bug remain
  unpromoted (owner call — they live in user stores, not the repo).
- `PATCH /api/memory/{id}` still needs the vector table for its re-embed.
- Freshness tags still have no consumer until the parked
  geolocation/context-bootstrap work lands.
