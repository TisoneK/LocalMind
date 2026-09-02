# Advanced Agent Architectures — Research for LocalMind's Redesign

**Purpose.** LocalMind's parent loop makes 2–4 *sequential, mostly-silent* LLM
calls per user turn (pre-tool Thinker → tool-emit → post-tool Thinker →
synthesis). On a slow provider this reads as a multi-minute hang with an empty
"Thinking" block. This document researches how advanced agents — **Claude Code
(the tool this analysis was produced by), OpenCode, Cline, Cursor, Aider** — are
actually built, so the redesign copies a proven shape instead of inventing one.

**Bottom line up front.** Advanced agents are *not* fast because they avoid
reasoning. They are fast because:
1. **Reasoning and action are FUSED into one model call per step** — there is no
   separate "thinker" call; the model thinks *and* emits tool calls in a single
   streaming response.
2. **Everything streams**, so even slow generation *feels* alive.
3. **The loop is thin**; intelligence lives in the *model + system prompt*, not
   in a scaffold of orchestration calls.
4. Extra LLM calls exist only for **genuinely parallelizable or isolatable
   work** (sub-agents, not inline second-guessing), and those run concurrently.

LocalMind currently pays an "orchestration tax": it calls the model to *decide*,
again to *analyze*, again to *synthesize* — reasoning 2–4× where these agents
reason once. Half of a LocalMind turn is invisible, redundant round-trips.

---

## 1. The universal pattern: the agentic loop

Every one of these agents is, at its core, the same ~20-line loop:

```
messages = [system_prompt, user_message]
while True:
    response = model.stream(messages, tools=TOOLS)   # ONE call; reasons + acts
    render(response)                                  # stream thinking + text live
    if response.tool_calls:
        results = run(response.tool_calls)            # execute (often in parallel)
        messages += [response, results]
        continue                                      # loop: model sees results, continues
    break                                             # no tool call => the turn is done
```

Key properties that fall out of this shape:

- **One model call per iteration.** The call *is* the reasoning *and* the
  decision to act. "For trending stories": iteration 1 (think + call search) →
  run it → iteration 2 (think + write answer). Two round-trips, and the thinking
  is *inside* each, not a separate call.
- **The stop condition is "the model emitted no tool call."** No external
  "acceptance gate" LLM call decides doneness — the model signals completion by
  answering in prose. (Some agents add a lightweight structural check; none add
  a *second model call* to judge every candidate answer.)
- **Tool results are appended and fed back verbatim.** The model, not a
  post-processing LLM, decides what the results mean on its *next* turn.

This is the pattern in Anthropic's own "Building Effective Agents" guidance: the
effective agent is a model in a loop with tools and environment feedback — and
the advice is explicitly to **add orchestration only when it measurably helps**,
because every added LLM step adds latency, cost, and failure surface.

---

## 2. Anatomy of a single agent step (fused reason + act)

The thing to internalize: in a modern tool-calling model, **one API response can
contain reasoning, prose, and tool calls together.** A single streamed response
looks like:

```
[thinking]  "The user wants today's trending stories. I don't have that in
             context; I'll search the web, then summarize the top items…"
[text]      "Let me pull today's trending stories."      (optional, user-facing)
[tool_use]  web_search({query: "trending stories today"})
```

That is **one call**. The model reasoned about *what to do* and *did it* in the
same pass. There is no separate "planning" call that outputs a plan, followed by
a "tool" call that executes it — that separation is exactly the tax LocalMind
pays.

**Extended thinking** (Claude's thinking blocks, DeepSeek-R1-style reasoning,
o-series reasoning) is *part of this same call*. The model burns reasoning tokens
before the tool call or answer, and those tokens **stream to the UI as they are
produced**. Thinking is therefore never a separate round-trip — it's the front
of the response you were already waiting for.

---

## 3. Where the LLM calls actually go (the call budget)

For a task that needs N tool interactions, the call budgets compare like this:

| Turn shape | Claude Code / OpenCode / Cline | LocalMind (current) |
|---|---|---|
| Simple answer, no tool | 1 call | 1 call |
| One tool (e.g. web search) | **2 calls** (act, then answer) | **2–4 calls** (pre-Thinker, act, post-Thinker, synthesis) |
| N tools | **N+1 calls** | up to **~2N+2 calls** (a Thinker after each tool) |

