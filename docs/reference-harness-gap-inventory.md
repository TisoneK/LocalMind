# Harness guarantee inventory — the reference standard vs. LocalMind

**Status:** Draft for owner review · 2026-10-27 · Amani (S006) part 6 — **re-identified same day** per the owner's terms ruling: the first draft carried the studied harness's own vocabulary; every guarantee below is restated as an outcome in LocalMind's own words.
**The reference standard:** a public agent harness, studied read-only at commit `22ddee37` — [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness), cloned at `../research/deepseek-harness`. This line is the inventory's only mention of it: the repo is public and the building agent can clone it for specifics; nothing from its vocabulary — term names, quotes, codes, labels — is imported into this document or into LocalMind.
**LocalMind side:** this repo @ `6079dc50` (docs + module surface + test names as guarantee evidence) plus one piece of ground truth: the **2026-10-27 12:45 weather-session export** ("Capability inquiry", glm-4.5-flash via zai / BankOfAI promo route).
**Rules honored:** every row states *outcomes the user can rely on*, not implementation; where LocalMind already does the job differently **on purpose**, the row is marked `original`, never scored as a gap.

## How to read the table

| Gap label | Meaning |
|---|---|
| **missing** | LocalMind has no mechanism delivering this guarantee at all |
| **partial** | A mechanism exists, but the guarantee is not airtight / not surfaced / not tested as a contract |
| **equivalent** | LocalMind delivers the same guarantee through its own design |
| **original** | LocalMind's approach is its own; comparing it to the reference would be a category error — recorded so it is not "fixed" into a clone |

**Caveat on the weather run:** that instance predates two fixes now on main — native-thinker streaming (`045199d`) and evidence grounding (`c118898`, plus full-evidence `b7f7985`). Rows affected are marked **(fixed on main after the run)**. The run is still the best end-to-end proof of what the *shipped* user experience looks like when a gap and a provider outage meet.

**Turn** and **step** are LocalMind's own reading contract (`sessionReading.ts`, since `c607ed60`): a **turn** is the user's request through the assistant's finished reply; a **step** is one model request plus the tool calls it caused.

---

## A. Context injection per turn

| Reference standard guarantees | LocalMind today | Gap |
|---|---|---|
| Everything entering context beyond the typed message is a durable, **individually labeled item with a declared form** — two dozen distinct, self-describing item types observed in real recordings (what each item is, where it came from). Injection is append-only and change-detected: unchanged facts are never re-sent; a changed fact arrives as a new snapshot that **explicitly retires** the old one, and retirement is itself a logged, visible message. Project instruction files load once as a baseline with per-file fingerprints and announce their own updates when they change. Time is injected **with its timezone**, and mixed or missing zones instruct the model to *clarify rather than guess*. | Injections exist and are gated — `injected_context_gate.py`, `user_context.py`, `session_context.py`, todo-state injection, staged system prompt with prompt budgets and a byte-stability test — but they are **assembled silently**: no typed sources, no per-item digests, no retirement notices, no change detection. And the identity facts are simply not guaranteed present: in the 12:45 run "where I am" had to be inferred from web-search results. The model guessed Kenya — and happened to be right. That was luck wearing a guarantee's clothes. | **partial** — the machinery exists; the two sharpest missing guarantees are identity facts (who/where/when) and per-item provenance |

## B. Provenance & audit symmetry

| Reference standard guarantees | LocalMind today | Gap |
|---|---|---|
| What the UI shows and what the model actually received are **provably the same data** — stated as an architecture invariant: anything the model can see must be reconstructable from the durable log. Every injected item is inspectable down to its raw bytes with its producer attributed; unrecognized item types still render, labeled opaque, rather than being hidden; the trajectory view is a pure projection of the same log, so the UI can neither show context that was never sent nor hide context that was. | The chat export records a real audit skeleton per run — `agentRuns` with phases, per-tool status/duration, evidence sizes, failed-tool flags. Genuinely good bones. But there is **no invariant** tying what the UI shows to what the model received; injected prompt material is not inspectable per item; and the thinking surfaced in the export was authored prose merged with native reasoning, so the record literally contained text the model never natively reasoned **(fixed on main after the run: `045199d`)**. | **partial** |

## C. The system prompt corpus

