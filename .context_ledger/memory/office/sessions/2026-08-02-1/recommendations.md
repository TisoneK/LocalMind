# Borrowing Recommendations — Codebuff Ideas for LocalMind

> Companion to `kickoff.md` and `comparison.md`. Each recommendation is
> scored on **impact** (what it unlocks), **effort** (how much code),
> **risk** (what it could break), and **model-readiness** (does it work
> with `llama3.1:8b` or does it need a stronger model?).
>
> Recommendations are grouped into three tiers:
> - **Tier A — borrow now**: high impact, low risk, works with current
>   local models.
> - **Tier B — borrow after ADR-8**: high impact, medium risk, requires
>   structural changes that ADR-8 already plans.
> - **Tier C — borrow when cloud routing lands**: high impact, requires
>   per-agent model selection (which itself needs the OpenAI-compat
>   adapter wired through `AgentConfig`).

---

## Tier A — Borrow Now (Low-Risk, High-Value)

### A1. Bounded output buffer for `shell` and `code_exec`

**Borrow from:** Codebuff `sdk/src/tools/run-terminal-command.ts:80-144`
(`BoundedOutputBuffer` class).

**Impact:** Currently `code_exec` has a 4000-char output cap
(`localmind.md:111`) and `shell` has a similar cap. When a command
produces 50KB of output, the agent sees only the first 4000 chars and
loses the tail — which is often where the error message is. A
head+tail buffer (keep first N chars + `[...TRUNCATED DUE TO LENGTH...]`
+ last M chars) preserves the error context.

**Effort:** ~80 lines of Python in `backend/src/tools/code_exec.py`
and `backend/src/tools/shell.py`. Add a `BoundedOutputBuffer` class
to `core/utils.py`. Existing tests should pass; add 2-3 new tests for
the truncation behavior.

**Risk:** Very low. Output shape changes (now includes a truncation
marker), but the agent prompt can be updated to explain the marker.
No API changes.

**Model-readiness:** Works with all models. The truncation marker is
self-explanatory.

**Concrete steps:**
1. Add `BoundedOutputBuffer` to `core/utils.py` with `head_chars`,
   `tail_chars`, and `total_cap` parameters.
2. In `code_exec.py:runner.py`, capture stdout/stderr into a
   `BoundedOutputBuffer(head=2000, tail=2000, total_cap=4000)`.
3. In `shell.py`, same pattern with `head=2000, tail=2000, total_cap=4000`.
4. Update `core/prompts/code_exec.md` and `core/prompts/shell.md` to
   mention the `[...TRUNCATED DUE TO LENGTH...]` marker.
5. Tests: `tests/tools/test_bounded_output.py` — verify head+tail
   retention, marker insertion, and under-cap passthrough.

---

### A2. Abort signal threading

**Borrow from:** Codebuff `RunOptions.signal` (`sdk/src/run.ts:175`)
threaded through every layer; `loopAgentSteps` checks `signal.aborted`
at the top of each iteration (`run-agent-step.ts:985`).

**Impact:** Currently there's no clean way for the UI to cancel a
running agent. The Electron frontend can close the SSE stream, but
the backend `AgentLoop` keeps running until it hits a wall-clock or
iteration cap. An `asyncio.Event` (Python equivalent of
`AbortSignal`) threaded through `AgentLoop.run()` → `BaseAgent.run()`
→ `adapter.chat()` would let the UI cancel cleanly.

**Effort:** ~150 lines across `core/agent/loop.py`, `agents/base_agent.py`,
`core/engine/_pipeline.py`, and `api/routes/chat.py`. Add an
`abort_signal: Optional[asyncio.Event]` parameter to `AgentLoop.run()`
and `BaseAgent.run()`. Check it at the top of each loop iteration and
in the adapter's stream loop. Raise `AgentAbortedError` when set.

**Risk:** Medium. Need to ensure cleanup runs (generators are
properly closed, sub-agent delegations are cancelled, obs events are
flushed). Test the abort-during-tool-execution path carefully.

**Model-readiness:** Works with all models.

**Concrete steps:**
1. Define `AgentAbortedError` in `core/models.py`.
2. Add `abort_signal: Optional[asyncio.Event] = None` to
   `AgentLoop.run()` signature.
3. Check `if abort_signal and abort_signal.is_set(): raise AgentAbortedError()`
   at the top of each loop iteration in `loop.py`.
