# Done-rules extension — when a step never reports back

Roadmap §U item 4 (`docs/reference-harness-gap-inventory.md`, row **E**). The
row names two things: synthetic results for unanswered calls, and the
provider-death completion path from item 1 stated as part of the done contract
rather than a rescue hack bolted onto the loop.

## What the contract actually was

`core/agent/turn_outcome.py` already names the turn states (ACT / ANSWER /
INCOMPLETE) and reduces every "the model stopped early" detector to one of two
recoveries. Everything about *losing* the answer lived somewhere else: the
provider-death branch was ~130 inline lines in `loop.py`, deciding by boolean
whether a dead synthesis still owed the user an answer, then composing the text
for each shape itself. And a call that never returned was simply labelled
"failed", even when the truth was that nobody knew whether it had run.

## What changed

**Provider death is now a state of the contract.** `classify_provider_death()`
answers one question — does this death still leave the turn owing an answer —
from the facts known at error time (source, code, retryability, whether
successful tool work is in hand). It returns the turn outcome
(`DEGRADED_ANSWER` when evidence is in hand, `INCOMPLETE` when it is not) plus
whether the death is terminal. `provider_death_answer()` composes the delivery
for every shape it can produce: an extracted answer framed "as gathered" on a
terminal death, the raw evidence blocks, the honest no-evidence notices. The
loop now calls both and no longer owns the decision or the wording.

**A call that never answered gets a recorded result.**
`classify_unanswered_call()` builds the placeholder from the two facts that
matter: whether the error could only have happened before the tool body acted
(argument/shape errors are known failures), and whether the tool can leave a
durable effect. Anything else is OUTCOME UNKNOWN, and the text forbids a blind
re-run for side-effecting tools while telling the model a read-only one is safe
to repeat. `pair_unanswered_tool_calls()` is the invariant behind it: every
assistant tool call without a matching result gets one, appended at the
iteration head, with the repair itself emitted as a `tool_call_unanswered` audit
event. The batch path also stops letting one raised sibling kill the batch —
that call is recorded as unknown-outcome and the other results survive.

**A turn that cannot act closes honestly instead of replanning.** The live proof
found this, not the reading: a parent turn whose only tool timed out and whose
model answered without acting was re-asked by the completion floor on every
iteration — 19 gate replans, 43 provider calls, one failed call. The floor now
spends the same bounded replan budget the criteria path already uses
(`_MAX_TOTAL_GATE_REPLANS`), so the turn ends with the honest floor summary.
Same turn after the fix: 9 provider calls.

## Evidence

- **Unit:** new `tests/core/test_done_rules.py`, 22 tests — the death-rule matrix
  (terminal/retryable/no-evidence/wrong-source/unknown code), every delivery
  shape including the "no try-again on a terminal death" guarantee, the
  unanswered-call classifications, the pairing repair, and three loop-level runs
  that assert what the *next* provider request actually carried. The replan-bound
  test was verified to fail with the cap disabled and pass with it (9 iterations
  vs 5 calls), so it pins the fix rather than the setup.
- **Live (wire capture, no provider credential):** new
  `scripts/live_test_done_rules.py` boots the real server on isolated port 8765
  against a fake OpenAI-compatible provider that captures every request body.
  PASS: the timed-out call's unknown-outcome result reached a captured request
  as a tool message and forbade a blind re-run; every captured request paired
  its tool calls (0 unanswered across 12 requests); the sysinfo evidence then
  the exact 12:45 death delivered the evidence framed with
  `payment_required` and "not retryable", `agent_loop_degraded` came through
  terminal with the provider named, the canonical error object rode the stream,
  and the degraded phase survived a reload.
- **Regression:** the three prior live harnesses re-run on this tree —
  `live_test_provider_death_honesty.py` PASS, `live_test_identity_injection.py`
  PASS, `live_test_provenance_symmetry.py` PASS (its first run fails on a cold
  scratch home: the one-time initialization call consumes its per-probe request
  counter, so the probes start one call late; second run and every run after is
  green — logged as friction, not chased).

## Open

- The fast path and the history-fallback surface still do not emit their own
  injected-items events (carried over from the previous session's honest scope).
- The trajectory view is still built from live-stream accumulators rather than
  being a pure projection of the persisted record — the ledger's persistence and
  the degraded phase remain its first teeth.
- A real-model live run (the acceptance bar's first clause) still needs provider
  credentials this machine does not hold; everything above is wire-captured
  against a fake provider, which proves the loop's plumbing and the honesty of
  what it says, not the behaviour of any particular model.