| Reference standard guarantees | LocalMind today | Gap |
|---|---|---|
| The prompt is **composed, not hardcoded**: a fixed identity line, then ordered principle sections owned by the tools themselves — the shell tool teaches exit-code checking, the web tools teach untrusted-data discipline, the goal tool teaches done-ness; each discipline lives with the tool that needs it. The fully rendered prompt is **snapshot-tested as a regression artifact** (a recorded 619-line expected prompt) and travels as replayable history. | `base.md` is a genuine principles corpus of its own — honest signals ("I'm not sure" over a confident wrong answer), ambiguity defaults ("state your interpretation and proceed"), memory-woven behavior ("you don't say 'As per your preference for Python…' — you just use Python"), tool honesty ("Never fake a tool result"), recovery discipline ("read the error message before retrying… don't retry the same thing harder") — and it is staged per intent with a byte-stability test. What it lacks: per-tool discipline living **with** the tools (LocalMind's tool guidance is centralized in stage files), and snapshot-tested rendered prompts per profile. | **equivalent in spirit, partial in mechanics** — and the staged-intent architecture is LocalMind's own (see §S) |

## D. Compaction & oversized output

| Reference standard guarantees | LocalMind today | Gap |
|---|---|---|
| Nothing is ever destroyed. Compaction *shadows* full-fidelity records behind summaries with exact token accounting, so totals stay true; it is bracketed by a log-recorded lock, so a crash mid-compaction is a **detectable orphaned lock**, never a falsely-claimed success. Oversized tool results **spill to disk verbatim** with a locator plus retrieval guidance, and a spill failure keeps the original inline result — a successful tool call is never turned into an error by storage. | `context_compactor.py` + `summarizer.py` + `smart_truncate` + tool-result budgets, and the tool-result index stores chunks so stubbed results are recoverable into a bounded full-text view (the Task-10 fix, `b7f7985`). Real machinery with tests. But there is no spill fidelity contract, no shadowed-record accounting, and truncation paths are destructive — bytes gone, not shadowed. | **partial** |

## E. Completion rules / definition of done

| Reference standard guarantees | LocalMind today | Gap |
|---|---|---|
| A turn closes only when **nothing is owed**. A step that fails mid-flight never leaves an unpaired tool call — an unknown-outcome placeholder is recorded so later history stays usable without blindly retrying an operation whose effect is uncertain. A plugin's failure ends the turn, not the loop. Goal rounds are durable and counted: "complete" requires actual achievement, and "blocked" requires the *same concrete blocker* on ≥3 consecutive rounds, reported — "difficulty, uncertainty, or useful remaining work is not blocked." | Strong here, partly original: the turn-outcome contract, the acceptance gate with evidence grounding (`c118898`), the completion judge, follow-through/punt detector, pending-action detector, parent completion floor, honest todo finalize, divergent-stop-uses-the-contract, goal rounds — all under test. The 12:45 run died of the *opposite* failure: not a premature stop but a provider death **after the answer was already in evidence** — and nothing in the done-rules covers "deliver what the evidence already supports, or say so, when the provider dies mid-synthesis." | **equivalent-to-stronger on premature stops; missing the provider-death-at-synthesis case** |

## F. Reasoning channel

| Reference standard guarantees | LocalMind today | Gap |
|---|---|---|
| The model's own streamed reasoning is first-class content — a distinct block type, kept **out of the answer channel**, preserved per step, replayable and auditable forever; even a cancelled stream preserves the delivered prefix as an anchor. | On main since `045199d`: the thinker streams **only** the native channel verbatim, the answer channel is buffered and never shown, and no-reasoning providers get honest silence. Same guarantee, independently designed. The 12:45 instance predated it and surfaced authored planner-prose, loops, and truncation artifacts in the thinking panel. | **equivalent** (fixed on main after the run) |

## G. Trajectory & turn-audit UI

| Reference standard guarantees | LocalMind today | Gap |
|---|---|---|
| The trajectory view is a **pure projection of the durable log**: a turn-aware ledger plus a per-record inspector (token usage, duration, time-to-first-token, raw input/output), with failed and retried attempts **retained and visible** — retry counts and the last attempt's error survive recovery. Numbers are honest: unavailable metrics render as unavailable; in-flight rows never invent elapsed time. | Turn timeline, phase cards, StateExplorer / Inspector / RunCompare, PerformanceMetrics, per-tool output panels, and the export's `agentRuns`/`phases`/`evidence` records. Not log-projection architecture, and honesty leaks: the activity meter showed **2/3 · 67% on a run that had failed**; there is no raw/source view for context items; failed/retried attempts are not a first-class ledger. | **partial** |

## H. Permissions & sandbox

| Reference standard guarantees | LocalMind today | Gap |
|---|---|---|
| Exactly three named file-effect modes, from fully read-only through workspace-scoped writes (the shipped default) up to full access; surfaced as one selector, pinned per session, surviving restart by replay, never crossing sessions. Approvals **fail closed** — any missing or throwing answerer collapses to "unavailable", never open; an approval grants exactly the asked-about call and nothing more; every ask and every decision is audit-logged, invisible to the model. | A permission *conscience* without a permission *surface*: safety gates (`safety_gate.py`, memory safety gate), a propose→apply write flow, intent-scoped tools, a code-exec sandbox. No user-visible modes, no session pinning, no approval audit events. | **partial** — the propose-apply flow is original and worth keeping as the kernel of a mode system |

## I. Provider & failure handling

| Reference standard guarantees | LocalMind today | Gap |
|---|---|---|
| Provider failures arrive as **stable, named codes** consumers can route on — never on message text. The billing split is honest: one code is reserved for the signed-in first-party account's own balance, so a top-up prompt **never** appears for a third-party failure, and payment is never silently assumed. Retryability is classified (a small, fixed set of codes retries, bounded times, made durable before waiting, inside the still-open turn); credential failures name the credential reference, never any part of the key. No automatic cross-provider fallback — the named code surfaces. | `failover.py` + tests (cross-provider failover **exists** — the reference deliberately doesn't have it), `error_normalizer.py`, provider-health UI. But the observed 12:45 behavior failed the honesty bar: `payment_required` (balance=0, retryable=false — both known at error time) surfaced as *"The model ran into an issue. Please try again, or switch to a larger model."* "Try again" was known-dead; a larger model cannot fix a balance; the provider rendered as "unknown". The machinery is ahead of the reference in one spot and behind it where it mattered that day. | **partial** — failover + taxonomy exist; surfacing lied by vagueness |