4. In the adapter's `chat()` stream loop, check after each chunk.
5. In `api/routes/chat.py`, expose a `POST /api/chat/{session_id}/abort`
   endpoint that sets the event.
6. In the frontend, add a "Stop" button that calls the abort endpoint.
7. Tests: `tests/e2e/test_abort_signal.py` — verify abort during
   planning, during tool execution, during streaming.

---

### A3. Hit-limit-aware fallback messaging (already partly done, extend it)

**Borrow from:** LocalMind's own Session 32 contract (this is a
self-borrowing — the pattern is already in place, just needs
extending to delegation).

**Impact:** When `delegate` times out
(`DELEGATION_WALL_CLOCK_SECS = 120s`), the parent agent currently
gets a generic `ERROR: delegation to 'research' timed out after 120s`
message. A more diagnostic message would say: "delegation timed out
— the sub-agent may have hit its own iteration limit, or the model
may be overloaded. Suggest: tell me to continue, or switch to a
smaller sub-task."

**Effort:** ~50 lines in `tools/delegate.py`. Add a
`_diagnose_delegation_failure(report: DelegationResult) -> str`
helper that produces a diagnostic message based on
`report.error_type` (`timeout`, `construction_failed`, `child_exception`,
`empty_response`).

**Risk:** Very low. Pure message improvement.

**Model-readiness:** Works with all models.

**Concrete steps:**
1. In `tools/delegate.py`, add `_diagnose_delegation_failure()`.
2. Replace the static `f"ERROR: delegation to {target_agent!r} timed out..."`
   strings with calls to this helper.
3. Tests: `tests/tools/test_delegate_diagnosis.py` — verify each
   error_type produces a distinct, actionable message.

---

### A4. Tool-result simplification under memory pressure

**Borrow from:** Codebuff's `simplifyReadFileResults` and
`simplifyTerminalCommandResults` helpers (referenced in
`codebuff-deep-profile.md` §10.2 and §12.6).

**Impact:** When the agent's context window fills up, LocalMind
currently trims oldest-first (`localmind.md:163`). This loses
information wholesale. A better approach: replace old `file_task`
tool results with stubs like
`{ path: "backend/src/agents/coding/agent.py", contentOmittedForLength: true }`
so the model still sees *that* a file was read, just not its contents.
Same for `shell` results — keep the command but stub the output.

**Effort:** ~120 lines in a new `core/context_compactor.py` module.
Walk the message history, find old tool messages, replace their
content with stubs based on tool type. Wire into `AgentLoop._assemble_messages()`
to run when token count exceeds 80% of context window.

**Risk:** Medium. Need to preserve the most recent N tool results
uncompressed (the agent needs them for current-step reasoning). Need
to be careful not to stub the *current* tool's output. Tests are
critical.

**Model-readiness:** Works with all models. The stub pattern is
self-explanatory in the prompt.

**Concrete steps:**
1. Create `core/context_compactor.py` with `compact_history(messages, keep_recent=5)`.
2. Identify tool messages by `role == "tool"` and the tool name in metadata.
3. For `file_task` results older than `keep_recent`, replace with
   `{ "path": "...", "contentOmittedForLength": true }`.
4. For `shell` results, keep the command but stub the output.
5. For `code_exec` results, keep the code but stub the output.
6. Wire into `AgentLoop._assemble_messages()` — run compactor when
   `token_count(messages) > 0.8 * context_window`.
7. Update `core/prompts/base.md` to mention the stub pattern.
8. Tests: `tests/core/test_context_compactor.py` — verify recent
   results preserved, old results stubbed, stub format correct.

---

### A5. Steering without aborting

**Borrow from:** Codebuff `drainSteeringMessages`
(`run-agent-step.ts:684-688`, `1149-1162`).

**Impact:** Currently if a user wants to redirect a running agent,
they have to abort and re-run. Steering lets the host inject a user
message at the next step boundary — the agent sees it as a new user
prompt and continues its turn. Smoother UX.

**Effort:** ~100 lines. Add a `steering_messages: asyncio.Queue`
to `AgentLoop`. At the top of each iteration, drain the queue and
append the messages to `messages`. Expose a
`POST /api/chat/{session_id}/steer` endpoint that puts a message
on the queue.

