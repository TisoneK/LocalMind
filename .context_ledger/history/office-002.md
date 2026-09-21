# Office 002 — accomplishments record (permanent)

- Opened: 2026-09-12
- Closed: 2026-09-21
- Sessions: 28

The frozen office lives at history/office-002/ until it is zipped into
archive/office-002.tar.gz. This record stays in history/ forever — even after
the tarball is garbage-collected, the office is never forgotten. Not read at
session start; deliberate lookback only.

## Accomplished

- **The thinking infrastructure (ADR-62 build order), which this office
  treated as its spine.** The owner's roadmap from his own v0.5 transcript
  ("the architecture is the product; the skills are just content") turned into
  shipped capability: a typed, keyed, verified **memory write path** (ADR-63 —
  volatile content refused with the reason in plain words, `canonical_key`
  identity so a restatement replaces one row, every mutation confirmed from a
  read-back, deletion by id/prefix/re-worded content/key), deterministic
  read/delete routing so a memory question reaches the store instead of being
  improvised from conversation context, a **deduction engine** (ADR-65 — trust
  tiers, not votes: OS geo setting > IANA zone > locale tag > keyboards,
  asserted on every answering surface and persisted once through the keyed
  path), and **passive context awareness** (ADR-66a — a deterministic keyed
  extractor for durable self-facts, visible only on an actual write). Live
  before/after on real providers throughout, e.g. "I cannot determine your
  country" → "Your country is Kenya (KE)", 0 tools.