## J. Session durability & lifecycle

| Reference standard guarantees | LocalMind today | Gap |
|---|---|---|
| A session is an **append-only, replayable event log** of immutable, checksummed, compressed generation files — never renamed, replaced, or deleted; torn tails from interrupted writes are repaired on open. Three durability barriers: the model request is durable *before* the stream starts, a **tool call is durable before its body can cause external effects**, each step flushes before the next request — a crash after that yields resumable state, and an interrupted tool call recovers as unknown-outcome, never silently re-executed. Format migrations are frozen and adjacent, proven by shipped restart recordings across three format generations. | SQLite-backed sessions with guaranteed-persist tests, per-session todos/goals, session history reload and export. Not an append-only event log; crash-during-tool semantics are undocumented; no checksummed generations. | **partial** |

## K. Workspaces

| Reference standard guarantees | LocalMind today | Gap |
|---|---|---|
| A durable registry of named projects grouping sessions by directory; a session's working directory is **immutable and is the write boundary**; removing a project never deletes the folder or the history; hidden sessions remain as findable ungrouped history. | Session/agent workspace modules and a workspace UI exist; no stated boundary or never-delete guarantees. | **partial** |

## L. Skills

| Reference standard guarantees | LocalMind today | Gap |
|---|---|---|
| A durable, sorted skill catalog per session; full instructions load **on demand** (progressive disclosure); different sources produce the identical format once delivered to the model; the catalog itself is delivered as a logged, inspectable message. | Intent-staged skill files (`prompts/skills/*`) with a registry and tests — skill guidance arrives **scoped to the classified intent** via the staged-prompt mechanism rather than via catalog + loader. No user-facing catalog surface. | **equivalent in kind, different by design** |

## M. Subagents / delegation

| Reference standard guarantees | LocalMind today | Gap |
|---|---|---|
| Delegation visible at any depth, children remain discoverable running or stored; bounded concurrency via a shared pool; every child's context carries a fixed delegation statement — its permission scope cannot be widened from inside its own session, and approval-requiring operations auto-reject; several interchangeable backends (in-process and external) behind one interface; results return as terminal events; stopping a session cancels descendants one by one. | `delegate` / `delegate_parallel` / `delegate_inline` + orchestrator + scoped tools + output-visibility tests — real multi-agent plumbing with its own phase-based delegation tests. No fixed-scope statement, no approval integration, no bounded pool. | **partial** |