**Risk:** Medium. Need to handle the case where the agent is
mid-tool-execution when a steering message arrives (defer to next
iteration boundary). Need to ensure the steering message is tagged
so it doesn't get compacted by A4.

**Model-readiness:** Works with all models.

**Concrete steps:**
1. Add `steering_queue: Optional[asyncio.Queue] = None` to
   `AgentLoop.__init__`.
2. At the top of each loop iteration, `while not steering_queue.empty():
   msg = await steering_queue.get(); messages.append(msg)`.
3. In `api/routes/chat.py`, add `POST /api/chat/{session_id}/steer`
   that puts `{"role": "user", "content": "..."}` on the queue.
4. Frontend: add a "Steer" input that's enabled during agent runs.
5. Tests: `tests/e2e/test_steering.py` — verify steering message
   arrives at next iteration, doesn't interrupt mid-tool.

---

## Tier B — Borrow After ADR-8 (Medium-Risk, Structural)

### B1. Parallel delegation primitive

**Borrow from:** Codebuff `spawn_agents` (`spawn-agents.ts:34-263`)
using `Promise.allSettled` for parallel fan-out.

**Impact:** This is **LocalMind's biggest functional gap**. Without
parallel delegation, the system cannot express: best-of-N editing,
parallel research + coding, multi-perspective review, speculative
execution. See `comparison.md` §5.3 for the full list.

**Effort:** ~250 lines. Add a `delegate_parallel` tool in
`backend/src/tools/delegate_parallel.py` that:
- Takes `targets: list[{agent, task, scope?, constraints?, forbidden_tools?, output_requirements?}]`
  (max 5 to bound fan-out).
- Constructs one `DelegationInstructionPacket` per target.
- Runs all child agents concurrently via
  `asyncio.gather(*[agent.run(packet) for packet in packets], return_exceptions=True)`.
- Returns a `ToolResult` whose `content` is a markdown summary of
  all children's outputs, and whose `metadata["results"]` is a
  `list[DelegationResult]`.
- Honors `MAX_DELEGATION_DEPTH = 2` and
  `DELEGATION_WALL_CLOCK_SECS = 120s` (the wall-clock cap applies to
  the gather, not per-child).

Register as `Intent.DELEGATE_PARALLEL` with `parallelizable=True`.
Add to `AGENT_ALLOWED_TOOLS` and to `CodingAgent`'s scoped toolset
(other agents can opt in later).

**Risk:** High. Concurrent agent runs share the adapter — need to
verify the Ollama adapter is thread-safe (or use a per-run adapter
pool). The OpenAI-compat adapter should be fine (stateless HTTP).
The `contextvars`-based `_current_run_id` and `_current_depth` need
to propagate correctly across `asyncio.gather` — `contextvars.copy_context()`
may be needed.

**Model-readiness:** Works with cloud models (Opus, Gemini). With
local `llama3.1:8b`, parallel runs may thrash the model server
(Ollama serializes requests by default unless `OLLAMA_NUM_PARALLEL > 1`).
For local-only setups, this primitive may be limited to 2-3 parallel
children until stronger local models arrive.

**Concrete steps:**
1. Read `tools/delegate.py` end-to-end — the parallel version is
   mostly a `gather` over the existing logic.
2. Create `tools/delegate_parallel.py` modeled on `delegate.py`.
3. Extract the child-run logic from `delegate.py` into a shared
   `_run_child(packet, adapter, depth) -> DelegationResult` helper.
4. `delegate_parallel` calls `_run_child` N times via
   `asyncio.gather(..., return_exceptions=True)`.
5. Register `Intent.DELEGATE_PARALLEL` in `core/models.py`.
6. Add to `AGENT_ALLOWED_TOOLS` and `CODING_TOOLS`.
7. Update `core/agent/loop.py`'s `_extract_tool_input` to parse
   `targets` array.
8. Update `agents/coding/tools.py` to include `DELEGATE_PARALLEL`.
9. Tests: `tests/tools/test_delegate_parallel.py` — verify 2-child
   and 5-child fan-out, depth cap, wall-clock cap, partial failure
   (one child errors, others succeed).
10. Docs: update `localmind.md` Agent Registry table to mention
    `delegate_parallel`.

---

### B2. Propose-stage tools (`propose_str_replace`, `propose_write_file`)

