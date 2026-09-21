# Research: refusals, plans and recovery in the agent loop (2026-09-21)

Author: Wanjiru / claude-sonnet-5 (Session 26). Evidence: live DeepSeek (deepseek-chat / deepseek-flash)
runs on an isolated stack, plus three real-user transcripts pasted by the owner. Every claim below
names what was observed; nothing is from memory of how such systems "usually" behave.

## 1. Question

The owner asked, in order: how can a tool know a "placeholder" without a model; whether the agent
should signal intent to tools; and whether the pattern generalises. Alongside it, four failures
showed the same root shape: something in the loop *guessed* where it should have *checked* or
*asked*.

## 2. Observations

| # | What happened | What guessed | Evidence |
|---|---|---|---|
| O1 | `file_write` refused `42` ("content is too short … not a placeholder") | that a short body is a mistake | S26 live run; `loop.py` guard was `len(content.strip()) < 5` |
| O2 | The user-text exemption missed "containing **the text** 42" | that only "containing 42" is a request for a literal | regex cue list |
| O3 | A good write was reported "verification FAILED … do NOT claim the file was created" | that a read tool failing means the write failed | `style.css` after `index.html` verified; the check dispatched a tool |
| O4 | A lookup showed the same three tasks ("Search / Read / Answer") known before anything ran; the step for a dead site was ticked done | the shape of every lookup; that narration means a step finished | owner screenshot; `lookup_plan.LOOKUP_STEPS` (S26's own earlier work) |
| O5 | The agent went back to a site that had failed (5 tools, 1m46s) | that the "best source" is still best after it failed | owner transcript |
| O6 | "Conversation too long" on a 3K-token chat, 1M-token model | that "exceeds the maximum" means the prompt | `error_normalizer` keyword rule; raw text not captured |
| O7 | "yes" after an offer got "I can't run that, switch to Agent mode" in Auto mode | that a bare "yes" is small talk | S26 live reproduction |
| O8 | One "Thought" block of 2m 37s / 75 lines for a two-file task | that all phases are one thought | UI accumulated every `thinking_start` into one string |

## 3. Findings

**F1. The failures are one failure.** In O1, O2, O3, O4, O6 and O7 a component decided something
about *intent or outcome* from a proxy (length, a phrase, a tool's exit status, narration, a
keyword, a word's shape). In every case a fact was available and cheaper: file existence/size on
disk (O1, O3), the tool's own result (O4), the token counts (O6), the previous assistant turn (O7).

**F2. A tool cannot know intent; the model can. A tool can know facts; the model cannot verify them.**
The clean split is: the tool states verified facts and refuses only on those; the model supplies
intent through an explicit, named signal. This is why a *"this is a placeholder"* flag from the
model would rarely help (a model that passes junk does not know it is junk), while an *"I mean it"*
flag on a refusal the tool can justify works.

**F3. Plans that are known before work starts cannot follow the work.** A canned skeleton (O4)
looked like planning and was contradicted by the first failure. Emergent tasks (one per real
action) plus the model's own `todo_write` list follow reality; per-step status must come from the
tool outcome, not from narration.

**F4. Failure needs memory at the layer that repeats it.** O5's loop is the model's habit; the
cheapest reliable interruption is in the tool that gets called (`web_fetch` remembers hosts that
refused/timed out/were unreachable for 15 minutes and answers a repeat with "pick a different
source"). A 404 must only block that page.

**F5. Error classification must keep input and output apart.** "exceeds the maximum" is ambiguous
between a prompt limit and `max_tokens`. The card must show the provider's actual text for a
"too long" verdict on a short chat, because the classification is the least trustworthy part.

**F6. Silent recovery is only acceptable if it is inspectable.** Provider failover (rate limit,
quota, outage) is invisible by design but must announce what it is doing ("X is out of quota —
switching to Y") and must never move a *local* model's conversation to a cloud provider the user
did not choose.

## 4. Options considered for F2 (the protocol)

1. **Model flags junk** (`placeholder: true`). Rejected: unobservable failure mode; adds a field the
   model will not set when it is wrong.
2. **Heuristic guard** (status quo: length / phrase lists). Rejected: O1, O2 — every list is
   incomplete; users pay with refused work.
3. **No guard at all.** Cheap, but loses protection against overwriting a real file with a stub.
4. **Confirmable refusal** (chosen): refuse only on a verified fact, name the fact, name the flag
   that confirms; log the flag. Shipped for `file_write` overwrite (`overwrite: true`).

## 5. Recommendation

Adopt *tools state facts; models supply intent* as a standing rule (ADR-67); make plan status a
function of tool outcome (ADR-68); keep provider failover as the one place recovery is silent
(ADR-69); treat "where things run/install" as a user setting, never an assumption (ADR-70). Open
work is queued in the backlog under `B-2026-09-21-*`.

## 6. Not established

- The raw provider error behind O6 was never captured; the reproduction is missing. The
  classification fix is defensible on its own, but it is *not proven* to be that user's cause.
- The Windows shell choices (PowerShell / cmd / Git Bash) and the packages-folder `PYTHONPATH`
  were verified only through simulated detection and macOS runs.
- The per-phase thinking split works live; chats reloaded from history do not store the split.