- **The reflection loop** (ADR-64): a post-turn self-critique now asks for one
  extra structured field and stores the *pattern* behind a failure as an atomic
  lesson (`memory_kind="lesson"`), surfaced to the user as a lightbulb badge
  rather than silently learned. Its shipping session also found the step had
  been dead for every parent-loop turn since an earlier refactor
  (`REFLECT_INTENTS` no longer matched the parent's `Intent.ANALYZE`) — fixed.
- **The loop's own contract, fixed at the root rather than per symptom.** The
  blocking pre-tool Thinker consult was deleted: the consult now launches when
  the loop learns a tool call was actually requested, so a zero-tool turn costs
  zero consults ("Hi, how are you?" before/after: thinker events 2 → 0, one
  iteration, ~1.2 s). Structured stage cards for the recovery/continue stages,
  prompt input SELECTION by stage (-38% system prompt on later calls),
  tool-result stubbing budget-gated (final answers 5/15 → 14/15), a root cause
  for "empty response after reasoning" (a whitespace-only content delta made
  the adapter drop the tool call), post-answer services sharing one 90 s budget,
  and `done` moved before those services so the UI stops "working" after the
  answer is visibly finished.
- **The turn bus** (ADR-66b): the processes for one goal now communicate
  through an in-process append-only fact log with provenance, freshness by plan
  generation, lanes, and one bounded `gate()` — the Thinker migrated onto it (a
  late analysis of a replaced plan is dropped), and its first verdict lane is
  the **completion judge**, which replaced a phrase-list detector that the
  model's next wording defeated within hours: the model judges whether its own
  short reply finished the request, publishing a goal-version-stamped verdict
  the final-answer gate reads.
- **Provider resilience and honest tool contracts.** A failover layer around
  every adapter (ADR-69 — retry after the window the provider named, then
  `fallback_to`, then any enabled provider with a key; process-wide health
  memory; recovery announced as plain status lines; `web_fetch` applying the
  same rule to refusing hosts), tools that refuse only on facts they verified
  and name the flag that confirms them (ADR-67), plans that are the model's own
  or emerge from real actions with step status from real tool outcomes (ADR-68),
  and commands/installs as user settings (ADR-70 — `<home>/packages` by
  default, shell choice in Settings).
- **The AI Connections layer:** settings.json became the source of truth for
  providers — preset seeds plus user-defined OpenAI-compatible endpoints, a
  live four-check probe (reachability/auth/streaming/tools) that learns
  capabilities back onto the record, and UI that makes a custom endpoint behave
  like a built-in provider everywhere. Verified live against a real local
  Ollama endpoint, not a mock.
- **The state-driven engine (ADR-71), the office's last and live thread.** A
  separate package (`core/state_engine/`, importing no parent-loop code) where
  the ENGINE owns the state: immutable states rebuilt from real observations,
  compact rendering with no chat history, fingerprints so a failed move is
  never re-proposed, candidate moves and outcome scoring as the model's only
  two jobs, simulation as real read-only probing, beam-of-one with backtracking
  (pruning the move that led into the dead end), a hard budget with an honest
  `stopped` that says the goal is NOT settled, and read-only by construction —
  an unmarked tool surfaces as `needs_confirmation` instead of running. Live on
  deepseek-chat: a folder question in 2 model calls, a README/stack goal in 4.
  Then the **State Explorer**: the backend serves a game-tree page at
  `GET /state-explorer` and streams a run as SSE from
  `POST /api/state-engine/run` (a `meta` event, then every `EngineEvent`;
  disconnect cancels), with no build step so it also runs on Windows. The
  in-app React port and the Classic/State engine selector were in flight,
  uncommitted in the working tree, when this office closed.
- **The agentic UI pass:** one live turn group replacing four competing
  blocks, an ActivityRail (Now/Tasks/Agents/Files), the Actions tab removed, a
  rebuilt Files tab, tool results as terminal/JSON/search cards with truncation
  turned into one honest note, provider-limit failover shown transparently,
  Retry/Edit/Undo, a command palette, Settings as pages behind a left nav, and
  per-phase thinking.
- **Housekeeping that keeps the rest honest:** the tree-wide
  `.context_ledger`-vocabulary strip of the product runtime surface (hand
  -stripped, per-line, ~2,650 citation lines, tests/docs remainder carried), a
  verified dead-code scan (6 orphan models + 3 dead parameters removed, 3
  live-looking bugs filed rather than guessed at), cross-platform path and
  cwd-truth fixes (session cwd respected by git/process/sysinfo, `~` display
  for a real Windows home), and the office's own protocol upkeep — core 1.2.0
  → 2.0.3 including the MAJOR office/token-optimization migration, the
  `STATE.md` digest, playbook extraction, the resource-leak and closeout rules,
  and this close.

## Decisions still in force

The full text of every ADR lives in `history/office-002/plans/decisions.md`
(ADR-1 through ADR-61 carried in from office-001; ADR-62 through ADR-71 written
here, including two distinct decisions numbered ADR-66 — the passive-context
one and the turn-bus one). The binding set for the next office:

- **Do-NOT-regress guardrails (verbatim from `memory/workflows/active.md`):**
  the ADR-34 event order; the `Hi`→zero-provider-call boundary; the
  thinking-aware-timeout fixes it builds on; the ADR-40 guardrail (live-verify
  tool SELECTION on a flash-tier model + cerebras before any further schema
  cut); ADR-41 (z.ai thinking ON — never re-add a thinking-disable for GLM;
  timeout scaling is the lever); the provider-stall watchdog fall-through (once
  a first byte lands the heartbeat returns to the truthful prior branches —
  never stall-shame a healthy stream); the Parent-only scope.
- **Thinking infrastructure:** ADR-62 (build order Perception → Deduction →
  Self-check → Reflection → Planning; skills last; its anti-pattern list is
  do-not-regress guidance); ADR-63 (durability decided in the write path, keyed
  identity, read-back confirmations); ADR-64 (autonomous memory writes are
  VISIBLE — a dedicated SSE event plus UI, the event fires only on a confirmed
  write, and what is stored is the pattern, not the instance); ADR-65 (trust
  tiers, collectors never raise, assert the conclusion on every answering
  surface); ADR-66a (passive writes deterministic, subject-hinted, keyed,
  visible only on actual writes).
- **Loop and bus:** ADR-66b (turn bus: facts appended never edited, freshness
  decided at read time, lanes, one bounded gate; a silent mutation must be a
  named exception; a per-provider concurrency budget before widening parallel
  lanes); ADR-57/60 (consults are never awaited at turn end; never reintroduce
  serial every-tool consults); ADR-59 (no machinery prose in Thinker output);
  ADR-61 (never gate loop optimizations on the `intent` parameter — it is
  constant on the parent path); ADR-18 verification-first, now applied to the
  memory store as well as to files.
- **Tool and provider contracts:** ADR-67 (refuse only on a fact the tool
  verified itself, name the fact and the confirming flag; verification reads the
  world directly — stat, not a tool that can fail for unrelated reasons);
  ADR-68 (no canned plans; a step ticks from its tool's real outcome; a failed
  step stays failed and persists); ADR-69 (failover absorbs provider limits —
  silent to the user, announced and bounded; a local model never silently falls
  back to cloud); ADR-70 (where commands run and where installs land are user
  settings, never assumptions).
- **The state engine:** ADR-71 (built BESIDE the classic parent, importing only
  stable capabilities — model adapters, tool dispatcher, `ToolResult`; the
  engine owns the state; the model only proposes moves and scores outcomes;
  simulation is real read-only probing; a hard budget with an honest stop;
  read-only by construction in slice 1; every step an `EngineEvent`; engine and
  model are independent axes — `Auto` deliberately not built first).
- **Working agreements:** the live-testing bar is MANDATORY for loop/tool/
  adapter changes (`system/live-testing.md`; report live-verified vs
  unit-tested vs assumed); cure the disease, not single prompts; model-agnostic
  and env-agnostic fixes — "there is no weak model" (neutral terms only); a
  defect whose trigger is "the model worded X differently" gets a semantic or
  state check, never a wording list; push to main after each commit;
  two-surface commit prefixes, never mixed; never mix a peer's uncommitted work
  into your commit (explicit `git add` paths only); roster check-in every
  session; never port 8000 (the owner's app runs there) — isolated 8765 +
  `LOCALMIND_HOME` only; no secrets in tracked files, ever; closeout clears its
  own residue and leaves `git status` clean. The permanent summary of
  office-001: `history/office-001.md`.

## Open threads

**Re-seeded into the new office's backlog (actionable, with an owner or a clear
next step):** the exit gate's frontend eslint budget (the extra React-effect
warnings from the recent UI work push `eslint . --max-warnings 53` red, so the
canonical exit gate has failed for every session since — fix the warnings or
consciously raise the budget, and do not let a red gate be normalized); the
state-engine program's next slices (write-capable moves behind the ADR-67
confirmation with predicted-then-verified outcomes, beam > 1, persisted state
so a turn can resume, tree visualization fed by `EngineEvent`s, and a
per-provider concurrency budget before parallel probes); the confirmable-refusal
rollout to delete/shell/installs; turn-bus follow-ons (post-turn services as
lanes, silent read-only grounding lanes, a Decider lane, parallel read-only
tool lanes); failover follow-ups (per-provider concurrency budget, health in
the Providers page, failed-source memory for browse/web_research); pre-action
recall; multi-step planning wiring; learning transfer; skill-gap detection;
anti-sycophancy; the memory edit path's vector-index tolerance; the unpromoted
junk rows from the bare-operation bug; and the Windows-portability cluster with
the pytest-baseline refresh that has blocked a clean exit gate on Windows for
weeks.