**Borrow from:** Codebuff `common/src/tools/params/tool/propose-str-replace.ts`
and `propose-write-file.ts`.

**Impact:** Without propose-stage tools, LocalMind cannot express
best-of-N editing — the model must commit to one edit, run it, observe
failure, and retry. With propose-stage tools, the model can stage
multiple candidate edits as proposals, then a selector picks the best,
and the parent applies it.

**Effort:** ~200 lines. Add `tools/propose_edit.py` and
`tools/propose_write.py` that:
- Take the same args as `edit_file` / `file_writer`.
- Stage the proposed edit in a per-run `proposed_edits: dict[str, str]`
  registry (path → proposed content).
- Return a `ToolResult` describing the staged edit (diff preview,
  affected file, no actual write).
- Do NOT touch disk.

Add a `apply_proposed_edit` tool that takes a `path` and writes the
staged content to disk (with the same HIGH-risk permission gating as
`file_writer`).

Wire into `AGENT_ALLOWED_TOOLS` and `CodingAgent`'s scoped toolset.

**Risk:** Medium. The proposed_edits registry needs to be per-run
(use `contextvars` like `_current_run_id`). Need to ensure staged
edits don't leak across runs. The apply step inherits all the
existing `file_writer` safety gates.

**Model-readiness:** The propose/select/apply pattern is most
valuable with strong models that can produce multiple high-quality
candidate edits. With `llama3.1:8b`, the candidates may all be
similar quality, reducing the value of selection. Still useful for
"stage then review before applying" workflows.

**Concrete steps:**
1. Create `tools/propose_edit.py` and `tools/propose_write.py`.
2. Add a per-run `proposed_edits` registry (use `contextvars`).
3. Register `Intent.PROPOSE_EDIT` and `Intent.PROPOSE_WRITE` in
   `core/models.py`.
4. Create `tools/apply_proposed.py` that takes a `path` and writes
   the staged content (with HIGH-risk permission gate).
5. Register `Intent.APPLY_PROPOSED`.
6. Add all three to `AGENT_ALLOWED_TOOLS` and `CODING_TOOLS`.
7. Update `core/agent/loop.py`'s `_extract_tool_input` and
   `TOOL_DEFINITIONS`.
8. Tests: `tests/tools/test_propose_edit.py` — verify staging,
   apply, discard (when run ends without apply), and isolation
   across runs.

---

### B3. Subgoal scratchpad tools (`add_subgoal`, `update_subgoal`, `create_plan`)

**Borrow from:** Codebuff `common/src/tools/params/tool/add-subgoal.ts`,
`update-subgoal.ts`, `create-plan.ts`.

**Impact:** Currently LocalMind agents have no structured way to track
sub-goals across iterations. The plan from the planning phase is
injected into the system prompt as text, but the model can't update
it mid-run. A subgoal scratchpad (per-agent, per-run) lets the model
decompose "build a hello world repo" into "create dir → write
hello.py → git init → git add → git commit" and check off each step.

**Effort:** ~150 lines. Add `core/subgoal.py` with a `Subgoal` dataclass
(`id`, `description`, `status`, `notes`). Add a per-run `subgoals: dict[str, Subgoal]`
registry (use `contextvars`). Add three tools: `add_subgoal`, `update_subgoal`,
`create_plan` (creates multiple subgoals at once from a markdown list).

**Risk:** Low. The scratchpad is per-run and doesn't touch disk.
The main risk is over-engineering — if the model doesn't use the
tools, they're dead code. Start with `CodingAgent` only.

**Model-readiness:** Small models may not use subgoals reliably.
`llama3.1:8b` may benefit; `gemma3:1b` probably won't. Make it
opt-in via the playbook — only CodingAgent's playbook mentions
subgoals initially.

**Concrete steps:**
1. Create `core/subgoal.py` with `Subgoal` dataclass and
   `SubgoalRegistry` class.
2. Create `tools/subgoal.py` with `add_subgoal`, `update_subgoal`,
   `create_plan` functions.
3. Register `Intent.ADD_SUBGOAL`, `Intent.UPDATE_SUBGOAL`,
   `Intent.CREATE_PLAN`.
4. Add to `AGENT_ALLOWED_TOOLS` and `CODING_TOOLS` only.
5. Update `agents/coding/playbook.md` to mention subgoal usage.
6. Tests: `tests/tools/test_subgoal.py` — verify add, update,
   list, complete, and per-run isolation.