The advanced agents' budget is **one call per step plus one to finish**. Every
call does real, visible work (it either acts or answers). LocalMind inserts
*additional* calls whose only output is internal ("analysis" that guides the
*next* call) — and, in LocalMind's case, those extra calls **stream nothing**,
so the user pays their latency and sees an empty "Thinking" box.

The math from the live test is stark: LocalMind produced ~790 tokens for
"Trending stories today" but split them across multiple calls at ~7 tok/s ≈ 110s;
Claude Code would produce the same information in 2 streamed calls, and on faster
infra, but the *architectural* difference alone (fewer calls, all streamed) is
the part LocalMind can actually close.

---

## 4. Streaming & perceived latency

**This is half the battle and it is free.** Advanced agents stream every token —
thinking, prose, and tool-call arguments — to the UI the instant the model emits
them. Consequences:

- A 40-second reasoning pass *feels* like watching the agent work, not a hang.
- The user can **read the plan forming and interrupt/steer early** (Claude Code,
  Cursor, Cline all support mid-stream steering / cancel).
- There is no "dead air": the moment of highest anxiety — after a tool returns,
  before the answer — is filled with visible synthesis tokens.

LocalMind's Thinker is **silent by contract** ("drain the consult silently — the
Thinker yields no user-visible chunks"). So its most expensive calls produce the
*worst* UX: maximum latency, zero feedback. Even before any re-architecture,
**streaming the model's reasoning during the calls LocalMind already makes** would
transform the felt experience.

---

## 5. Extended thinking / reasoning — inline, never a separate call

A crucial distinction the redesign must get right:

- **What LocalMind does:** a *separate* "Thinker" sub-model call whose job is to
  reason about the evidence and hand structured guidance back into the main
  model's context. Two models' worth of reasoning, serialized.
- **What advanced agents do:** the *same* model reasons inside the *same* call
  that acts or answers. If deeper reasoning is wanted, they turn up the model's
  own thinking budget (reasoning effort / thinking tokens) — they do **not** add
  a round-trip.

The lesson: **reasoning quality is a knob on the call you're already making, not
a new call.** If LocalMind wants the model to "analyze the evidence before
answering," the answer is *let the synthesis call think* (extended thinking on),
not *insert a prior analysis call*.

---

## 6. Context management (the actually-hard problem)

As the loop runs, `messages` grows — tool outputs are large (a fetched page is
thousands of tokens). This, not orchestration, is the real engineering. How the
advanced agents handle it:

- **Summarize/compact on threshold.** When the window fills, older turns and
  large tool results are compressed into a summary and the loop continues from
  it. (Claude Code does this automatically; the conversation carries a compacted
  summary forward.)
- **Trim tool results aggressively.** Old, already-acted-on tool outputs are the
  cheapest thing to shrink (head + omission marker + tail). The newest results —
  which the model still needs — are preserved.
- **Just-in-time retrieval over pre-loading.** Rather than stuffing everything
  into context up front, agents fetch (files, search results, docs) *when the
  step needs it*, keeping the working set small.
- **Structured note-taking / external memory** for long horizons (a scratchpad
  file, a todo list) so state survives compaction.

LocalMind already has pieces of this (tool-result stubbing, the todo/goal
checklist). The redesign should treat context management as a *first-class*
subsystem — it is what actually lets a thin loop run long tasks.

---

## 7. Tool design & orchestration

- **Native tool-calling.** The model emits structured tool calls; the harness
  validates and executes. No LLM "router" call chooses the tool — the acting
  model chooses, as part of acting.
- **Parallel tool calls.** When steps are independent (read 3 files, hit 2
  endpoints), the model emits several tool calls in one response and the harness
  runs them concurrently. This collapses N sequential round-trips into one.