## N. Model selection

| Reference standard guarantees | LocalMind today | Gap |
|---|---|---|
| A running step **keeps the model/effort it started with** across retries (selection is snapshotted per step); fresh agents get the deployment default; account routes gate models explicitly. | ModelSelector + model router + context-window discovery + reasoning-effort clamp + per-adapter thinking policies — a comparable surface; per-step pinning is not documented as a guarantee. | **partial** (surface equivalent; pinning guarantee unstated) |

## O. Plugins / extensibility

| Reference standard guarantees | LocalMind today | Gap |
|---|---|---|
| Every part of the product is a plugin — including the model adapter, the tool registry, the session log, and the agent loop itself — so each is replaceable from configuration. Registrations are reversible effects; the booted plugin tree is printable; installs are inspected before they happen, version-pinned, and rolled back on failure — with the honest caveat that host plugin code runs unsandboxed in-process. | No plugin architecture. The extension surface is the tools registry + skills + package-env choice. | **missing** (a deliberate roadmap decision to make, not an accident) |

## P. Automation tasks

| Reference standard guarantees | LocalMind today | Gap |
|---|---|---|
| Scheduled reminders **survive host restart** — the host wakes a cold session to deliver them as ordinary follow-up messages in the original conversation; recurring catch-up delivers only the latest missed occurrence; receipts + bounded history are inspectable; sessions with active reminders refuse to archive; and the limits are stated honestly (receipts acknowledge delivery, not execution). | Nothing. | **missing** |

## Q. Deliverables — "what did this turn change"

| Reference standard guarantees | LocalMind today | Gap |
|---|---|---|
| A turn's file-effects are recorded as durable events: declared deliverables plus per-turn snapshot diffs with per-file line counts, served as on-demand comparisons. | Per-file diff blocks in chat, file undo, file-diff emission tests — close in spirit, not a turn-scoped recorder. | **partial** |

## R. Small guarantees

| Reference standard guarantees | LocalMind today | Gap |
|---|---|---|
| Credentials are named in config, never embedded; values live in private on-machine storage; rotation applies from the next request; error names never leak key material. User feedback ratings never reach the model. Attachments are saved, survive restarts, and are re-sent in later turns — with on-screen masking that is honestly screen-only. | The `.context_ledger/memory/secrets/` pattern (self-gitignored, 0600 protocol, never-echo standing rules, rotation practice) — comparable for agent-operators. No feedback channel; attachments partial; no install identity. | **partial** |

---

## S. Where LocalMind is original — recorded so nobody "fixes" it

These are not gaps. They are the reasons LocalMind will not become a copy of the reference.

1. **The ledger office protocol** (`.context_ledger/`): a multi-agent roster, append-only session records, review reports, a parking lot, an office-close trigger, and a **vendored, versioned protocol core** that travels between repos. The reference ships plain project-instruction file pointers; nothing in it makes agent collaboration across sessions and repos a first-class product.
2. **Three-tier semantic intent classification** (embeddings → rules → LLM fallback) driving **staged, intent-scoped prompts**. The reference composes one prompt from ordered sections for everyone; LocalMind scopes the prompt to the classified intent. Different bet, keep it.
3. **The memory flywheel**: episode memory, failure memory, reflection lessons, the knowledge writer, memory distillation — memory woven into behavior per `base.md`, not a searchable archive.
4. **Value scoring for tool selection** and the decision ledger — LocalMind reasons about *which* tool is worth calling; the reference hands the model a toolset and discipline lines.
5. **The recovery-hint contract**. In the 12:45 run, accuweather's 403 produced an actionable hint — "try the NEXT URL from the list. If none of the URLs work, synthesize from the snippets you already have, or say so honestly. Do not invent an answer." — and the model **obeyed it** and fetched the real answer from MSN. That contract worked. It was the provider layer that failed afterwards. Keep this pattern; generalize it (§T-1).
6. **State engine + StateExplorer/RunCompare** as first-class UI surfaces.
7. **The Thinker's history as a design lesson** now embodied in the native channel (`045199d`) — reasoning is the model's own, or it is nothing.