---

### B4. Inline delegation (`delegate_inline`)

**Borrow from:** Codebuff `spawn_agent_inline`
(`spawn-agent-inline.ts:26-178`).

**Impact:** Enables the `context-pruner` pattern (A4 above can be
re-implemented as an inline agent that rewrites the parent's history).
Also enables any "transparent transformation" agent — context
compactor, history summarizer, tool-result simplifier.

**Effort:** ~200 lines. Add a `delegate_inline` tool that:
- Takes `target_agent` and `task` (same as `delegate`).
- Constructs the child agent.
- Runs the child with the **parent's** `messages` list (passed by
  reference, not copied).
- The child's `run()` method has access to a `mutate_parent_history(new_messages)`
  callback that replaces the parent's messages in-place.
- Returns a `ToolResult` indicating the parent's history was rewritten.

This is the riskiest Tier B item because it breaks the strict
isolation invariant. Add a `allow_inline_mutation: bool = False` flag
on `AgentConfig` — only agents that opt in (like a future
`ContextPrunerAgent`) can be spawned inline.

**Risk:** High. The child can corrupt the parent's transcript.
Mitigations: (a) only one agent (`ContextPrunerAgent`) is initially
allowed to be spawned inline; (b) the parent's pre-mutation history
is snapshot to disk for debugging; (c) the mutation is logged via
obs events.

**Model-readiness:** The inline agent itself can be a cloud model
(even if the parent is local) — this is a place where per-agent
model routing (Tier C) would help.

**Concrete steps:**
1. Define `InlineMutationCallback` type in `core/agent/delegation.py`.
2. Add `allow_inline_mutation: bool = False` to `AgentConfig`.
3. Create `tools/delegate_inline.py` modeled on `delegate.py` but
   passing the parent's messages by reference.
4. The child's `run()` method gets an optional `mutate_parent_history`
   callback in its `**kwargs`.
5. Register `Intent.DELEGATE_INLINE`.
6. Create `agents/context_pruner/` as the first inline-capable agent.
7. Tests: `tests/tools/test_delegate_inline.py` — verify mutation,
   snapshot, and the `allow_inline_mutation=False` rejection path.

---

## Tier C — Borrow When Cloud Routing Lands (High-Impact, Needs Per-Agent Models)

### C1. Per-agent model routing

**Borrow from:** Codebuff's per-agent `model: ModelName` field
(`agent-definition.ts:21-269`) and the `CODEBUFF_REVIEWER_BY_MODEL`
map (`base2.ts:47-51`).

**Impact:** Currently every LocalMind agent uses the same model
(`OLLAMA_MODEL` env var). A CodingAgent running on `llama3.1:8b` uses
the same model as the DirectAgent (which just needs to acknowledge
the user) and the BrowserAgent (which needs strong reasoning for
DOM interaction). Per-agent routing would let CodingAgent use a
stronger local model (`llama3.1:70b` if available) while DirectAgent
uses a smaller one (`qwen2.5:1.5b`), or route heavy reasoning to a
cloud model via the OpenAI-compat adapter while keeping the
orchestrator local.

**Effort:** ~300 lines. Extend `AgentConfig` with
`model: Optional[str] = None` and `adapter: Optional[str] = None`
(fields naming the model and adapter to use). In `BaseAgent.run()`,
if `config.model` is set, construct a fresh adapter for that model
(caching adapters per-model to avoid reconstruction). The `delegate`
tool already passes the parent's adapter; update it to use the
child's configured adapter if set.

Add a `ModelRouter` config in `core/config.py` that maps agent names
to (model, adapter) pairs. Read from `.env`:
```
LOCALMIND_AGENT_MODEL_CODING=llama3.1:70b
LOCALMIND_AGENT_MODEL_DIRECT=qwen2.5:1.5b
LOCALMIND_AGENT_MODEL_RESEARCH=zen:deepseek-v4-pro
LOCALMIND_AGENT_MODEL_BROWSER=zen:claude-3.5-sonnet
```