- **Tool results as plain, honest data.** Results (including errors) go back
  verbatim; the model reasons about failure on its next turn ("that 404'd, try
  the other path") — recovery is inline, not a special orchestration branch.
- **Few, well-described tools beat many narrow ones.** Tool *descriptions* are
  prompt real estate; agents invest in a small set of sharp, unambiguous tools.

---

## 8. When multiple LLM calls ARE justified — and how they stay fast

The user is right that a redesign must handle *multiple* LLM calls well. The
point is not "never more than one call" — it's "extra calls must be **parallel,
isolatable, and visible**, not **serial inline second-guessing**." Legitimate
multi-call patterns:

- **Sub-agents / delegation (the orchestrator–worker pattern).** A parent spawns
  focused sub-agents for independent sub-tasks, **run concurrently**, each with
  its own clean context; the parent composes their results. This is how Claude
  Code's Task/subagents and "deep research" systems scale — the extra calls buy
  *parallelism and context isolation*, and they run at the same wall-clock time,
  not stacked. (LocalMind already has a `delegate` tool + child agents — this is
  the right primitive; the redesign should lean on it for breadth.)
- **Prompt chaining for genuinely distinct stages** (e.g. draft → then a
  separate polish/verify pass) — justified when each stage is a different *kind*
  of work and the gate between them catches real errors. Kept to a *few* stages,
  not one-per-tool.
- **A cheap, bounded verifier** (LLM-as-judge) on the *final* output only, when
  correctness matters more than latency — one call at the end, not one per step.

The anti-pattern LocalMind fell into: a **serial, silent "analyze" call after
every single tool result**, on the critical path, adding latency with no
parallelism and no visible output. That is the opposite of every pattern above.

**Design rule for LocalMind:** extra LLM calls are for **breadth (parallel
sub-agents)** and **occasional distinct stages (a final verify)** — never for
**inline narration of what the next call is about to do**.

---

## 9. Prompt architecture (the guide, not the orchestration)

- **The system prompt is the agent.** OpenCode ships *model-specific* system
  prompts (a GLM/DeepSeek `default.txt` distinct from the Anthropic one) —
  because the discipline that makes weak models behave (be concise, act don't
  narrate, ground answers in evidence, use tools when needed) is delivered by
  *prompt engineering*, not by wrapping the model in extra LLM calls.
- **Examples > rules.** Calibrated few-shot examples of the desired
  reason-then-act shape steer behavior more reliably than prose rules.
- **This is the crux for LocalMind:** the Thinker/acceptance-gate scaffold was
  bolted on to make weak models behave. The proven cheaper substitute is a
  *disciplined, model-aware system prompt* (LocalMind already has a first version
  of this) that gets the model to reason-and-act in one pass.

---

## 10. Per-agent notes

- **Claude Code (this tool).** Thin loop over the Messages API. One streamed call
  per step; the response carries interleaved thinking + text + `tool_use`.
  Parallel tool calls in a single response. Automatic context compaction when the
  window fills. Sub-agents (Task) for isolatable/parallel work, each with its own
  context window. No separate "thinker"/"router"/"acceptance" model calls on the
  hot path — the model does all of it inline, streamed.
- **OpenCode.** Open-source, provider-agnostic coding agent. Same native
  tool-call loop; notable for **model-tuned system prompts** and a lean loop that
  runs well on non-Anthropic models (including the same bankofai/GLM/DeepSeek
  endpoints LocalMind uses) — evidence that the *architecture*, not a premium
  provider, is what makes it feel good.
- **Cline (VS Code).** Plan/Act modes, native tool-calling, human-in-the-loop
  approval of each tool action, streaming. Its key discipline: **if the model
  returns prose where a tool call was expected, reject and re-prompt** — a
  cheap structural correction, not a second reasoning model.
- **Cursor.** Editor-integrated; heavy on *context retrieval* (codebase
  indexing/embeddings) feeding a fused reason+act model call; aggressive
  streaming and speculative edits for perceived speed.
- **Aider.** Minimal, git-native; a tight edit/apply/test loop with strong
  prompt discipline and repo-map context — a good example of "thin loop + good
  context + good prompt" beating orchestration.

Common denominator: **thin loop, fused reason+act call, streaming, native tools,
strong prompt; extra calls only for parallel sub-agents.**

---

## 11. Where LocalMind diverges (the tax it pays)

| Dimension | Advanced agents | LocalMind (current) |
|---|---|---|
| Calls per single-tool turn | 2, both visible | 2–4, two of them silent |
| Reasoning | inline in the acting/answering call | separate Thinker sub-calls |
| Streaming | everything streams | Thinker silent; synthesis reasoning not surfaced (esp. deepseek) → empty "Thinking" box |
| Doneness | model stops calling tools | model + acceptance-gate machinery |
| Extra calls | parallel sub-agents | serial, on the hot path |
| Weak-model discipline | model-tuned prompt | Thinker + gates + replan scaffold |
| Context mgmt | first-class (compaction, trim, JIT) | partial |

The tax is: **reasoning is paid for 2–4× per turn, serially, and most of it is
invisible.** That is the entire felt-latency story on a slow provider.

---

## 12. Design principles for LocalMind's redesign

1. **One model call per step; fuse reason + act.** Delete the separate pre/post
   Thinker calls from the hot path. Let the acting call reason (extended thinking
   on) and the synthesis call reason — each once.
2. **Stream everything.** Forward the model's real reasoning to the Thinking
   panel (fix the deepseek empty-block path) and stream synthesis tokens. This
   alone fixes most of the *felt* latency for free.
3. **Doneness = the model stopped calling tools.** Replace the per-answer
   acceptance-gate *LLM call* with a cheap structural check (did it act when it
   promised to? is the answer non-empty?) — the seam work already started
   (`turn_outcome`) is the right home; it must stay *code*, not a model call.
4. **Discipline via prompt, not orchestration.** Lean on the disciplined,
   model-aware system prompt (already begun) to get reason-then-act in one pass;
   retire the scaffolding the Thinker/gates were compensating for.
5. **Extra LLM calls buy breadth, run in parallel.** Reserve multi-call patterns
   for the `delegate` sub-agent path (independent sub-tasks, concurrent, isolated
   context) and an optional single final verify — never inline per-tool analysis.
6. **Context management is a subsystem, not an afterthought.** Compaction, tool-
   result trimming, and just-in-time retrieval are what let a thin loop go long.
7. **Keep the model+provider swappable and measure per model.** Prompt-tune per
   model family (the OpenCode lesson); measure tokens-per-turn and calls-per-turn
   as first-class metrics.

---

## 13. A concrete target loop for LocalMind

```
messages = build_context(system_prompt, memory, user_msg)   # code, no LLM
while iteration < cap:
    # ONE streamed call: reasons (thinking streamed to panel) + acts/answers
    resp = adapter.stream(messages, tools=current_tools, thinking=on)
    stream_to_ui(resp.thinking, resp.text)                  # live
    if resp.tool_calls:
        results = await run_parallel(resp.tool_calls)        # concurrent
        messages += [resp, results]
        messages = compact_if_needed(messages)               # code, no LLM
        continue
    # no tool call => done. Structural completion check only (code):
    outcome = classify_turn_outcome(resp, tools_ran)         # ACT/ANSWER/INCOMPLETE
    if outcome is INCOMPLETE and recoverable:
        messages += nudge(outcome)                            # a reminder, not a call
        continue
    break
# Breadth when needed: parent emits `delegate(...)` sub-tasks that run as
# PARALLEL sub-agents with isolated context, composed on return.
```

Calls per turn: **one per step + finish** (like the advanced agents), all
streamed, with the model's own reasoning doing the analysis the Thinker used to
do as a separate round-trip. Multi-call scaling happens through **parallel
sub-agents**, not serial inline calls.

---

## 14. Open questions to resolve before implementing

1. **Does removing the Thinker regress weak models?** Needs an A/B on
   bankofai/glm-4.5-flash (the "weak" model) — disciplined-prompt-only vs
   Thinker — measuring correctness *and* calls/turn. The hypothesis (from
   OpenCode) is that a good prompt replaces the Thinker; verify it.
2. **deepseek reasoning forwarding.** Confirm why the Thinking panel is empty for
   deepseek-v4-flash — is the adapter surfacing its reasoning tokens at all? This
   is likely an adapter/bridge gap independent of the loop redesign.
3. **Acceptance gate → structural check.** Enumerate what the acceptance-gate
   LLM call currently catches, and confirm each can become a code check on
   `turn_outcome` (most already can).
4. **Streaming plumbing.** Verify the SSE bridge can stream synthesis tokens
   incrementally (not buffer-then-emit) for all adapters.

---

*Prepared as the research basis for the multi-LLM-call architecture redesign.
The redesign itself should land as an ADR in `.context/plans/decisions.md`,
scoped and sequenced against the principles in §12.*
