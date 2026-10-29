# Independent review — S031 done-rules extension (`9bfe6fd2`)

**Reviewer:** Jabari (S033), GLM (Z.ai) — supervisor-requested second pass, 2026-10-29.
**Claim:** `20261029T194414Z-Jabari-59e75997` (read-only on product code; this file and the
ledger records are the write scope). **Tree reviewed:** `f6c6e54d` (product-identical to
`f054688f`, where S031 shipped; the two commits between differ only in ledger files).

## Verdict: PASS with findings — the release stands

Every guarantee S031 claims was verified live on this tree, by code read and by wire
evidence. Two findings were logged — one harness-determinism flaw that produced two
false-negative live runs, one consolidation residue in the loop — and neither is a runtime
defect in the shipped guarantees. Both are one-commit-sized follow-ups, parked for the owner.

## Evidence

- **Unit:** `tests/core/test_done_rules.py` + `tests/core/test_turn_outcome.py` — **40/40
  passed** (1.4s). The death matrix, all five delivery shapes (including the negative
  "no try-again on a terminal death" assertions), the unanswered-call classification, the
  pairing repair (with a mutation-freedom assertion on paired messages), and four loop-level
  runs through the real `AgentLoop.run` asserting what the *next provider request* carries.
- **Loop-adjacent regression slice:** empty-response, pre-tool-thinker, post-loop-synthesis,
  post-turn-budget, trivial-turn, turn-bus, goal-tree, history-dedup — **73/73 passed**.
- **Live, `live_test_done_rules.py` probe A (the core S031 guarantee):** wire-perfect. The
  timed-out `code_exec` left an `OUTCOME UNKNOWN` placeholder on the SSE tool_call record AND
  in a captured provider request as a tool message, forbidding a blind re-run; **9 provider
  calls** total (matching the documented post-fix count), closing on the honest completion
  floor; pairing across all 11 captured requests: **0 unanswered**.
- **Live, the with-evidence degraded path — confirmed via the provenance harness:**
  `live_test_provenance_symmetry.py` **PASS (exit 0)** on this tree, including its own death
  probe: *"the provider death surfaced as a terminal degraded event with the canonical error
  object"*. That is the S030+S031 machinery working end to end when the harness state machine
  stays aligned.
- **Live, `live_test_identity_injection.py`:** **PASS (exit 0)**.

## Finding 1 (medium, test infra) — the harness fakes race the product's background provider calls

`live_test_done_rules.py` probe B and `live_test_provider_death_honesty.py` probe A both
**failed on this tree** in two runs, on product code byte-identical to the tree where both
passed the day before. Mechanism, traced through `scratch/donehome-server.log`:

1. Both fakes key their state machine on **absolute request position** (`request_count == 1`
   → emit the tool call; the next request → the death payload).
2. The product legitimately makes provider calls **outside the loop**: probe A's background
   title refinement (observed at 19:49:31, `[title] no classify title — LLM refinement
   scheduled`), conversation-state classification, the init classifier.
3. In my run, the title call landed inside probe B's window and consumed the fake's `n=1`
   slot. The sysinfo call went to a consumer that ignores tool calls; the loop's first
   request hit the death payload **evidence-less**; the failover layer poisoned the provider
   (`[failover] fakeprov failed (payment_required)`); the loop aborted at iter=1.
4. The probes then assert things only a with-evidence death produces (terminal
   `agent_loop_degraded`, framing, persisted phase) → false FAIL.

The product's behavior on the mis-routed death was **honest on every assertion that still
applied**: the canonical error object rode the stream with `payment_required`, non-retryable;
the answer named the provider and the code and contained no "try again". The failure is the
harness's, not the loop's. This is the same class Nadia documented on the provenance harness
(cold-home init call consumes the per-probe counter) — the root cause is general: **a
request-position state machine cannot share a fake provider with a product that makes
out-of-band provider calls.** Fix options, smallest first: content-key the fake (emit the
tool call for any request whose messages lack the expected tool result; die only on a request
carrying that result), or disable title refinement / drain scheduled work between probes in
the harness settings.

## Finding 2 (minor, product residue) — the no-evidence death wording still lives outside the contract

The S031 commit message says "The loop no longer carries its own booleans or wording for it."
True for the with-evidence path — but the no-evidence death branch still composes its own
text inline at `loop.py:6739-6748` (the pre-contract wording "…can't continue because the
failure is not retryable.", plus the generic large-model advice line). Meanwhile the
contract's matching shapes (`provider_death_answer`'s `tool_count == 0` terminal notice) are
**unreachable from the loop** — that branch routes to the inline text before the contract is
consulted. The frontend carries rewrite regexes for **both** wordings
(`errorText.ts:13-14`), so the duplication is load-bearing today. Honest either way (both
wordings name provider + code and refuse retry advice), but there are two truths in two
places where the consolidation meant one. Fix: route the dead-end branch through the contract
and delete the frontend's duplicate regex, or delete the unreachable contract shapes and
state the split explicitly. Per the playbook's deep-scan rule, all instances in one commit.

## Observations (no action taken)

- `_task_index.get(_fut, 0)` in the batch path defaults a lost task to index 0, which could
  in principle overwrite sibling 0's real result with a placeholder. Unreachable with current
  `asyncio.as_completed` semantics (it yields the original task objects), but a safer default
  costs nothing.
- `classify_unanswered_call`'s timeout detection in the retry-exhausted branch string-matches
  `"timed out"` in attempt errors; a differently-worded timeout degrades to "abandoned
  mid-run" prose — same UNKNOWN classification, same guidance, prose only.
- `except (ValueError, Exception)` in the dispatch handler is redundant (pre-existing).
- `SIDE_EFFECT_FREE_TOOLS` is currently the only side-effect registry (no read-only metadata
  in `tool_schemas.py` to drift from) — safe default direction (unlisted ⇒ treated as
  side-effecting), worth remembering when tool metadata appears.
- Terminal wording capitalization varies between "The model provider" and "the model
  provider" across `provider_death_answer` shapes — cosmetic.

## Platform note on the older harnesses' exit codes

Nadia's Windows baseline ("all three print PASS and exit 1 — the port sweep taskkills the
harness's own PID") did not reproduce on this Linux sandbox: identity and provenance exited
**0** after PASS. `live_test_provider_death_honesty.py` exited 1 here — but from Finding 1's
real probe failure, not the sweep. Exit-code baselines for these scripts are
platform-dependent until Soren's `harness-exitcode-fix` branch (socket closed before the
sweep) lands.

## Scope of this review

No product edits (per the claim). The full backend suite was not re-run — Nadia's corrected
sequential-batch evidence (3717 passed / 4 skipped, per her correction event
`20261029T094820Z-Nadia-7fed8ca1`) stands, and my slice runs are consistent with it.