**Risk:** Medium. Adapter construction per-model adds startup cost
(cache mitigates). Mixing local and cloud adapters in one run means
some agent calls egress to the cloud — needs explicit user opt-in
via `.env` (don't default to cloud).

**Model-readiness:** This is what *enables* cloud-model features
(best-of-N, parallel delegation) on local-only setups. Without it,
Tier B items are limited to what local models can do.

**Concrete steps:**
1. Extend `AgentConfig` with `model` and `adapter` fields.
2. Add `ModelRouter.get_adapter_for_agent(agent_name) -> BaseAdapter`.
3. In `BaseAgent.run()`, use `ModelRouter` instead of `self._adapter`
   when `config.model` is set.
4. In `tools/delegate.py`, use the child's configured adapter instead
   of the parent's.
5. Document in `README.md` and `localmind.md`.
6. Tests: `tests/core/test_model_router.py` — verify per-agent adapter
   selection, fallback to default, .env override.

---

### C2. Best-of-N editor pattern

**Borrow from:** Codebuff `agents/editor/best-of-n/editor-multi-prompt.ts:58-246`.

**Impact:** Produce N candidate edits with different strategy prompts,
pick the best via a selector, apply the winner. This is the single
most impactful pattern for code editing quality — it converts "the
model's first guess" into "the best of N guesses."

**Depends on:** B1 (parallel delegation), B2 (propose-stage tools),
C1 (per-agent model routing — the editor children should be a strong
cloud model even if the orchestrator is local).

**Effort:** ~400 lines. Create `agents/editor/` as a new agent
(actually, extend `CodingAgent` with a `best_of_n_edit` tool, or
create a dedicated `EditorAgent`). The tool:
1. Takes `file_path`, `instruction`, `n=3` (number of candidates),
   `strategies: list[str]` (optional — defaults to
   `["conservative", "refactor", "minimal-diff"]`).
2. Spawns N `CodingAgent` children in parallel (via B1), each with a
   different strategy prompt and the `propose_*` tools (B2).
3. Each child returns a `propose_str_replace` result (staged edit,
   not applied).
4. Spawns one `EditorSelectorAgent` child with all N proposals as
   input.
5. The selector returns `{ implementationId, reason, suggestedImprovements }`.
6. The parent applies the winner's proposed edit via
   `apply_proposed_edit`.

**Risk:** High. The selector agent is itself an LLM call — if it
picks badly, you've spent N+1 model calls and gotten a worse result
than just running one editor. Mitigations: (a) start with N=2 and
increase as confidence grows; (b) log every selection for review;
(c) allow the user to override the selector's pick in the UI.

**Model-readiness:** Needs a strong selector model. With
`llama3.1:8b` as the selector, the picks may be unreliable. This is
a Tier C item specifically because it needs cloud-model support.

**Concrete steps:**
1. Wait for B1, B2, C1 to land.
2. Create `agents/editor/` with `agent.py`, `tools.py`, `playbook.md`.
3. Implement `best_of_n_edit` tool in `tools/best_of_n_edit.py`.
4. Create `agents/editor_selector/` for the selection agent.
5. Add to `AGENT_ALLOWED_TOOLS` and `CODING_TOOLS`.
6. Tests: `tests/agents/test_editor_best_of_n.py` — verify N=2 and
   N=3 paths, selector pick, apply, and the override path.
7. Add UI: "Best-of-N Editor" toggle in settings; "View all candidates"
   expandable section in chat.

---

### C3. Skills system (lightweight prompt injection)

**Borrow from:** Codebuff `sdk/src/skills/load-skills.ts:47-250` and
the `skill` tool (`common/src/tools/params/tool/skill.ts`).

**Impact:** Skills are markdown files with YAML frontmatter loaded
on-demand. No model binding, no tool registration — pure prompt
fragments the model can pull in when relevant. This is a much
lower-friction extension mechanism than full agent definitions.

LocalMind's current extension story is: write a new agent directory
with 5+ files, register in the registry, add tests. With skills,
a user can drop `backend/data/skills/python-testing/SKILL.md` and
the model can pull it in mid-conversation when the user asks about
Python testing.

**Effort:** ~150 lines. Create `core/skills.py` with a `SkillLoader`
that scans `backend/data/skills/*/SKILL.md` at startup. Add a `skill`
tool that takes `skill_name` and returns the skill's markdown content
as a tool result. The model sees it and incorporates it into its
next response.

**Risk:** Low. Skills are read-only and don't execute code. The main
risk is prompt injection from untrusted skill files — mitigate by
documenting that skills are trusted user content (same as
`AGENTS.md`).

**Model-readiness:** Works with all models. Small models may not
reliably call the `skill` tool — add a hint in the system prompt
when skills are available.

**Concrete steps:**
1. Create `core/skills.py` with `SkillLoader` and `Skill` dataclass.
2. Scan `backend/data/skills/*/SKILL.md` at startup.
3. Create `tools/skill.py` with `skill(skill_name: str) -> ToolResult`.
4. Register `Intent.SKILL`.
5. Add to `AGENT_ALLOWED_TOOLS` (all agents — skill is universal).
6. Create 2-3 example skills in `backend/data/skills/`.
7. Tests: `tests/core/test_skills.py` — verify loading, lookup,
   missing skill handling.

---

## Summary — Phased Adoption Roadmap

| Phase | Items | Why this order |
|---|---|---|
| **Phase 1 (now)** | A1, A2, A3, A4, A5 | All low-risk, work with current local models, no structural changes. A1 + A4 together meaningfully improve context handling. A2 + A5 add critical UX controls. A3 polishes the delegation UX. |
| **Phase 2 (after ADR-8 Phases 1-2)** | B1, B2, B3 | ADR-8 Phase 1 (agents as directories) and Phase 2 (wire `build_context()`) are prerequisites — they ensure the agent directory structure is stable enough to add new tools. B3 is the easiest (per-run scratchpad, no isolation concerns). B1 is the highest-impact (parallel delegation). B2 enables B2 → C2. |
| **Phase 3 (after per-agent models)** | C1, C2, C3 | C1 (per-agent model routing) is the prerequisite for C2 (best-of-N editor needs a strong selector model). C3 (skills) is independent and could ship in Phase 2 if desired — listed in Phase 3 because it's lower-impact than B1. |
| **Phase 4 (research, no commit)** | B4 (inline delegation) | Riskiest item. Wait until B1, B2, C1 are stable. Design the `ContextPrunerAgent` carefully — it's the only initial inline-capable agent. |

---

## What NOT to Borrow

For completeness, here are Codebuff ideas that LocalMind should
**not** adopt:

1. **XML-tag tool calling.** Codebuff uses this for provider-agnosticism
   (any model that can emit text can call tools). LocalMind already has
   native function calling via Ollama and OpenAI-compat adapters.
   Switching to XML would be a regression.

2. **Centralized backend routing.** Codebuff routes all traffic through
   `codebuff.com` for billing/attribution. LocalMind is local-first by
   design — adding a mandatory backend would break the core value prop.

3. **Agent Store.** Codebuff publishes agents to a store for reuse.
   LocalMind's scope is a single-user desktop app — agent sharing is
   lower priority than agent capability.

4. **`handleSteps` generator.** Codebuff's procedural agent definition
   is powerful but adds significant complexity (stringified functions,
   `eval`, no closure capture). LocalMind's playbook-md approach is
   simpler and works for the current agent lineup. Revisit if/when
   LocalMind needs procedural agents (e.g., a best-of-N editor that
   can't be expressed as a tool).

5. **`set_messages` / `add_message` tools.** Letting the model
   rewrite its own history is dangerous without strong guardrails.
   LocalMind's strict isolation model is a feature, not a bug. The
   `delegate_inline` (B4) is the controlled version of this — prefer
   it over giving the model direct history manipulation.

---

## Tracking

These recommendations should be filed as backlog items in
`.context/memory/tasks/backlog.md` (per the `.context` protocol —
append-only). Suggested slugs:

- `B-2026-08-02-1: bounded-output-buffer` (A1)
- `B-2026-08-02-2: abort-signal-threading` (A2)
- `B-2026-08-02-3: delegation-diagnosis-messages` (A3)
- `B-2026-08-02-4: context-compactor` (A4)
- `B-2026-08-02-5: steering-without-abort` (A5)
- `B-2026-08-02-6: parallel-delegation` (B1)
- `B-2026-08-02-7: propose-stage-tools` (B2)
- `B-2026-08-02-8: subgoal-scratchpad` (B3)
- `B-2026-08-02-9: inline-delegation` (B4)
- `B-2026-08-02-10: per-agent-model-routing` (C1)
- `B-2026-08-02-11: best-of-n-editor` (C2)
- `B-2026-08-02-12: skills-system` (C3)

Each backlog item should reference this recommendations file and the
corresponding `comparison.md` section for context.