**The owner's standing target (`memory/workflows/active.md`) is NOT done and
stays in force:** the ZCode-import resilience program — MCP client support, a
read-only Explorer subagent as a Parent TOOL, a fresh-eyes acceptance judge,
and plugin-style skill packaging. It yields to the owner's live chat-message
targets whenever one arrives, and the state engine now shares that queue.

**Parking-lot knowledge (63 rows, frozen verbatim at
`history/office-002/tasks/parking-lot.md`; the fresh office starts with an
empty lot):** the durable findings are (a) latency levers still unshipped —
folding classify + first action, the create→`file_write` steering family and
routing "create a file" to FILE_WRITE, prompt diet/input trims, and the uniform
bounded observation contract; (b) open owner questions — boot-time geolocation
default, confidence-calibration surfacing, whether the planner needs a
spec-kit, keyring-encrypted API keys (deferred by the owner until the VS Code
403 closes), the grep_search expose-vs-retire call, and the Experiential Labs
provider (reverted for timing only — re-apply by reverting the revert);
(c) architectural long-termers — Direct Mode removal, Thinker right-sizing,
ParentSession compaction tuning, monolith decomposition, the non-coding
capability roadmap, and ~280 unverified dead-code hits; (d) test health — the
~23-failure Windows baseline, the flaky process-tool and acceptance-gate
families, and the residue e2e runs leave in the real chat store. Promote a row
by giving it an owner and a next step; do not copy the list.

**Windows is the owner's machine and remains the least-verified surface:** the
State Explorer and the live SSE route were verified on macOS only, ADR-70's
Windows paths by simulation only, and several backend tests fail on a Mac
unless `LOCALMIND_SHELL_ENABLED=true` (a real environment-shaped failure worth
fixing on its own merits). Anything said to work "on Windows" without a Windows
run is a guess.

**Protocol asks re-seeded into the new office's flaws log:** the gates' `sh`
commands have no teeth on a bare Windows PATH (a red step can pass silently); a
pathless `git commit` while a peer's files are staged sweeps them into the
wrong commit (the reason the explicit-adds rule exists); a collab `claim` event
silently accepted a truncated paths list; and the deferral-to-claimant pattern
has no fallback when the claimant clocks out without clearing the deferred item.

**Carried forward as a hazard, not a task:** this office was closed eight
sessions past `office_size` because every session from the twenty-first onward
read the due-close notice and worked anyway. A session that ignores the door
trigger believes a stale board; the close is cheap, the confusion is not.