---

## T. The 12:45 weather run as a failure trace

One run; every observed failure maps to a row above. This is the ground truth the roadmap is ordered against.

| # | Observed | Root gap |
|---|---|---|
| F1 | "Where I am" was unanswerable from context; the country came from web-search inference (correct by luck) | **A** — no identity/place/time injection |
| F2 | Thinking panel showed authored planner-prose, loops, truncation artifacts | **F** — pre-`045199d` instance; fixed on main |
| F3 | The answer **existed in evidence** (MSN: 25°C, partly sunny, wind 11 km/h, humidity 40%) and never reached the user: the provider died at synthesis and the run was marked failed | **E + I** — no provider-death path; the harness's own recovery contract ("synthesize from the snippets you already have, or say so honestly") was violated by the harness, not the model |
| F4 | Error guidance was misleading: "try again, or switch to a larger model" for a balance=0, retryable=false failure; provider shown as "unknown" | **I** — named codes exist internally; the surface lied by vagueness |
| F5 | Activity meter showed 2/3 · 67% on a failed run; todos were synthesized but no honest outcome state was shown | **G + E** — meter is not tied to outcome truth |
| F6 | **The win**: a 403 produced a recovery hint → next URL → real data | **S-5** — LocalMind's own pattern; generalize it |

## U. Gap ordering — the roadmap input

Ordered by how many observed failures each gap causes, weighted by breadth. **Merge step for the owner:** overlay the 10-task scorecard — the scorecard answers "does LocalMind work end-to-end"; this table answers "what to build first." A gap that fails many scorecard tasks rises.

1. **Provider-failure honesty & the provider-death path** (fixes F3 + F4; row **I + E**). Named error codes surfaced verbatim; retryability honored in the UX (never suggest "try again" when `retryable=false`); failover to a healthy provider *before* dying; and — the new rule — **when synthesis dies with evidence in hand, the harness delivers what the evidence supports or says so honestly, exactly as the tool-recovery contract already demands.** This is the only failure class that turned a *completed* evidence-gathering run into nothing.
2. **Identity context injection** (fixes F1 at the root; row **A**). Timezone, place (as the user stated it), and user identity as guaranteed injected items with the provenance treatment of row B — "the model is told who and where the user is before it acts."
3. **Provenance & audit symmetry** (fixes F5; rows **B + G**). Typed injected items with sources; a trajectory that projects the actual record; meters tied to outcome truth; failed attempts visible as attempts.
4. **Done-rules extension** (row **E**). Synthetic results for unanswered calls; the provider-death completion path from item 1 stated as part of the contract, not a rescue hack.
5. **Next tier:** session durability barriers (**J**), a permission-mode surface grown from the propose-apply flow (**H**), a spill/shadow fidelity contract (**D**).
6. **Deliberate decisions, not accidents:** plugins (**O**) and automation (**P**) — choose scope before code.

## Appendix — method & sources

- The reference standard was studied read-only at `22ddee37` via two inventory passes (shared host worklog Tasks **17-a** context/conversation layer, **17-b** operations surface), each returning outcome-level guarantees with evidence pointers. Primary evidence there: its architecture document (the reconstructability invariant), its recorded system-prompt snapshots, its per-item context injection and instruction-file loading, its permission presets and approval audit, its provider error taxonomy and retryability classes, its session durability and restart recordings, its scheduler, and its shipped trajectory projections — all findable in the clone at `../research/deepseek-harness` (commit `22ddee37`). Specifics are looked up there on demand, never pasted here.
- LocalMind evidence: repo @ `6079dc50` (module + test surface named inline), `docs/SEMANTIC_CLASSIFICATION.md`, `backend/src/core/prompts/base.md`, and the owner-provided 12:45 chat export (`localmind-chats-1-2026-10-27.json`).
- Companion reading: `docs/prior-art-codebuff-freebuff-architecture.md` (same slot for a different system); the 10-task scorecard (owner's; to be merged into §U).
- **Provenance:** the first draft (2026-10-27, `a4d9dd6d`) stated the reference side in the reference's own vocabulary — term names, verbatim quotes, error codes, UI labels, and its shorthand in the filename — and was re-identified the same day per the owner's terms ruling: outcomes restated in LocalMind's words, judgment per line, file renamed, repo cited once at the top.
