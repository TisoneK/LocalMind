# Backlog (live queue)

Open items for future sessions only. Append at the bottom; never reorder.
When an item is done, DELETE its line — the completion record is the
session entry in `agents/sessions.md` plus the commit itself, never a
tombstone here (core 0.21.0 live-queue rule; git history preserves removed
lines). Partially-done work carries `- [~]`. A checked-off `- [x]` line a
session left behind is a finished tombstone — sweep it with
`ledger-mem closeout` (dry run by default; `--confirm` deletes).

---

- [ ] **[Medium] Anthropic streaming fix needs live verification** (added 2026-07-11 by Super Z) — The Anthropic streaming format fix (`_chat_anthropic` now parses `content_block_delta`/`message_stop`/`message_delta` events) was based on Anthropic's SSE spec documentation, not runtime testing — no Anthropic API key was available. Next session with an Anthropic key: switch to the Anthropic adapter, send a streaming chat message, and verify tokens appear. File: `backend/src/adapters/openai_compat.py:1166-1231`.

---

- [~] **[Long-term] Decompose monolith files** (added 2026-07-11 by Super Z; **partial — Session 129, commits `5e47a6a` + `c24e5ab`**) — `backend/src/core/engine/_pipeline.py` (2269 lines) and `backend/src/core/agent/loop.py` (2926 lines) are approaching unmaintainable size. Candidates for further decomposition into smaller modules. Low priority — well-documented and working, but future feature work will be harder. — **Done (helpers): Session 129 extracted all pure text/routing/clock helpers, behavior-preserving, backward-compat re-exports — `core/agent/text_tools.py` (plan parse, MiniMax+DSML interception, tool-talk, truncate, tool-input; loop.py 4534→4184), `core/engine/routing_helpers.py` (`_fallback_todo_plan`/`_PLAN_REQUIRED_INTENTS`/`_should_skip_planning`/`get_adapter`), `core/engine/stage_clock.py` (`_StageClock`; _pipeline.py 3747→3639). Structural test pins the re-export contract. Full suite 1152 green. **Remaining:** the `AgentLoop` class body (~2900 LOC) and `Engine` class body (~3400 LOC) — method-level extraction is riskier, deferred.**

---

- [ ] **[Low, Long-term] B-2026-07-31-10 — Non-coding capability roadmap** (added 2026-07-31 by Buffy, Session 40) — Knowledge & Reasoning (summarizer, extractor, document analyzer), Computer Interaction (keyboard, mouse, window management), Personal Productivity (calendar, tasks, notes, reminders), Data tools (calculator, CSV, JSON, SQL, chart), External Services (connector/plugin framework). Long-term roadmap — build as extensible plugin framework rather than hardcoded tools. See `.context/memory/reviews/2026-07-31-review-6.md` Phase E. **Data tools slices DONE Sessions 131-132** (calculator/CSV/JSON + SQL — 4 bounded offline tools + 70 tests). Remaining: chart, Knowledge & Reasoning, Computer Interaction, Personal Productivity, External Services.

---

- [~] **[Medium] B-2026-08-09-12 — Best-of-N Editor UI (C2 spec step 7)** (added 2026-08-09 by Buffy, Session 86) — **Part 1 (Settings toggle) done `b01fcc6` (Session 88); Part 2 (ChatMessage candidates expandable) deferred** — needs SSE metadata plumbing. Files: `frontend/src/components/shared/SettingsModal.tsx`, `frontend/src/components/chat/ChatMessage.tsx`, `frontend/src/types/index.ts`.

---

- [ ] **[Low] B-2026-08-12-4 — Session 151 carry-over: re-run the live two-turn UI validation (stats corner + context meter)** (◐ partial 2026-09-08 audit — the CODE half is done: cumulative corner stats + context-occupancy meter shipped (PerformanceMetrics.tsx, CenterPanel.tsx; hook regression tests cover turn accumulation/reset); the ONLY remaining piece is the live two-turn validation itself) (added 2026-08-12 by Buffy, Session 152) — Blocked 2026-08-11 on Zen 429; servers left running. Once the rate limit clears: two live turns, verify corner shows "2 turns" + summed tokens, Context meter a real %, no confidence badge, per-message stats under each bubble. Frontend path already covered by 3 hook regression tests.

---

- [ ] **[Medium] B-2026-08-15-10 — Remove Direct Mode as a separate user-facing path; fold into classification (ADR-37)** (◐ partial 2026-09-08 audit — the enum/dispatcher half IS done: thinking_dispatcher.py and ExecutionMode deleted from models.py; but the user-facing Chat/Direct toggle was RE-ADDED later by B-2026-08-23-34 (ChatInput chatModeOptions, POST /api/settings/chat-mode, loop.py direct branch bypassing classification) — closing this now means a product decision to retire that toggle, not just code removal) (added 2026-08-15 by Buffy, Session 236) — Direct Mode (`chat_mode=direct` / `ExecutionMode.DIRECT`-as-toggle) is a second code path alongside the parent's classify-first pipeline — structurally the source of dual replies. One entry point, one path: classification decides trivial-vs-loop, and "fast vs slow" is just how much context-gathering a message needs. Keep DirectAgent (ADR-6) as the registry entry for the trivial path, but remove the user-facing toggle concept and any `chat_mode` branch that can fire in parallel with classification. Files: `backend/src/api/routes/chat.py` (chat_mode), `backend/src/core/thinking_dispatcher.py` / `models.py` (ExecutionMode.DIRECT), `frontend/src` (toggle UI), `docs/architecture/dual-mode-chat/*`. Needs care: don't regress the "Hi"→zero-call boundary (S206) or ADR-35's direct-turn token fix.

---

- [ ] **[High] B-2026-08-15-12 — Three-tier classification: tier decides whether Agent Workspace boots (ADR-37)** (◐ partial 2026-09-08 audit — (a) done: initialization.py prompt routes "what can you do?"/self-questions to direct; (c) mostly done: test_parent_uses_initialization_for_direct_response_without_execution_call + is_conversational_question fast-path prove zero tool-loop calls, though no test asserts absence of workspace EVENTS; (b) REMAINING: "reasoning proportionate to question" has no explicit mechanism — still only implicit via classify-only init — plus the live zen/laguna validation) (added 2026-08-15 by Buffy, Session 236) — The cleanest spec from the whole ADR-37 thread: not binary (trivial-fast vs everything-else-heavy), but THREE tiers — (1) trivial "hi" → reply immediately, near-zero reasoning; (2) needs-thought-not-tools "what can you do?" → content planning only, one pass, `direct`, NO workspace, NO loop, NO Thinker consult; (3) needs-tools/context → Thinker + full loop + workspace. Only tier 3 boots the workspace. Today's init classifies 1+2 as `direct` and 3 as `execute` (structurally correct), but the free-tier model can over-trigger `execute` for tier-2 content questions, and direct-mode reasoning does not yet scale with the question. Work: (a) prompt-tune the init classifier so tier-2 content questions resolve `direct`; (b) make direct-mode reasoning proportionate (brief objective for "hi", richer objective for "what can you do"); (c) prove tiers 1+2 never emit workspace/loop events (regression test). Needs live zen/laguna validation. Files: `backend/src/core/agent/initialization.py` (prompt), `backend/src/core/agent/loop.py` (direct branch), tests.

---

- [~] **[Medium] B-2026-08-16-5 — Right-tool steering + drop the redundant read-back (ADR-43 levers L2+L3)** (◐ PARTIAL Session 277 — `6b0b0f4`, review-53. **L3 DONE + live-verified**: loop surfaces its own file_write read-back verification to the model ([VERIFICATION] line), prompt trusts it → the redundant file_task read-back is gone (shell→file_write→file_task is now shell→file_write); also kills the S264 failure cascade. **L2 prompt half done** (removed list-before-create at prompts.py 740/874) but the exploratory `ls` PERSISTS on weak models because create tasks route to the `analyze` intent — the real fix is intent routing, split out to B-2026-08-16-9.) (added 2026-08-16 by Claude Code, Session 270) — Cheap prompt/guardrail changes that fix the user-flagged patterns: (L2) steer discovery → `find_path` not `shell`; "create X" → `file_write` directly (skip the exploratory `ls`/`Get-ChildItem` that also feeds the Thinker irrelevant evidence, cf. S263); structured data → `json`/`csv`/`sql` not shell text-munging — via the ADR-40 per-tool guardrail prose and/or a Thinker next-step hint. (L3) drop the post-write read-back self-verify (`file_task`) — the loop ALREADY verifies the write (`file_write verification passed: expected/actual`); the extra read is redundant and hit the S264 Windows path bug → `empty_response`. Fold confirmation into the `file_write` result and steer the agent not to re-read. **Live-verify tool SELECTION on z.ai/glm-4.5-flash (weak-model steering can regress).** Files: `backend/src/core/agent/prompts.py`/`tool_schemas.py` (guardrails), loop verify path. See ADR-43 + review-50.

---

- [ ] **[Medium] B-2026-08-16-6 — Uniform bounded observation contract (ADR-43 lever L4)** (◐ unchanged 2026-09-08 audit — still open as specified: ToolResult has unbounded content + no summary/detail-handle, observe.py doesn't exist; bounding remains the flat 2000-char _truncate_observation applied ad hoc at ~13 loop sites. Context: two-layer bounding is comprehensive (B-2026-08-16-4), so this is now the structural-cleanup half, not a leak fix) (added 2026-08-16 by Claude Code, Session 270) — The structural finish: standardize what every tool returns into the loop — `summary` (bounded, always) + `metadata` (counts/paths) + optional `detail handle` (fetch full output on demand) — enforced ONCE in the ingestion path so bounding is a framework property, not a per-tool patch. Fold B-4's ad-hoc caps into it. Open design question: contract lives in `ToolResult` (each tool fills a bounded `summary`) vs the loop/`observe.py` ingestion layer — leaning ToolResult so each tool owns what "bounded" means for its output. Largest + most durable; do AFTER B-4/B-5. Files: `backend/src/core/models.py` (ToolResult), `backend/src/core/agent/observe.py`, the tool registrations. See ADR-43 + review-50.

---

- [ ] **[Medium] B-2026-08-16-8 — Audit + trim the ~9k-token non-tool prompt overhead (prompt diet)** (◐ partial 2026-09-08 audit — INSTRUMENTATION done: _audit_breakdown/_audit_record per-section token accounting (env-gated LOCALMIND_PROMPT_AUDIT) + scripts/live_test_prompt_audit.py + review 2026-09-03-prompt-audit.md; some trims landed (intent tail split off the cached prefix 05e365c, stale-tool-reference fix, S411 core-tier demotions). REMAINING: the verbose REASONING DEPTH block (prompts.py) is still verbatim — no measured cut of it) (added 2026-08-16 by Claude Code, Session 275) — User: a one-tool task (find_path) cost 11,932 prompt tokens — "it needs all those tokens to run a single tool?" Measured: scoped tool schemas ≈ 2,718 tok (~23%, already lean via ADR-40). The other ~9,200 tok (~77%) is the agent system prompt (persona + CRITICAL RULES + the long REASONING DEPTH block + the intent-specific template with strategy/failure-modes/self-check + env context + ADR-18 task-state/criteria) + conversation. The lever is now the SYSTEM PROMPT, not the tools. Do NOT guess the split — instrument the actual assembled prompt (log each section's char/token count for one real turn) BEFORE cutting, then trim the highest-cost low-value sections (candidate: the verbose REASONING DEPTH + intent-template bullets a capable model doesn't need). Live-verify the trimmed prompt doesn't regress tool selection/quality on a weak model. Relates to the earlier "prompt diet" lever + ADR-39/40. Files: `backend/src/core/agent/prompts.py`, the prompt assembly in `loop.py`.

---

- [ ] **[Medium] B-2026-08-16-9 — Route "create a file" to FILE_WRITE, not analyze (the real L2 blocker)** (added 2026-08-16 by Claude Code, Session 277) — L2's exploratory-listing waste persists on weak models because "Create a recipe file on my desktop" classifies as the `analyze` intent, where the model explores (shell ls) by default before acting. Prompt steering (B-5, review-53) removed the "list before create" instructions but can't override analyze-mode on a weak model. Fix the classifier/router so create/write phrasings ("create/write/save a file/recipe/notes …") route to FILE_WRITE (whose scope + guidance are create-oriented). **Risky — live-verify across many task types (create, read, list, search, code) on glm-4.5-flash that nothing else misroutes; a classifier change can regress routing broadly.** Files: `backend/src/core/model_router.py` + the intent classifier. See review-53, ADR-43 L2.

---

- [~] **[Medium] B-2026-08-16-10 — As-completed result streaming for parallel tool batches** (◐ IMPLEMENTED Session 279 — `cf38bc0`, review-55. Per-task emit + asyncio.as_completed + yield-to-flush; model-context rebuilt in input order; fixes the stale-`_inp` args bug. NO REGRESSION (1875 pass). **As-completed ordering NOT live-verified**: neither glm-4.5-flash NOR gemini-2.5-flash emits native parallel tool_calls — they serialize or route to the delegate_parallel TOOL, so the MultiToolCallResult path never activated in live traces. Low-risk (contained). Finding → B-2026-08-16-11.) (added 2026-08-16 by Claude Code, Session 278) — Parallel tool calls already dispatch concurrently via `asyncio.gather` (loop.py:1603), but the loop BLOCKS until the whole batch finishes before continuing. The user wants each tool's result surfaced to the user the moment it completes ("invoke multiple tool calls and wait for outputs from each separately … results caught concurrently"). Replace the gather-all-then-continue with an as-completed pattern (`asyncio.as_completed` / a queue) that emits each tool's completion event/observation as it lands, so a slow tool doesn't hold up a fast one's UI update. NOTE (honest architecture limit): the MODEL still can't generate tokens while awaiting results — its turn pauses at the tool hand-off; this is about the loop surfacing results progressively, not the model reasoning mid-await. Live-verify with a multi-tool turn (e.g. two find_path calls) that fast results appear before slow ones. Files: `backend/src/core/agent/loop.py` (the MultiToolCallResult dispatch, ~1600), the obs/SSE bridge. See review-54.

---

- [ ] **[Low] B-2026-08-17-4 — restore thinkMs / diffData / candidates on reload** (added 2026-08-17 by Claude Code, Session 290) — Session 290 fixed the thinking block (isAgent) + persisted the acknowledgement, but three per-turn ChatMessage fields still don't survive a reload: `thinkMs` (the "Thought for Xs" duration — cosmetic; backend doesn't currently track thinking duration), `diffData` (edit_file structured-diff render — the edit is still visible via toolCalls, so partial), `candidates` (best_of_n_edit — niche feature). `statusText`/`pendingWrite` are transient and correctly NOT persisted. Follow the Session 266/290 pattern (persist column → history endpoint → client restore) if/when these matter. Files: `frontend/src/lib/localmind/client.ts` (getSessionHistory mapping), `frontend/src/components/chat/ChatMessage.tsx`, backend `storage/db.py` + `core/models.py` + `api/routes/sessions.py` for any that need a new column.

---

- [ ] **[Low] B-2026-08-17-7 — write-allowed-but-read-blocked path gives a FALSE grounding failure** (added 2026-08-17 by Claude Code, Session 294) — After B-2026-08-17-6, a file written to a path that file_write ALLOWS but file_task's read-allowlist (`is_path_allowed`, file_reader.py:346) BLOCKS (e.g. /private/tmp, or any folder outside LOCALMIND_ALLOWED_FOLDERS) still gets `[GROUNDING CHECK FAILED]` — because the read-back is DENIED, not because the file is missing. The grounding/verify should distinguish "read blocked by allowlist" from "file missing/empty" and not emit a fabrication warning for the former (the write itself succeeded — metadata.bytes>0). Edge case (writing outside allowed folders). Files: backend/src/core/agent/loop.py (grounding block ~2385, `_verify_tool_result` ~4796), backend/src/tools/file_reader.py (is_path_allowed).

---

## Session 295 — token/speed optimization roadmap (3-agent investigation, review-62)

---

- [ ] **[Medium] B-2026-08-17-8 — INPUT tokens: in-prompt tool-list + scaffold trim** (◐ partial 2026-09-08 audit — (A2) substantially superseded: the in-prompt list renders only scoped/core defs and the bootstrap branch uses compact_tool_summary (<4k, pinned by test_compact_tool_summary_covers_all_tools_with_purpose) with a name-only on-demand menu; render_tool_list still emits full name:description lines by design. REMAINING: (A4) the scaffold was consolidated (byte-stable prefix 05e365c) but disambiguation/safety prose is NOT deduplicated — e.g. prompts.py FILE_WRITE template still carries "list it with shell first" alongside the universal "don't list the folder first" rule (a contradictory remnant); ADR-40 live-verify on phi4-mini still owed) — (A2) collapse long-tail tools in the in-prompt "Available tools:" list (prompts.py:489) to name-only (~323 tok/call; they're describe_tool'd anyway) — keep a one-line "on-demand: …" menu; update test_render_tool_list_*/test_system_prompt_list_derived_from_tool_defs. (A4) trim triplicated disambiguation in build_agent_system_prompt (prompts.py:672-824,862-904; ~500-1000 tok/call). ADR-40 live-verify tool selection on phi4-mini before shipping.

---

- [ ] **[High] B-2026-08-17-9 — OUTPUT tokens: cap file_read injection + uniform choke-point cap** (◐ partial 2026-09-08 audit — (B5) done: cached obs truncated where they enter the log + log itself capped, but tool-role re-injection still sends raw cached output ("content": cached_obs). REMAINING: (B1) constants.py FILE_READ_MAX_BYTES still 512*1024 — no 16-32KB injection cap; (B2) no per-tool-aware cap map — only the flat 2000-char _truncate_observation at the choke point) — (B1, HIGH) FILE_READ_MAX_BYTES 512KB→~16-32KB for the agent-loop injection (constants.py:118, file_reader.py:239) — up to ~120K tokens per large read; keep the "use shell for specific lines" notice; verify a "summarize a file" task on a mid model. (B2) add ONE per-tool-aware cap at the choke point loop.py:2580 so every observation is bounded (make L4 real; per-tool cap, NOT flat 2000). (B5, safe) truncate re-injected cached obs on dedup hits (loop.py:2038).

---

- [ ] **[High/risky] B-2026-08-17-11 — LATENCY: fold classify + first action (3 calls → 2)** — the biggest per-turn win on slow models (one full generation saved every execute turn). Revive the dormant initial_tool_result path (loop.py:1089-1138; agent_runtime.py:681 passes None): let init optionally emit a `first_action`; pre-dispatch it ONLY when it's a high-confidence WHITELISTED READ-ONLY action (dir list/git status/file read/web fetch) — any missing/unparseable first_action falls back to the normal iter-0 call, keeping ADR-46 (execute opt-in, never fail-open) intact. Cuts against ADR-38 evidence-first — needs live A/B on accuracy, not just latency. initialization.py:109-117,254.

---

- [ ] **[High] B-2026-08-17-12 — STEERING (L2 secondary): parent-path create→file_write + don't-exploratory-shell** (◐ partial 2026-09-08 audit — the universal execution scaffold (build_agent_system_prompt, used for EVERY parent intent incl. ANALYZE) now carries the steering: rule 7 "to CREATE a file … call file_write directly — do NOT list the folder first", shell-writes-file = LAST RESORT (rule 768), rule 10 "Never re-run a read". REMAINING: discovery→find_path steering absent (find_path nowhere in prompts.py) and prompts.py FILE_WRITE planning template still says "list it with shell first to confirm the path" — contradictory remnant; ADR-40 live-verify still owed) — the live baseline showed a "create a file" task do shell ls + echo> + cat (3 LLM calls) instead of one file_write. The parent path runs intent=ANALYZE whose persona lacks the create→file_write + discovery→find_path + "don't list the folder first / don't cat to read back" steering the SHELL persona has (prompts.py:738-740). Add that steering to the ANALYZE persona / the parent execute scaffold. Biggest per-task LATENCY win (collapses ~4 LLM calls). ADR-40 live-verify. This is ADR-43 L2-secondary + connects to L3.

---

- [ ] **[Medium] B-2026-08-18-6 — synthesis grounding: don't assert specific facts not in the evidence** (◐ partial 2026-09-08 audit — (a) the combined-synthesis prompt ALREADY carries anti-fabrication rules ("If the fetched page doesn't fully answer the question, say what you found and note what's missing… NEVER add information from your training data" — synthesizer.py) but they predate this item; remaining: the post-synthesis proper-nouns-vs-evidence check — the existing _filter_synthesis (synthesizer.py) only matches 3 hardcoded patterns (Volume Serial/Directory of/File(s)) (added 2026-08-18 by Claude Code, Session 298; source: EPL transcript) — In the transcript the model found the season START DATE (Wikipedia) but then asserted a SPECIFIC first match ("Arsenal vs Coventry City, Emirates, Friday Night Football") that was NOT in the fetched evidence — a fabricated detail presented confidently, and it didn't self-correct when challenged. The completion floor + grounding (B-2026-08-18-2) verify TOOL RESULTS, not whether the ANSWER's claims are supported by the gathered evidence. Consider a lightweight synthesis-grounding check: flag/soften answer claims (named entities, specific dates/scores) that don't appear in any tool observation, and instruct the synthesizer to say "the sources gave X but didn't specify Y" rather than inventing Y. Hard to fully enforce on a weak model (it will still hallucinate), so scope to (a) a stronger "only state what the evidence supports; if a detail wasn't found, say so" instruction in the combined-synthesis prompt, and (b) optionally a post-synthesis check that the answer's proper nouns appear in the evidence. Live-verify on glm with a query whose specifics aren't in the results. NOTE: this is model-limited — the harness can reduce but not eliminate hallucination.

---

- [ ] **[High] B-2026-08-18-4 — SHARPENED (Session 298): the weather steer is PROVEN unreliable; build the structured path** — Live-tested TWICE on glm-4.5-flash (soft steer, then a strong "weather MUST be a table" steer): the model STILL returns a bold list, not a table. Confirmed: prompt-steering cannot guarantee weather formatting on a weak model (same lesson as ADR-49 / B-2026-08-18-5). The reliable fix is HARNESS-FORMATTED from structured data: (1) a `weather` tool (`backend/src/tools/weather.py`) that fetches `https://wttr.in/<location>?format=j1` (free, no key → JSON: current_condition + hourly + nearest_area), register it in the parent toolset; (2) when a weather tool result is present, the synthesizer/harness DETERMINISTICALLY formats the answer's weather section as a Markdown table (Metric|Value for current; Time|Conditions|Temp for hourly) from the structured fields — NOT the model's prose — which then renders via the table-card styling already shipped (9d1ac6b). Optional stretch: a dedicated `WeatherCard` React component + a ```weather fenced block (mirror DiffBlock) with a °C/°F toggle. This removes the model-format dependency entirely. NOTE shipped this session toward it: table-CARD styling (9d1ac6b) + `<br>`-in-cell → line break rendering + the (soft, unreliable) steer. (⧗ status clarified 2026-09-08 S440 — this is the LIVE copy of this item; the checked B-2026-08-18-4 copy above (the 2026-09-02 sweep's superseded-duplicate pointer) closes the POINTER, not the work. Re-verified open in code 2026-09-08: no `backend/src/tools/weather.py`, no WeatherCard component — grep clean. Do NOT mark this item done because a checked duplicate exists.)

---

- [ ] **[Medium] B-2026-08-19-1 — live recovery after a failed high-stakes action needs a clean honest-stop path** (◐ partial 2026-09-08 audit — a bounded deterministic honest-stop EXISTS since Session 330: _MAX_TOTAL_GATE_REPLANS=2 → _emit_honest_stop "Cap hit — honest report" (test_parent_failed_action_at_cap_stops_honestly), so the infinite-replan symptom is capped. REMAINING: the gate still rejects honest-inability prose UNCONDITIONALLY at first pass (no early acceptance of "couldn't/unable to" acknowledgments) and the specific weak-model behavior still needs the live verify the item requires) (added 2026-08-19 by Buffy, Session 299 live follow-up) — The real z.ai/glm-4.5-flash trace confirmed structured failure propagation and `[RECOVERY]`, but then the weak model emitted honest prose without a corrective tool call. The parent completion floor rejected that prose and issued repeated replan calls; the trace ended before a clean terminal completion event. Regression tests use a cooperative mock and therefore do not cover this model behavior. Decide whether the floor should accept an explicitly honest inability answer after a failed action, or use a deterministic bounded failure response once the model has acknowledged the failure, while preserving the no-false-success contract. Must live-verify before shipping any change.

---

## Session 302 update — warm Parent Kernel

---

## Session 303 scope amendment — Parent-only architecture

---

## Session 305 update — ParentSession + readiness telemetry (ADR-54)

---

- [ ] **[Low] B-2026-08-20-5 — tune ParentSession compaction thresholds from real workload** (added 2026-08-20 by Super Z, Session 305) — `RECENT_TAIL_MAX=6` pairs and `SUMMARY_MAX_CHARS=4000` (≈1000 tokens) are initial guesses calibrated to keep the prompt bounded. A real long-conversation workload (50+ turns, code-heavy) may want different values — e.g. raise tail to 8 for ongoing multi-step tasks, or lower summary cap to 2500 for tighter token budgets. Tune based on observed prompt_tokens on turn 20+ of a real long chat. Files: `backend/src/core/parent_session.py` (constants at top). Re-run the live trace after any change.

---

## Session 306 update — GLM native tool trace + new weak-model finding

---

## Session 307 update — prose-commitment detector + new finding

---

- [ ] **[Low] B-2026-08-20-8 — extend `_is_tool_talk` regex to include "describe" verb** (added 2026-08-20 by Super Z, Session 307) — The existing `_is_tool_talk` detector (`core/agent/text_tools.py:368`) catches "I'll use/call/invoke/run the X tool" at the initial-buffer stage, but misses "let me describe the shell tool" because "describe" isn't in the verb alternation. Session 307 shipped a backstop detector at the acceptance gate (`prose_commits_to_tool_action`) that catches this later, but the cleaner fix is to extend the existing regex so the pattern is caught EARLIER (before the prose streams to the user). Add `describe` to both regexes: `r"i (will|would|need to|am going to) (use|call|invoke|run|describe) (the )?(\w+) tool"` and `r"let me (use|call|invoke|run|describe) (the )?(\w+) tool"`. Also consider "first" between "me" and the verb: `r"let me (?:first )?(use|call|invoke|run|describe) (the )?(\w+) tool"`. Watch for false positives — "describe the shell tool" could appear in a legitimate capability answer. Files: `backend/src/core/agent/text_tools.py` (`_TOOL_TALK_PATTERNS`). Unit-test the new patterns; live-verify on glm-4.5-flash.

---

## Session 308 update — post-loop synthesis + new finding

---

- [ ] **[Low] B-2026-08-20-9 — shell tool error message should suggest plain-string command on JSON-wrapped input** (added 2026-08-20 by Super Z, Session 308, from a live GLM trace) — The live trace showed the model call `shell({"action": "execute", "command": "hostname"})` (a JSON-wrapped form) which the shell tool rejected. The model then concluded "the shell tool does not include a direct hostname command" — a capability hallucination. The shell tool DOES accept arbitrary `command` strings including `hostname`, but the error message when given a JSON-wrapped form doesn't guide the model toward the correct plain-string form. FIX: when the shell tool receives a `command` arg that looks like JSON (`{"...": "..."}`), return a helpful error: "The `command` parameter expects a plain shell command string (e.g. `hostname`), not a JSON object. Retry with `command: \"hostname\"`." This would let the model self-correct instead of concluding the tool can't do it. Files: `backend/src/tools/shell.py` (the argument-validation/error path). Live-verify on glm-4.5-flash with the hostname task.

---

## Sessions 309-310 update — frontend indicator + parent recovery cap

---

## Session 311 update — overlap ParentSession DB load with memory retrieval

---

## Session 313 update — end-to-end system audit findings

---

- [ ] **[High] B-2026-08-20-10 — MiniMax XML interception conflicts with prose-commitment detector** (added 2026-08-20 by Super Z, Session 313, from live audit trace C1) — Live audit: "What is the hostname of this machine?" produced the prose preamble "I'll get the hostname of this machine for you." as the FINAL ANSWER — the model committed to calling shell but never did. The B-2026-08-20-6 prose-commitment detector at the acceptance gate did NOT fire because the MiniMax XML interception path (initial-buffer stage, loop.py ~line 3806) treated the prose as a completed turn first (`MiniMax XML detected in initial buffer during Phase 2 — re-checking` → `finished iter=1`). The two recovery paths conflict: the XML path runs BEFORE the gate-level detector and accepts the prose. FIX DIRECTION: the MiniMax XML interception should check whether the prose contains a tool-action commitment phrase ("I'll get", "let me use", "I'll call") before accepting it as final; if it does, route to the prose-commitment nudge (inject `[TOOL COMMITMENT]` re-prompt) instead of finishing. Alternatively, lower the prose-commitment detector to run at the initial-buffer stage too (before the XML interception). Live-verify on glm-4.5-flash with the hostname task. Files: `backend/src/core/agent/loop.py` (the MiniMax XML interception path ~line 3806, + the `prose_commits_to_tool_action` detector ~line 648).

---

- [ ] **[Low] B-2026-08-20-12 — embedding failure when Ollama unavailable silently disables memory** (added 2026-08-20 by Super Z, Session 313) — The vector store (`storage/vector.py:278`) logs `[embed] Failed: All connection attempts failed` when Ollama isn't running, and memory facts don't get stored. The turn proceeds gracefully (no crash), but the memory system is effectively disabled. In a cloud-only deployment (no local Ollama), this means memory never works. FIX DIRECTION: allow a cloud embedding provider (e.g. z.ai's embedding API, or OpenAI's text-embedding-3-small) as a fallback when Ollama is unreachable, OR document explicitly that the memory system requires a local Ollama instance for embeddings. Files: `backend/src/storage/vector.py`, `backend/src/core/config.py` (an `LOCALMIND_EMBED_ADAPTER` setting). Low priority — the system degrades gracefully; the fix is about capability, not stability.

---

## Session 314 update — anti-hedging + recovery nudge context

---

## Session 315 update — clean user-facing fallback

---

## Session 316 update — deterministic evidence extraction

---

## Session 318 update — web_fetch redirect + tool-failure recovery (live-tested)

---

## Session 319 update — B.AI provider (ADR-55, config-only, live smoke blocked)

---

## Session 323 update — task-anchored recovery nudges + creation-commitment detection

---

## Session 324 update — silent Thinker (filter-before-render)

---

## Session 330 update — synthesize/evaluate stage shipped (B-2026-08-20-24 done)

---

## Session 342 update — conversation test sets (multi-turn) + first live findings

---

## Session 342 addendum — corrections + clarify sets live (CONV-03/04/05/06)

---

## Session 342 addendum 2 — Thinker coverage gap: root cause of the narration-without-action findings

---

- **[Diagnosis, refines B-2026-08-22-3] The Thinker is ABSENT on the parent-agent pre-tool path — not shallow.** Verified from saved SSE event counts (CONV-05/06/11/12 traces): the Thinker has exactly two call sites — (1) `agent_runtime.py:907` pre-tool but ONLY on the conversational fast-path (`is_conversational_question`, S354); (2) `loop.py:3543` post-tool, gated on `observation` truthy. A parent-agent turn with zero tools and no conversational opener (e.g. "Fix my project.", "Improve the system.", "Don't tell me you don't know — just guess.") gets NO Thinker consult at all → no structured intent pass → the model free-associates "I'll start by exploring…" or fabricates. The Thinker's own prompt has the exact guidance for this class ("NO TOOLS HAVE RUN YET… respond directly, call a tool, or clarify"). Fix direction: wire the S354 pre-tool consult (Evidence(user_message, conversation_history, observations="") → inject `_thinker_context_block`) into the parent-agent loop's FIRST iteration before any tool call. Also: CONV-05/06 turn 1 shows no `agent_initialization_done` — the objective-derivation init call also skips vague imperatives (related, investigate with the fix). CONV-06 turn 2 was `agent_loop_error`, not a silent drop — downgrade B-2026-08-22-4.

---

## Session 343 update — pre-tool Thinker consult FIXED; honesty guard items refined

---

## Session 344 update — B-2026-08-22-1 AND B-2026-08-22-2 DONE (pressured re-ask guard)

---

## Session 344 addendum — CAT2 criteria tightened (B-2026-08-22-3 remainder part DONE) + portability fix

---

## Session 346 update — B-2026-08-22-5 DONE (vague imperative → deterministic clarify)

---

## Session 347 update — B-2026-08-22-4 CLOSED (downgraded: 429 error card, by design) + B-2026-08-20-11 DONE

---

## Session 349 addendum — 12 new backlog items (user-provided, 2026-08-23)

---

Each item below is a SEPARATE backlog entry — some are features, some are fixes. They were

---

recorded verbatim-ish from the user's list; each gets its own B-2026-08-23-N id and its own

---

checkoff. Work them one at a time per the one-task-at-a-time rule.

---

- [ ] **[Medium] B-2026-08-23-10 — Planning and logic should be concrete** (fix/quality, user: "Planning and logic should be concrete.") — Vague/abstract planning output (generic steps that don't reference the actual task artifacts) must be replaced with concrete steps (named files, real commands, specific verification). Likely ties to the planner prompt + the goal-checklist derivation; audit current plan output quality on a tool-bearing task and tighten.

---

## Session 360 addendum — 12 more backlog items (user-provided, 2026-08-23)

---

A second "Backlog Each Separately" batch. Each is a SEPARATE entry with its own

---

B-2026-08-23-N id and checkoff. Some are features, some fixes; work them one at a

---

time per the one-task-at-a-time rule. A few are deliberately under-scoped

---

(user-provided one-liners) — scope with the user when picked up.

---

- [ ] **[Medium, frontend] B-2026-08-23-20 — Rewrite the code block preview, discarding the old one** (◐ partial 2026-09-08 audit — every REQUESTED FEATURE is present (copy button, language badge, clickable filename header, line numbers, horizontal scroll, run-in-terminal affordance) but the work was an IN-PLACE upgrade, not a discard: react-syntax-highlighter (PrismLight/vscDarkPlus) is still the renderer in ChatMessage.tsx and no standalone CodeBlock component file exists. REMAINING for a true "discard": replace the lib + light/dark-adaptive syntax theming (vscDarkPlus is a fixed dark theme). Same effort as B-2026-08-25-10) (feature, user: "Rewrite code block preview discarding the old one") — Replace the current code-block rendering (CodeBlockComponent / react-syntax-highlighter path in ChatMessage) with a fresh implementation (copy, language badge, filename header, line numbers, run affordance, theming). Discard the old component rather than patching it.

---

- [ ] **[Low, needs scoping] B-2026-08-23-23 — Advanced image viewing and processing** (feature, user: "Advanced image viewing and processing") — Beyond the current data-URL render: zoom/pan, rotation, fullscreen, and processing actions (resize/convert). Needs scope + feasibility check against the current viewer.

---

## Session 379 addendum — third "Backlog Each Separately" batch (user-provided, 2026-08-23)

---

Another batch from the user. Each is a SEPARATE entry with its own B-2026-08-23-N id and

---

checkoff. Some are features, some are fixes; work them one at a time per the

---

one-task-at-a-time rule. A few are deliberately under-scoped (user one-liners) —

---

scope with the user when picked up.

---

- [ ] **[Needs scoping, architecture] B-2026-08-23-30 — Should the agent planner have a workflow / backlog / task-list / spec kit?** (question, user) — advisory item: whether the planner should carry a persistent workflow/backlog/spec-kit shape beyond the current plan_steps/goal_items + todos. Do NOT build yet — investigate what exists (planner, todo_write, goal-checklist, session todos) and bring the user a proposal with options.

---

- [ ] **[Medium, backend] B-2026-08-24-7 — Gemini answers directly from the LLM instead of going through the agent (no thinking/loop)** (investigation+fix, user: "Why don't gemini invoke thinking? It answers directly from LLM not the agent.") — Gemini (gemini-2.5-flash via the OpenAI-compat endpoint) appears to bypass the agent loop / thinking and reply straight from the model. Root-cause: is it the DIRECT fast-path, a classifier/route decision, or an adapter quirk where gemini returns content without tool deltas (the loop already has several gemini-specific "skipped the tool API" workarounds — `loop.py` ~762, ~3056, ~4936, ~5266)? Determine why gemini turns don't enter the agent/thinking path and fix so gemini gets the same agent treatment as other providers. Pointers: `backend/src/core/model_router.py`, `backend/src/core/engine` routing, `backend/src/adapters/openai_compat.py`. Live-test with a real gemini key.

---

- [ ] **[Standing practice] B-2026-08-24-8 — Always live-test to verify** (process, user: "Always live-test to verify") — Every agent-behavior fix must be verified against a real model in the running app before it's called done — mocked/unit tests are necessary but not sufficient (the 2026-08-24 exports are all live-behavior failures unit tests passed through). Applies to B-2026-08-24-1..7 and all future agent work: reproduce the original prompt live, confirm the fix, and record the live result in the session entry. This is a standing verification requirement, not a buildable feature.

---

- [~] **[Medium, frontend/design] B-2026-08-24-13 — Give the whole app the Settings page's background** (✅ DONE Session 399, commit `1b15c2f`; pending user's visual sign-off) — Elevated all 7 main chrome surfaces (shell/panels/center+header/titlebar) + html/body ground from `bg-brand-bg-base` (#12161d) to `bg-brand-bg-panel` (#1f2530, the Settings surface); inner inputs/cards keep base so they recess, exactly as Settings. Background/tone only. tsc + 59 layout tests pass; live via HMR in the user's running app. Tunable: change `--brand-bg-panel` / pick another `--s-*` step if the tone is off. (feature, user: "the settings UI has a different background to the main app; I like the settings one and want the app to have that — the real background of the settings itself, NOT the blur") — The user likes the Settings background SURFACE COLOR/TONE, explicitly not the backdrop-blur. Settings sits on the panel background token(s) (`bg-brand-bg-panel` / `bg-brand-bg-panel-alt`) while the main app shell sits mostly on the flat `bg-brand-bg-base` — that panel tone is what the user wants app-wide. Apply the Settings background surface to the main app (panels, rails, chat area) WITHOUT adding blur. Confirm the exact token the user means by comparing `SettingsModal.tsx`'s outermost/content background vs the main shell, then route the main layout surfaces through it. Audit `frontend/src/components/layout/*.tsx` (WorkspaceLayout, CenterPanel, LeftPanel, RightPanel); keep it theme-token-driven (relates to B-2026-08-23-19 custom theme/tone, B-2026-08-23-24 no-hardcoding). Design pass — get the user's eye on it before finalizing.

---

- [~] **[High, frontend] B-2026-08-24-14 — Real-time UI updates flicker/flaky (Agent Workspace, action cards)** (✅ DONE Session 399, commit `6cc1aa7`; pending user's visual sign-off) — Root cause (user's hint "maybe they get animation a bit?"): the live lists put framer-motion `layout={!reduceMotion}` on their rows, so every append/update/reorder/removal animated the POSITION of every existing sibling → the whole list reflowed and jiggled on each SSE event. Removed `layout` from AgentWorkspace (runs/phases/tools), ActionHistory, ToolSteps, and TodoList; new rows still fade/slide in via `enter()`, existing rows now snap instead of re-animating. React 19 already auto-batches setStates (not the cause); keys were already stable. tsc clean; full frontend suite 352 pass. Runtime-visual — user to confirm the flicker is gone in the app. Original note below: — Live SSE-driven updates to the Agent Workspace (AgentPhases / agent runs) and the action/tool cards flicker, reorder, or briefly show inconsistent state as events stream in. Likely causes to investigate: unstable React keys, list re-sorting on each event (phases are sorted by rank every append — see AgentPhases + useLocalMind buildAgentPhase), dedup races between started/done tool events (the name-based dedup in useLocalMind ~840-910), and frequent setState from the 2s/2.5s polls colliding with SSE updates. Stabilize keys, make updates idempotent/monotonic, and avoid full-list re-renders per event. Pointers: `frontend/src/hooks/useLocalMind.ts` (SSE handlers, tool-call dedup, phase assembly), `frontend/src/components/chat/AgentPhases.tsx`, `frontend/src/components/chat/ToolSteps.tsx`, ActionHistory. Live-test to reproduce (flicker is runtime-only).

---

- [ ] **[Medium, tools] B-2026-08-25-2 — system_search Phase 2: content-aware search** (feature, original pitch) — Wire content search into the unified front door: a `content` operation over `grep_search` machinery (bounded), then semantic ranking over .md/.txt/.docx/.pdf project docs ("find the document where we discussed building the parent agent"). Pointers: `backend/src/tools/grep_search.py`, `backend/src/tools/system_search.py`, the feature manifest `.context/memory/features/system-search-tool/manifest.md`.

---

- [ ] **[Low, tools] B-2026-08-25-3 — open_with native associations unverified outside Linux container** (verification) — `_op_open_with` platform lookups (Windows assoc/ftype, macOS osascript, Linux xdg-mime) degrade to the hint map in the dev container (no desktop associations installed). Needs a real-Windows/macOS verification pass by the user. Pointers: `backend/src/tools/system_search.py` (`_assoc_windows`/`_assoc_macos`/`_assoc_linux`).

---

---

- [ ] **[Low, agent/tools] B-2026-08-25-5 — File creation via shell `echo >` redirection instead of file_write (skips diff emission)** (steering gap, field live-test finding Session 401) — bankofai/deepseek-v4-flash, prompt "Make a folder called Invoices and create a file march.txt inside it…": the model used `mkdir -p` + `echo '...' > march.txt` (both via shell) instead of the file_write tool. Deliverable was correct on disk, but shell-redirect writes emit NO before/after diff event (the diffable-writes steering from the Session ~380 work exists but did not hold on this model). Consequence: no diff card in chat for user-created files. Consider: steer in the shell tool's description ("to CREATE/WRITE a file use file_write — echo > redirects are not diffable") or accept per-model. Pointers: `backend/src/tools/shell.py` (description + `_open_app` region), `backend/src/core/agent/tool_schemas.py` shell description, trace `scratch/sse-field-run1-invoice_folder.sse`.

---

- [~] **[High, frontend/UX] B-2026-08-25-6 — Diff card does not return to a normal view after the user clicks Accept on a file edit/creation** (fix, user report 2026-08-25) — After an edit_file/file_write turn, the chat message shows the inline diff card with an Accept/Reject bar. When the user clicks **Accept**, only the button row swaps to a small "Accepted" status strip — the card itself KEEPS rendering the full colored diff (red/green lines) permanently, so the chat reads as if an un-applied diff is still pending. Expected: after Accept, the message transitions OUT of diff presentation to a normal view (compact "changed file" chip like FileResultChip, or the final file state), with the diff still re-openable on demand. Root cause pointers: `frontend/src/components/chat/ChatMessage.tsx` (~line 800) renders `<DiffBlock hunks={diffHunks} showActions={true} isStreaming={...}/>` with **no onAccept/onReject passed** — the internal `handleAccept` (DiffBlock.tsx ~line 251) only sets local `actionStatus='accepted'` and calls the optional (absent) callback. Two dimensions to fix: (1) no state transition dismisses/collapses the diff view on accept; (2) `actionStatus` is component-local useState — it resets to 'pending' on remount/refresh, so the Accept bar REAPPEARS after reload even though the edit was already applied (accept-state should derive from the message's applied-status, not ephemeral UI state). Note: the FilePreviewDialog has its own separate Preview/Edit/Diff mode switcher (mode==='diff' is user-toggled there) — this item is about the INLINE chat diff card, but check both surfaces for the same stuck-diff symptom. Repro: ask the agent to edit or create a file → click Accept on the diff card → card stays in diff mode; refresh → Accept bar is back.refresh → Accept bar is back. **DONE (3072074, Session 402):** Accept now collapses the diff to a compact applied card (file + stats + View-diff toggle; read-only reopen). Correction to the reload claim above: diffData is live-stream-only (not persisted, not restored by the history mapping) — on reload the diff disappears entirely, so there is no stale-Accept-bar-after-reload case; component-local state suffices. 4 regression tests; 356 frontend tests green; user visual sign-off pending.

---

- [ ] **[High, agent/context] B-2026-08-25-7 — Follow-up turn loses the prior fast-path answer from the model's context** (◐ partial 2026-09-08 audit — the PERSISTENCE half was fixed 2026-09-07 (8e72d3d: _persist_user_before_reply awaited on the fast-path epilog, locking both rows — closes the CX-1 never-persisted-user-row symptom; test_fastpath_user_persist.py). Since agent-loop turns assemble history[-8:] user/assistant rows from the same store, persisted fast-path turns now mechanically reach the next turn's window. REMAINING: no SC-1 regression test in tests/ + the live repro (run_suite_detached.sh sc SC-1) to confirm the t1 agent_context_ready observation is gone) (bug, full-suite benchmark finding Session 404, test SC-1) — Multi-turn session `suite-run1b-SC-1`: t0 "What is 15 × 8?" answered "120." via the trivial fast-path (SSE t0 has NO `agent_context_ready`/`task_type_settled` — loop bypassed). t1 "Check your previous answer carefully. Was it correct?" → model answered "There is no previous answer in this conversation thread — this is the very first interaction." DB evidence: `messages` table rows 109 ("120.", role=assistant), 110 (t1 user), 111 (t1 assistant) — t0 WAS persisted, so the break is in the follow-up turn's CONTEXT ASSEMBLY, not persistence. `agent_context_ready` for t1 shows only `memory_facts: 1`, no conversation-history fields. Related observation in the same run: CX-1's t1 USER message ("What is the budget for each project?") was never persisted (its assistant answer row exists, the user row doesn't) — yet CX-1 still answered correctly, so the loss is intermittent or shape-dependent. Suspicion: fast-path / short-circuit turns don't feed the next turn's history window the way full-loop turns do. Repro: `./scripts/run_suite_detached.sh sc SC-1` then inspect `scratch/suite-home/localmind.db` messages for the session. Pointers: `backend/src/api/routes/chat.py` (`_is_first_turn`, fast-path wiring), `backend/src/core/engine/_pipeline.py` (history assembly), trace `scratch/sse-suite-run1b-SC-1-t0.sse` / `-t1.sse`.

---

- [ ] **[Medium, frontend/design] B-2026-08-25-10 — Redesign the code block component** (◐ partial 2026-09-08 audit — see B-2026-08-23-20's note (same effort): all requested features present but the react-syntax-highlighter path was upgraded in place, not discarded; remaining = replace the lib + light/dark-adaptive syntax theming) (feature, user 2026-08-25: "add codeblock redesign") — Fresh code-block rendering in chat: copy button, language badge, optional filename header, line numbers, syntax theming that matches the app surface (light + dark), horizontal scroll for wide lines (no page overflow), and a run affordance where it makes sense. Discard/replace the current component rather than patching it. NOTE: overlaps B-2026-08-23-20 ("Rewrite the code block preview, discarding the old one") — treat as the same effort / dedupe when picked up. Pointers: `frontend/src/components/chat/ChatMessage.tsx` (CodeBlockComponent / react-syntax-highlighter path), `frontend/src/components/chat/ResponseBlockRenderer.tsx`. Scope the look with the user before building.

---

- [ ] **[Medium, agent/routing] B-2026-08-25-12 — Destructive imperatives ("delete the .bin files") classify as intent "analyze"** (fix, live-test finding Session 405) — In the B-25-11 live test, "Delete the two large .bin files in <dir>…" settled to intent **analyze** (read-biased), not an action intent. The parent loop still ran and (post-B-25-11) completed the delete, but the read-bias is a latent cause of "inspect then stop" behavior and of the model treating a mutation request as investigation. Map clear destructive/mutating imperatives (delete/remove/rm/erase/move/rename/create/write/install) at the head of the request to an action intent (SHELL/FILE_TASK/FILE_WRITE) rather than ANALYZE. Verify it doesn't regress genuine "analyze X before changing it" phrasing (B-24-9/Cluster-B already protects "don't write code yet"). Pointers: the task-type/intent classifier feeding `agent_loop_start` (`intent=`), `backend/src/core/agent/pre_init_classifier.py`, engine routing. Live-test: re-run the sandbox delete and confirm intent settles to an action type.

---

- [ ] **[High, agent/adapters] B-2026-08-25-13 — `gate_force_tool` (tool_choice) is a NO-OP on providers that reject tool_choice (bankofai)** (fix, live-test finding Session 405) — Backend log during the B-25-11 live test: `[adapter] bankofai rejected tool_choice; retrying without it`. Every force-tool gate (ACTION-NARRATION, PENDING ACTION, TOOL COMMITMENT) sets `gate_force_tool[0]=True` so the main loop forces `tool_choice` — but on bankofai (and any OpenAI-compat endpoint that 400s on tool_choice) the adapter silently drops it, so the model is NOT actually forced; only the injected re-prompt TEXT carries weight. Provide a provider-agnostic force: (a) detect tool_choice support per adapter and, when unsupported, escalate the re-prompt (stronger imperative + example tool_call JSON), and/or (b) a bounded "must emit a tool_call or a single clarifying question" contract enforced by the gate regardless of tool_choice. Pointers: `backend/src/adapters/openai_compat.py` (the tool_choice retry-without), `backend/src/core/agent/loop.py` (gate_force_tool consumer, forced-tool nudge). Live-test across a tool_choice-honoring provider vs bankofai.

---

- [ ] **[Medium, security/config] B-2026-08-29-1 — Encrypt/externalize provider API keys via OS keyring (Option A, VS Code-parity)** (added 2026-08-29, user: "backlog option a … after we diagnose 403 in vs code we will implement the adr") — DEFERRED until the VS Code custom-endpoint 403 is diagnosed/closed, then land as an ADR. **Problem:** provider API keys are stored PLAINTEXT in `~/.localmind/settings.json` under the `api_keys` dict (`backend/src/core/config.py:524` `save_api_key`), protected only by `0o600` file perms (`_secure_write_json`, config.py:448). VS Code Insiders' custom-endpoint config keeps only a *reference* (`${input:chat.lm.secret.<id>}`) in settings.json and stores the value in the OS secret store (macOS Keychain / Windows Credential Manager / Linux libsecret), encrypted at rest — model definitions stay readable, key never appears in plaintext. **Chosen approach (Option A):** use the `keyring` package as the true analog — store the value in the OS store, keep only a `keyring:` marker (or nothing) in settings.json. `get_api_key()` (config.py:552) is already a single choke point: try keyring → `_runtime_api_keys` → env fallback; `save_api_key()`/`delete_api_key()` write/remove in keyring instead of the JSON dict. **ADR must cover:** (1) migration of existing plaintext `api_keys` in settings.json into keyring (one-time, then scrub from JSON); (2) headless-Linux / no-Secret-Service fallback policy (fall back to current 0o600 plaintext or env-ref, documented); (3) new `keyring` dependency + cross-platform test/CI implications. Rejected alternatives: Option B (env/.env `${env:VAR}` reference — key still plaintext in .env, only partial) and Option C (keep 0o600 plaintext — no encryption). Pointers: `backend/src/core/config.py` (`save_api_key` 524, `delete_api_key` 535, `get_api_key` 552, `_secure_write_json` 448, `_runtime_settings_path` 339), provider list in `backend/src/adapters/openai_compat.py`.

---

- [~] **[High, tools/browser] B-2026-08-30-3 (REVERTED 2026-08-30 — hiding a first-class capability was wrong) — `browse` attempted-first and not_installed only discovered via a failed call** (added 2026-08-30 from session syn-0) — **REVERTED per user feedback:** the initial fix hid `browse` from the roster when `shutil.which("agent-browser")` was None. That was wrong — the browser agent is a FIRST-CLASS LocalMind capability, and the PATH check can FALSE-NEGATIVE (npm global bin not on the backend process's PATH), hiding a browser the user actually installed. All gating removed; `browse` is always offered again. The real (already-shipped) mitigation for the original waste is B-2026-08-30-2 (describe_tool iteration refund) + the clean `not_installed` recovery message. Any future improvement here must NOT hide the tool — at most STEER simple GET/JSON fetches toward `web_fetch` via tool descriptions, and/or bundle/document agent-browser install. ORIGINAL ANALYSIS: For a simple JSON GET the agent chose `browse` first; it returned `error_type=not_installed` ("Browser agent is not available. Install it with: npm install -g agent-browser…", `browser_agent.py:52` `shutil.which("agent-browser")` is None), costing an iteration before falling back to `web_fetch` (which succeeded). Two problems: (1) browser availability is known at startup (`_AGENT_BROWSER_BIN`) but isn't gated OUT of the tool roster / plan when absent, so the model wastes a call discovering it; (2) even when installed, a plain `GET …?format=j1` should prefer the core `web_fetch`, not spin up a headless browser. Fixes: hide/deprioritize `browse` from the available-tool set when `agent-browser` is not installed (capability gating), and steer simple GET/JSON fetches to `web_fetch` in the planner. Also: decide whether to ship `agent-browser` as a bundled dep or document install in setup. Pointers: `backend/src/tools/browser_agent.py`, tool-roster assembly, planner intent→tool mapping.

---

- [~] **[Medium, agent/efficiency] B-2026-08-30-8 — Over-thinking after evidence is in hand; "remember X" took 1m28-39s** (added 2026-08-30 from session syn-0) — After `web_fetch` returned the weather JSON, the loop kept "thinking" (Turn 2 total 2m20s) instead of synthesizing promptly; and a pure memory-store ("I meant remember <url>") took **1m39s** with 88s of "thinking" for a one-line fact. Partly the free-tier model + `reasoning_effort` (now clamped to `low` by B-2026-08-30-1), but also: the loop should synthesize as soon as sufficient evidence exists, and trivial store/ack turns should not trigger heavy reasoning. Overall throughput was 3.47 tok/s. Fixes: an "evidence-sufficient → synthesize now" short-circuit (relates to POST-EVIDENCE NARRATION handling), and routing trivial memory/ack intents to a fast path that skips deep planning. Pointers: `backend/src/core/agent/loop.py` (synthesis gating), intent classifier / trivial-input fast path (`core/trivial_input.py`), thinking-aware timeouts (`core/agent/constants.py`). (✅ OVER-THINKER HALF DONE 2026-09-07, Session 438, commit bd0641d + live-verified: evidence-sufficient answer-only call — after a substantive page fetch the next loop call runs tool-schema-free with an answer directive; FORCE_TOOL asymmetry restores tools when the reply narrates a further action; live 184.8s→14.1s on the same weather task, log-proven mechanism lines. The memory/ack half was re-scoped by the owner OUT of this item mid-session ('the overthinker and latency not memory') — the plain 'remember X' phrasing already took the deterministic zero-LLM path; the remaining detector gap ('I meant remember <url>' — a lead-in defeats the start-anchored write cues) is NEW work, not covered here.)

---

- [~] **[High, config/agent] B-2026-08-30-9 — Dead iteration-cap env var + two disagreeing caps (knob silently ignored)** (PARTIAL 2026-08-30: dead-knob half FIXED) (added 2026-08-30, from user Q "why limit iteration that much?") — **DONE (half):** `core/agent/constants.py` now honors `LOCALMIND_AGENT_MAX_ITERATIONS` as a legacy alias (`os.getenv("LOCALMIND_MAX_ITERATIONS") or os.getenv("LOCALMIND_AGENT_MAX_ITERATIONS")`), so the knob is no longer a silent no-op; `backend/.env` switched to `LOCALMIND_MAX_ITERATIONS=25` (local, gitignored) and `backend/.env.example` documents the canonical name + failsafe intent. Verified env=25→25, alias→12, unset→8. **STILL OPEN:** the two-cap disagreement — legacy `core/agent/loop.py` (`MAX_ITERATIONS`, 8) vs the newer framework parent agent (`max_iterations=20`, `agents/parent/agent.py:20`) — is NOT unified; which loop/cap governs a parent turn remains unclear (parent-agent-spec migration). ORIGINAL ANALYSIS: `backend/.env:136` sets `LOCALMIND_AGENT_MAX_ITERATIONS=6`, but NOTHING reads that name: the legacy loop reads `LOCALMIND_MAX_ITERATIONS` (`core/agent/constants.py:33`, default `_MAX_ITERATIONS_DEFAULT=8`) and `config.py:233` documents that the `localmind_agent_max_iterations` Settings field was REMOVED as dead code. So the user's iteration knob is a silent no-op — changing it has no effect, which is confusing during testing. Compounding it: the cap is defined in TWO places that don't agree — the legacy `core/agent/loop.py` uses the `MAX_ITERATIONS` constant (8 / `LOCALMIND_MAX_ITERATIONS`), while the newer framework's parent agent sets `max_iterations=20` (`agents/parent/agent.py:20`, base default `DEFAULT_MAX_ITERATIONS=20` in `agents/base_agent.py:66`). The live run stopped at "6 iterations", matching neither default — so which loop/cap actually governs a parent turn is unclear (the two agent systems aren't unified; relates to the parent-agent-spec migration). Fixes: (1) make the env knob work under the name the docs/.env use — either restore `LOCALMIND_AGENT_MAX_ITERATIONS` as an alias or update `.env`/`.env.example` to `LOCALMIND_MAX_ITERATIONS` and remove the dead line; (2) unify to ONE cap source consumed by whichever loop runs the parent turn; (3) document the failsafe intent (cap a FAILING loop, not ration work) and consider a higher default for capable models. Note: the cap is a failsafe, so the durable fix for trivial-task exhaustion is B-2026-08-30-2 (stop describe_tool waste), not just a bigger number. Pointers: `backend/.env:136`, `backend/.env.example`, `core/agent/constants.py:31-36`, `core/config.py:233`, `agents/base_agent.py:66,75`, `agents/parent/agent.py:20`.

---

### Session note 2026-08-30 — batch fix of the syn-0 issues ("Fix everything and push")

---

Shipped in this session (all with tests; frontend tsc 0 / vitest 360 green, backend touched suites green):

---

### Agent-enhancement effort — kicked off 2026-08-30 (user: "work on agent thoroughly … enhance it drastically … very essential now and in future")

---

Grounded in two live syn-0 sessions (weather via browser). Prioritized workstreams:

---

1. **Tool-result capture** (STARTED — milestone 1 below): browser (and tools generally) results must reach the agent's EVIDENCE, not be left in the browser window.

---

2. **Anti-thrash tool protocols**: teach multi-step tool patterns + a bounded fallback ladder (browse-read → web_fetch → honest report) instead of flailing to the iteration cap.

---

3. **Efficiency**: cut describe_tool round-trips (pre-load likely tools per intent), synthesize-once-evidence-sufficient (B-2026-08-30-8), attack 4-min / ~2 tok/s latency.

---

4. **Measured eval harness**: extend `scripts/live_test_*.py` into a repeatable scenario suite so "drastic" is measured, not vibes. Aligns with parent-agent-spec §40 QUALITY BAR.

---

CONSTRAINT: the browser tool can't be live-tested on the dev Mac (no agent-browser) — browser changes need the user's Windows box to verify.

---

- [ ] **[Medium, agent/tools + frontend/electron] B-2026-08-30-12 — Non-headless browser should surface as LocalMind's OWN branded window (not a detached Chrome)** (added 2026-08-30 by user: "browser non headless should pop up as localmind's custom window if the agent uses no headless") — agent-enhancement effort (workstream: browser UX). Today `browse` runs agent-browser HEADLESS (`browser_agent.py:7`), with no headless/headful control exposed. Request: (1) let the agent (or a setting) run the browser NON-headless so the user can WATCH what the agent does, and (2) when it does, the visible browser must appear as a LocalMind-integrated/branded window — part of the app — NOT a bare, detached Chrome window. **Two pieces:** (a) plumb a `headless` flag through `browser_agent` → the agent-browser invocation (per-call `{"action":"open","headless":false}` and/or a global setting/env, defaulting headless); (b) present the headful session inside LocalMind. **Approach options (needs feasibility check):** embed via an Electron `BrowserView`/`WebContentsView` in a LocalMind "Browser" panel pointed at the SAME session (best integration — depends on whether agent-browser exposes its CDP endpoint / can attach to an app-managed Chrome), OR launch agent-browser headful and adopt/brand the window (position, title, icon), OR render a live view (screenshot/CDP screencast stream) into a workspace panel while the agent drives. LocalMind is Electron (`electron/main.js`, `electron/preload.js`, `electron/tray-icon.js`), so a BrowserView panel is viable. Cohesion matters — the browser is now a first-class capability (see B-2026-08-30-3 revert), so when visible it should feel like LocalMind, not a popup. Pointers: `backend/src/tools/browser_agent.py` (CLI args, `_run_browser_cmd`), `electron/main.js` (window/BrowserView mgmt), `frontend/src/components/panels/` (a Browser panel / the Agent Workspace), agent-browser's CDP/headful docs. Prereq: confirm B-2026-08-30-10/-11 work against the real CLI first.

---

### Feature: system-awareness — kill the sysinfo reflex + complete tool summary (user 2026-08-30, phased, each phase its own session)

---

Reframe: glm-5.3-flash is the LATEST/BEST model (NOT weak — glm-4.5-flash is the weak one per live-testing.md). So the sysinfo tool-first reflex and wrong tool selection on the documented suite (TS-1 weather → sysinfo×4; TS-2 file-search → sysinfo; AM-1/2/3 pre-existing B-25-9) are 100% SYSTEM bugs, not model limits. Two root gaps found: (a) the first-call/bootstrap prompt gave tool NAMES only, no purpose → blind first tool choice; (b) sysinfo is live-only — never collected at boot, stored, or injected, so the agent has zero system knowledge until it calls the tool (and over-calls it). User-approved design: injection = **BOTH** (static system summary always in the system prompt; full/mutating in memory + sysinfo tool for deep queries).

---

- [~] **[High, agent/prompt+memory] B-2026-08-30-17 Phase 3 — Inject cached sysinfo: static summary → system prompt** (✅ CODE DONE 2026-08-30, prompt path live-verified; memory sub-piece deferred) — SHIPPED: boot-set cache (`system_snapshot.set_cached_summary`/`get_cached_summary`, set in `app.py` startup from `SystemInfoStore.get_summary()`), injected into the first-call/bootstrap prompt via `prompts._system_env_line()` with guidance ('you already know the machine — answer OS/CPU/RAM/disk directly; only call sysinfo for processes/network/live re-read'). Tests: `test_system_snapshot.py` +2 (summary in bootstrap prompt; empty when cache unset). **LIVE (bankofai/glm-5.3-flash): boot cache ran (8 static/3 mutating logged) AND the agent did NOT call sysinfo for 'how much RAM/disk?' (tools=[], reflex suppressed) — but the FINAL ANSWER was blocked by a bankofai 429+120s timeout (free-tier throttle from heavy same-session testing), NOT code. Per live-testing.md: not claiming success through the rate limit — reflex-suppression + boot-cache are verified; the answer-from-summary is unit-pinned and needs one clean un-throttled run to confirm end-to-end.** DEFERRED (own follow-up): the 'full/mutating → memory' half of Both (store snapshot as retrievable memory facts) — the sysinfo tool + DB cache already cover deep queries, and 'available in prompt' satisfies the core requirement. Also TODO: inject the summary into the non-bootstrap prompt for call-2+ robustness. ORIG: a compact one-line `System:` summary (from the Phase-2 static cache) injected into every turn's system prompt by default so the agent already knows the machine; the fuller/mutating detail stored as memory facts surfaced via the existing memory-retrieval path; sysinfo tool stays for deep/live queries. Verify (live) the agent stops reflexively calling sysinfo for basic system questions AND still answers them correctly from the injected summary. Pointers: `core/agent/prompts.py` (system-prompt assembly), memory injection path (`core/memory*.py`), Phase-2 cache.

---

### Loop-discipline re-architecture (§40 quality bar) — seam-first, incremental, de-patching (user 2026-08-31: "don't just patch")

---

Root: `core/agent/loop.py` (8,539 lines) accreted ~10 overlapping discipline detectors (narrates_pending_action, narrates_after_evidence, answer_hedges_after_evidence, tool_error_recovery_directive, _recovery_nudge_tail, _message_implies_tool_action, gate_force_tool, zero-tool force, empty-response recovery, DSML/MiniMax interception, _synthesis_failure_fallback). They ALL judge one event: what did this model turn do? Plan: ONE seam (act|answer|incomplete + a single recovery), migrate the detectors onto it one at a time (guard count DOWN), each behind its existing tests. NOT a rewrite, NOT another guard.

---

- [ ] **[Medium] context-quality pass — the paired half** (◐ partial 2026-09-08 audit — the measurement seam the item requires SHIPPED: turn_outcome.py (ACT/ANSWER/INCOMPLETE + Recovery) wired at the final-answer gate with the per-turn "turn outcome=X recovery=Y" log + test_turn_outcome.py. REMAINING: the paired half itself — the deliberate context-completeness guarantees and the before/after INCOMPLETE-rate measurement) — after the seam lands: ensure every turn's context is consistently complete (stable tools + current state + last observation + the one act-or-answer contract) so the model earns INCOMPLETE less often. Measure INCOMPLETE-rate via the new `turn outcome=` log before/after.

---

- [~] **[reference] Loop-discipline re-arch — FORCE_TOOL live-verified + scope boundary noted** (2026-08-31) — Live (bankofai sandbox): a delete request ACTUALLY deleted junk_a.bin + junk_b.bin and preserved keep.txt; the seam logged `turn outcome=answer recovery=none` (model acted cleanly, no spurious recovery). The consolidated final-answer gate (4→1, -140 lines) is verified end-to-end. **Scope boundary (intentional):** the empty-response-after-reasoning region (~loop.py:5555) is NOT a seam-migration target — it is STREAM-LIFECYCLE recovery (drain the stream, force thinking off, keep role alternation, bounded cap), a distinct concern from final-answer discipline. Forcing it onto the turn-outcome seam would be over-engineering, not de-patching. The seam owns final-answer classification; stream-lifecycle recovery stays its own mechanism. Remaining principled work: (a) OPTIONAL fold of the zero-tool-force (no tools ran + plan_steps) into the seam's FORCE_TOOL(tools_ran=False) case if clean; (b) the CONTEXT-QUALITY half — measure INCOMPLETE-rate via the `turn outcome=` log and reduce it at the source.

---

## 2026-09-02 — Backlog marking sweep (ZCode, Session 407)

---

User: "most were fixed but not marked." Verified every unchecked entry against git

---

history (ID-tagged commits), `agents/sessions.md` closure notes, collab release

---

events, and direct code/test inspection. **40 entries checked off** with dated

---

evidence notes (in place, per Step 15). Categories:

---

- **Fixed + shipped** (commit or session evidence): B-2026-08-12-3, -14-5, -14-6,

---

  -17-5, -17-6, -17-10, -18-3, -20-1, -20-2, -20-4, -20-6, -20-7, -20-11, -20-19,

---

  -22-1 (both entries), -22-2, -22-3, -22-4, -22-5, -23-13, -23-14, -23-15, -24-16,

---

  -25-8, -30-7, -30-15 + loop-discipline Steps 4-5.

---

- **Superseded/parked by ADR-53** (Parent-only scope): B-2026-08-12-1, -12-2, -12-5,

---

  -14-2, -14-3, -16-11, -20-3 (standing).

---

- **Superseded by newer entry**: B-2026-08-15-4 (→ B-17-13), B-2026-08-18-4 medium

---

  dup (→ sharpened High).

---

- **Demoted/closed by evidence**: B-2026-08-17-3 (S291 disproved hypothesis),

---

  Step 3 (intentional scope boundary).

---

**Still genuinely open (~50)** — spot-checked, no fix evidence: the newest

---

Session-404/405/406-era items (B-25-4 Worker-report leak still reproduces in

---

suite-results-404; B-25-7 fast-path context loss; B-25-12 destructive-classify;

---

B-25-13 gate_force_tool no-op — flaws log still open; B-30-8 over-thinking —

---

d41327c explicitly deferred it; B-30-12 branded window; B-30-17 CRLF verify —

---

REPRODUCED again this session), the token/efficiency family (B-17-1/8/9/11/12,

---

B-16-6/8/9, B-15-14), ADR-17/18-era UI items (B-11-3, B-12-4), frontend features

---

(B-23-20/24, B-24-7/17, B-25-2/3/10), and standing/long-term items (B-24-8,

---

B-07-31-10, Anthropic live-verify).

---

**Incident:** `context-sync verify` failed on 2 core files this session —

---

confirmed the known B-2026-08-30-17 Windows autocrlf false-positive (git blobs

---

match the manifest exactly; only CRLF-on-disk differs). No rollback needed;

---

item remains open.

---

- [ ] **B-2026-09-04-1** (P2, from S416 addendum): `qwen3.8-flash` (and other bankofai free models beyond deepseek-v4-flash/hy3) are missing from `MODEL_CONTEXT_WINDOWS` (backend/src/adapters/openai_compat.py:50) — they silently fall back to the 32,768 default. bankofai's `/v1/models` exposes NO context_length metadata (probed live 2026-09-04: only id/owned_by/supported_endpoint_types), so a value must come from provider docs/user research — do NOT guess. A too-small window makes the context meter over-predict degradation; verify before adding. Also consider: should the meter warn when it's running on the "default" fallback (unknown model) instead of showing a confident percentage?
  → **RESOLVED (S416 addendum 2, `6d4b45e`):** qwen3.8-flash = 1,000,000 added (owner-verified from B.AI docs: max input 991,808 / output 131,072); the "default" fallback is no longer silently presented — the models route omits context_window for unknown models and the meter shows "window unknown" instead of a fake percentage; fetch-first probe added for providers that DO expose metadata (OpenRouter/vLLM-style).

---

- [ ] **B-2026-09-04-2** (P3, from S416 addendum 2): other bankofai free models (`qwen3.8-max`, `qwen3.8-27b`, `hy3`) still rely on the conservative default or partial entries — bankofai exposes no metadata, so values need owner-verified doc lookups like qwen3.8-flash's. The fetch-first probe + honest "window unknown" UI make this low-urgency (no more lying percentages), but accurate entries improve meter fidelity whenever the user provides documented values.

---

- [ ] **B-2026-09-05-1** (P3, from S423 file-reading milestone — deferred by design): PDF scanned-page routing — when `_parse_pdf` extracts near-zero text from a page (image-only scan), route that page's rasterized image through the OCR path (`_parse_image`/pytesseract) instead of returning empty text. Foundation is now in place (OCR deps installed + image reader reachable); needs a rasterization step (PyMuPDF page.get_pixmap) and an honest "this page is a scan, OCR'd" note.

---

- [ ] **B-2026-09-05-2** (P3, same milestone): embedded-image EXTRACTION — `_parse_docx` now *enumerates* embedded images (count note), but does not extract them; wire an opt-in extraction (docx = zip; images live in `word/media/`) feeding the OCR path. Same for PDF page images via PyMuPDF.

---

- [ ] **B-2026-09-05-3** (P4, optional): screenshot-to-OCR fallback for formats no parser can render (legacy OLE2 .pub/.doc) — requires opening the file in a native app or converter, then OCR of the rendered page. Heavy; only if .pub-family files actually recur (the user's Documents has one 2022 .pub superseded by a .docx).

---

- [ ] **B-2026-09-05-4** (P3): the ~23-failure Windows backend baseline (find_path ×13, runfile_redirect, csv ×2, sql ×2, observe, process_tool, propose_edit, json_tool, file_writer_l3, intent_tool_scoping ×2, goal_derive ×4, goal_interpreter, session_workspace ×2, browser_open, parent_completion_floor ×2, empty_agent_fix, server_port_check) needs the deferred peer pass — several families (find_path KeyErrors, permission-gate asserts) look like a shared fixture/env cause, not 23 independent bugs. Failure set verified identical to d727030 baseline in S423. **UPDATE S431 (Kwame), commit c340f3d — of the 22 tests/tools failures: 0 were touched (that suite's families remain open here), but the OTHER 14 failures this file's list named (goal_derive ×4, goal_interpreter, session_workspace ×2, browser_open, parent_completion_floor ×2, empty_agent_fix, server_port_check, intent_tool_scoping ×2) are ALL FIXED — 4 real product bugs (criteria-gate misroute on "pytest"-containing paths; Windows port-probe binding over live listeners; chat-mode memory_facts dropped from the prompt; os.sep leaking into the files-listing contract) + stale test contracts updated. Main suite now 2305 passed / 0 failed. tests/tools remains the one open family (615 passed / 22 failed).**

---

- [ ] **B-2026-09-06-1** (P2, feature — owner-directive backlog, S424): **Experiential Labs model-gateway provider** — implemented 2026-09-05 (`ec9b6b7`) and REVERTED same-day-plus-one at the owner's "not right now" directive (`645b5c4`, forward-out; nothing live ever used it). NOT rejected — timing only. Full research + design are preserved in **ADR-58** (`plans/decisions.md`); re-apply with `git revert 645b5c4` (expect a CHANGELOG.md context conflict — resolve by re-adding the entry to the top `### Added`). The feature: OpenAI-compatible gateway `https://api.experientiallabs.ai/v1` — one `xpl_` Bearer key reaches 500+ catalog slugs with automatic waterfall failover; billing is BYOK pass-through or platform credits per model; public keyless catalog at `/api/models` (verified 2026-09-05: glm-5.3-flash ctx 1,310,720, tools, ~$0.075/M input; 429 `insufficient_quota` is non-transient — already covered by `error_normalizer._PERMANENT_QUOTA_MARKERS`; keyed `/v1/*` → uniform 401 `invalid_key`). The revert removes: ProviderConfig entry, Settings `experiential_model` + env-key map line, SettingsModal PROVIDERS entry, models.py live-list tuple membership, `.env.example` key+model lines, `MODEL_CONTEXT_WINDOWS["glm-5.3-flash"]=1310720`, 3 registry tests, changelog entry — each is a copy-paste restore from ADR-58/the revert parent if a fresh re-add is preferred. **When resumed, owed:** ADR-58 smoke test with a real key — (a) keyed `GET /v1/models`, (b) isolated-8765 `/api/chat` with `LOCALMIND_ADAPTER=experiential` (copy settings.json into the scratch home; never print values), (c) tool calls + streaming end-to-end — then mark ADR-58 tested. Owner-side gotcha: after (re-)adding any provider, the backend must be RESTARTED before saving its key, or the stale process rejects with "Unknown provider. Valid: [...]" (all validation derives from PROVIDER_CONFIGS at boot).

---

 properties- [x] **B-2026-09-06-2** **Chat export drops user messages; sidebar message count is assistant-only** — The JSON export of session-1788669567862 (`localmind-chats-1-2026-09-06.json`, exportedAt 04:42Z ≈ 07:42 local — AFTER the 07:39–07:40 conversation) contains 3 messages, ALL `role:"assistant"`, while the UI transcript for the same chat shows 3 user + 3 assistant messages; the sidebar shows "3 msgs" (matches the assistant-only count). The auto-generated title "Casual how's it going check-in" could only come from user content → user messages ARE persisted; the export path (or the API source it reads) filters them out. Fix: include ALL roles in the export and in the message count, in original order; regression-test an export of a mixed-role session against the UI transcript 1:1. Pointers: the chat-export endpoint/serializer, the sidebar message-count source (likely the same query/filter). Coordinate with B-2026-09-06-3 (same surface — one agent can take both). **RESOLVED S433 (Mei), commit ad4e3fc — root cause was persistence, not the export: the deterministic epilogs (trivial/conversational fast path, memory write) returned before the user-message persist line; they now await it immediately before the reply, so every turn leaves a user row and the count/preview see it. Regression tests: tests/core/test_fastpath_user_persist.py (isolated tmp home). B-2026-09-06-3 still open, builds on this surface.**

---

- [ ] **B-2026-09-06-3** (P1, backend/export — owner directive 2026-09-06: "the json export data it should capture everything"): **Full-fidelity export schema (v3)** — The current v2 export carries todos[] + per-message performance{} but omits: user messages (see B-2026-09-06-2), thinking/reasoning blocks (the UI shows "Thinking 1.1s" + streamed prose — the data reaches the SSE channel), model/provider identity per chat/turn (UI shows "qwen3.8-flash · bankofai"), agent-workspace turn metadata (per-turn durations, tool-step counts, lifecycle), and real dates (`formattedDate` is time-only "07:40" — ambiguous across days). Fix: bump the export `version` (v3), include every persisted field per chat (all message roles, thinking blocks, performance, model/provider info, todos, ISO-8601 timestamps), keep v2 readable (backward-compatible import). Coordinate with B-2026-09-06-2 (same surface). **RESOLVED S431 (Kwame), commits 5a7d3f4 + cad31f1 + merge 02b42e0 — export v3 shipped: version 3, ISO-8601 per chat (createdAt/lastActive) and per message, raw epochs preserved end-to-end (timestampEpoch/createdAtEpoch/lastActiveEpoch in client+API), per-turn model/provider lifted from persisted metrics (identity stamped only on model-produced legs; composes with the S434 synthetic-canned contract), fast-path Thinker/conversational thinking persisted; every v2 key intact (display strings kept as timestampDisplay). Regression: exportChats.test.ts v3 suite (mixed-role 1:1, v2-key compat, ISO dates, identity) + tests/api/test_session_identity_export.py endpoint pass-through; live-verified on 8765.**

---

- [ ] **B-2026-09-06-5** (P1, testing/data — S431 live finding): **Test/e2e runs pollute the REAL user chat store (~40 residue chats + 7 empty chats)** — The live sidebar shows ~40 chats created 06:34–06:38 the same morning with e2e-style titles ("write hello.py", "create hello world repo" ×2, "find weather", "show projects", "run the tests", "build the app", "say hello", "research this and compare the sources", "X", "Remember", "Weather", "Search", "inspect the project") and single-word previews ("done", "ok", "planned", "fallback", "answer", "Verified result"), plus seven "0 msgs" chats. Suites are writing chats into the production LOCALMIND_HOME data dir instead of an isolated home. Fixes: (a) audit test fixtures/harnesses for default data paths and force the isolated LOCALMIND_HOME harness (system/live-testing.md) for anything that can create chats; (b) one-time cleanup of the residue — CAREFUL: real chats are interleaved (the Sep 03–05 CV/news/weather sessions and the 05:0x–07:40 real usage must survive) — build the delete-list from exact title+timestamp pairs and get owner confirmation BEFORE deleting. Verify: run the offending suite against an isolated home and assert the real store gains zero chats.

---

- [ ] **B-2026-09-06-6** (P3, frontend/UX — S431 live finding): **Sidebar chat previews render raw markdown** — Previews show `**bold**` asterisks and raw `|---|` table pipes (e.g. "Kitengela right now (≈5 AM): 🌥️ **15°C (59°F)** — … | | |---|---|"; same in the EPL-fixture and Kenya-president previews). Strip markdown to plain text for previews (single line, truncated). While there: the chat titled "Assistant capabilities overview" shows a weather answer as its preview — check which message feeds the preview (first vs last assistant message). **RESOLVED S431 (Kwame), commit 5a7d3f4 — new previewText.stripMarkdownToPreview() (bold/tables incl. |---| separator rows/links/fences/headers/quotes/bullets → single plain line) rendered at display time in LeftPanel; the stored last_message keeps raw markdown for export fidelity. Verified: the preview source is the LAST message (any role), so the "capabilities overview" weather preview was the latest message, not a selection bug. 8 unit tests.**

---

- [ ] **B-2026-09-06-7** (P2, frontend/arch — S431 live finding, standing-decision conflict): **Agent Workspace panel copy contradicts the Parent-only architecture decision (ADR-53)** — The panel is titled "Parent loop and delegated work" and its helper text reads "Child agents receive an isolated task and report back to the parent." — advertising child-agent delegation that is parked/legacy surface under the standing Parent-only decision (ADR-53, 2026-08-20). Fix: reword to parent-only language (the panel tracks the Parent's turns and tool steps — say that); check the panel renders no delegation affordances for the parent. Frontend copy only — no loop changes; ADR-53 stays authoritative. **RESOLVED S431 (Kwame), commit 5a7d3f4 — header now "Parent loop — turns and tool steps", footer now "One active agent: the Parent runs every turn and tool step itself."; panel renders no delegation affordances.**

---

- [ ] **B-2026-09-06-8** (P3, from S428): Thinker cadence/depth tuning from live usage. ADR-60 made post-tool consults concurrent and per-tool; the knobs live in `backend/src/core/agent/loop.py`: `_THINKER_CONSULT_CAP` (5/turn) and `_THINKER_TOOL_SKIP` (todo_write, describe_tool, create_plan, add_subgoal, update_subgoal). Gather real multi-turn usage and tune: is 5/turn right, or should the cap scale with iterations/complexity; any tool in the skip-list firing consults wastefully (or any evidence-bearing tool being skipped); consult token spend vs decision value in traces (the prompt's "depth proportional to the decision" is prompt-driven — consider whether a size/effort dial is warranted). The live-testing bar applies (agent-loop change): before/after on bankofai + the weak-model trace. Related: ADR-60, ADR-57.

---

- [ ] **B-2026-09-06-9** (P2, from S428): ADR-57 slice 4 — right-size the Thinker role. The consult is a lightweight reasoning role (facts/ambiguities/next-step, ~1-2K tokens, no tools); since S428 it runs concurrently so it costs no wall-clock, but it uses the SAME adapter+model as the main loop — on expensive providers its token spend accumulates and on slow ones its 5-30s occupies the overlap window. Design (MODEL-AGNOSTIC per the standing rule — a role/effort choice, never a "weak model" special case): a configured reasoner adapter/model pair (Settings UI + env), or a lowered `reasoning_effort` for the consult role (ADR-41 lever), or per-role adapter selection if the kernel already has one. Must hold: consult quality (the structured analysis still steers the loop — judge on the LIVE bar with before/after traces, not unit tests) and the no-machinery prompt contract (ADR-59). Touchpoints: `backend/src/core/agent/loop.py` (`_BackgroundConsult`, both consult sites), `backend/src/core/agent_runtime.py` fast-path consult, config/settings surface. Coordinate via the event trail — loop.py is a shared surface.

---

- [ ] **B-2026-09-06-10** (P3, backend/shutdown — S432 live finding): **Title-generator races SIGTERM teardown — adapter call fires after connections close** — observed live on the isolated-8765 smoke (`scratch/server-sync-check.log`): `Received signal SIGTERM — shutting down gracefully…` → `[shutdown] all adapter connections closed` → THEN `ERROR adapters.openai_compat — Unexpected error calling bankofai: ` (EMPTY message — the exception text is dropped, which cost a diagnosis round) + `WARNING core.title_generator — [title] adapter error for s332-apple_math-…`. The background title task is fire-and-forget; the shutdown path closes adapter connections without cancelling/awaiting in-flight background tasks (title generation, thinker consults), so the task's provider call hits a closed client. Benign to the user mid-session (the turn is already complete) but every shutdown with an active chat logs a spurious ERROR pair and silently loses that chat's title. Fix: in the SIGTERM path, cancel background tasks and await them (or shield + short timeout) BEFORE closing adapter connections; while there, make `openai_compat`'s "Unexpected error" log include the exception text. Full mechanism in flaws/log.md (2026-09-06, Session 432 entry).

---

- [ ] **B-2026-09-07-1** (P2, frontend/backend — S437 live finding, owner symptom "agent workspace is disconnected"): **Fast-path/conversational turns persist no workspace artifacts — the Agent Workspace panel resets on reload or session switch.** The panel hydrates from the last assistant message carrying `agentRuns` (`useLocalMind.ts` run-tree restore) and fills live from SSE during streaming; but `build_workspace_artifacts()` is invoked only on the parent-agent-loop finalize paths (`agent_runtime.py` ~1715-1903) — the trivial/conversational fast-path epilog (~line 1300) persists metrics + thinking but `agent_runs`/`agent_phases` stay NULL. Every chat that stays on the fast path (greetings, capability questions) therefore shows turn cards live, then an empty panel after reload — panel and history disagree. Fix options: (a) build minimal turn-shell artifacts on the fast-path epilog (task=label, phases from the stage_timings it already emits, tools=0), or (b) have the panel render a distinct "direct-answer turn" card from persisted metrics for messages without agentRuns. (b) is frontend-only; (a) changes the persisted contract — coordinate before touching the epilog (same surface as the S434/S431 metrics work). Evidence: session-1788766660727 rows have `agent_runs=NULL` for both turns while the panel showed 2 live turn cards.

---

- [ ] **B-2026-09-08-1** (P3, frontend lint — S441 follow-on to the closed B-2026-08-17-13): **Next eslint ratchet tranche below 53.** After S441 (errors 9→0, warnings 84→53, cap 71→53), the remaining debt by rule: 15 `@typescript-eslint/no-explicit-any` in `frontend/src/components/chat/ChatMessage.tsx` (react-markdown v10 component props — the `inline` prop on `code` is a pre-v9 pattern, check how `components={{code}}` typing works in v10 before typing), 24 `react-hooks/set-state-in-effect` (WARN-level by config; mostly intentional mount-refresh/derived-state patterns — assess each honestly, several may warrant `allowAsConst`-style refactors rather than suppression), 9 `react-refresh/only-export-components` (mostly vendored `components/ui/*` shadcn files — consider a dedicated override rather than file splits), 5 `react-hooks/exhaustive-deps`. Same discipline as before: pay down in safe tranches (tests green per tranche), lower `--max-warnings` in scripts/ci-check.sh as you go, never raise it.

---

- [ ] **B-2026-09-09-1** (P3, tests/flaky — S447 exit-gate finding): **`tests/tools/test_process_tool.py::test_stop_already_stopped` is flaky on Windows.** The S447 exit gate failed with it as the single NEW failure beyond scripts/pytest-baseline.txt (23 failed vs the documented 22); the identical test passes in isolation (twice: direct `backend/.venv/Scripts/python.exe -m pytest` and via `sh scripts/venv-run.sh pytest`). Likely a process-timing race (stop/signals vs Windows process teardown) under full-suite load. My session's diff contained zero product code (ledger files + package.json allowScripts only), so a regression from S447 is excluded. Fix direction: read the test's synchronization (probably needs a poll/until-terminated wait instead of a single check after stop()); if it uses a fixed sleep, replace with a deadline-bounded poll. Gate context: ci-check.sh's baseline comparison is failure-SET based, so a flake shows as a hard "NEW failure" — if this recurs, consider a documented-flaky allowlist (ratchet rule: named, justified, never silent).

---

- [ ] **B-2026-09-09-9** (P2, backend/robustness — S449 batch-8 live finding; initially filed as B-2026-09-09-7, renumbered twice — -7 went to S453's CI-integrity finding (landed first, flagged by Nia/S454 release event), and -8 went to Zola's S455 memory-ingest follow-up, whose filing (commit 7143ef7f, 20:18) predates this item's -8 renumber (commit a41c5f74, 21:02) — the landed-first rule again, applied by the B-2026-09-10-2 owner call): **The isolated trace server can terminate SILENTLY under provider 429 storms — no traceback, no graceful-shutdown log, and the client sees raw "connection refused" with zero explanation.** Observed twice in one hour on the isolated 8765 harness (bankofai 429-storm window, ~68 429s logged in the run): (1) mid-stream connection kill surfaced to the client as `[WinError 10054]` on the SSE request while the server stayed up; (2) later the same hour the server process VANISHED between two turns — the log's last line is a normal adapter 429-retry (`attempt 2/3`), then nothing: no Python traceback, no SIGTERM handler output, no `shutting down gracefully` — the next turn got `[WinError 10061] No connection could be made` and the harness limped through its remaining conversations collecting per-turn errors. Evidence preserved: `scratch/server-death-evidence-s449.log` (tail ends mid-retry) + per-turn client errors in `scratch/edge-sets-2026-09-09-16*.json`. Mechanism UNKNOWN from these traces (candidates a worker should discriminate: native crash in uvicorn/httpx under client-abort during SSE + adapter retry loop; Windows OOM; something in the keepalive/shield path of `chat.py:_event_stream` — the ONE traceback in evidence, from a DIFFERENT earlier run, is the settings-less boot's API-key failure and unrelated). Worker tasks: (a) add a last-gasp crash surface — faulthandler + a wrapper that logs ANY uncaught/native exit of server.py to a file; (b) repro/verify under a mocked 429 storm (no provider needed: force the adapter to 429) while holding an SSE connection open and aborting it client-side; (c) make the client-facing failure honest (a dead server should never look like "provider rate-limited" to the user — the engine's own fallback text can't fire when the process is gone, so the SSE contract for process death needs a definition). NOT claimed to be: anything about model quality — this is process-robustness only. Repro attempt: fire `scripts/lm_edge_sets_b8.py --convs OTT-26` repeatedly inside a real 429 storm, or (better) the mocked-429 route in (b).

---

- [ ] **B-2026-09-09-7** (P2, testing/CI-integrity — S453 finding while running the exit gate): **The tests/tools + acceptance-gate cluster is order/hash-seed dependent — the full-suite failure set is NONDETERMINISTIC (7 ↔ 22 across two back-to-back runs on the same tree), so scripts/pytest-baseline.txt cannot be refreshed reliably and ci-check.sh's baseline comparison flaps.** Evidence: run A = 7 failures (find_path ×5, json/observe/propose_edit/sql path-asserts), run B minutes later = 22 failures (run A's 7 + the rest of the documented-baseline set) on the identical tree; test_find_path.py alone fails 13, csv+sql alone fail 3, together 15 (cross-file state leak). Pinpointed mechanism for one member: `tests/core/test_acceptance_gate.py::test_is_coding_done_all_criteria_met` passes cwd=None → `core/agent/verify.py:195` falls back to `os.getcwd()` and REALLY stats `<repo-root>/hello.py` (`candidate.is_file()/stat()` — the test's `patch("core.agent.verify.os.path.isfile")` does not intercept the pathlib call), so the verdict depends on whether an earlier test happened to create `hello.py` at the repo root (residue also explains why the main checkout passes where fresh worktrees fail). Fix direction: (1) make the criteria verifier's filesystem checks honor cwd injection + patchability (tmp_path-based cwd in is_done tests), (2) hunt the remaining cross-file state leak (allowed-folders config / caches in tests/tools — find_path/json/observe/propose_edit/sql all assert against allowed-path behavior), (3) only THEN refresh scripts/pytest-baseline.txt from a stable repeated-run set. The stale 22-entry baseline + flapping gate is NOT fixable by editing the baseline file alone. (Owner-visible symptom until fixed: exit gate's ci-check pytest step fails with a different "new failures" list run to run.)

---

- [ ] **B-2026-09-09-8** (P3, memory/ingest — follow-up to B-2026-09-09-6): **Quantified multi-fact Remember writes store the joined facts as ONE blob row.** "Remember two things: my project is called Falcon and my sister's name is Ama" now extracts cleanly (framing stripped by the S455 extractor, 7cc8d9e8) but lands as ONE vector_facts row `my project is called Falcon and my sister's name is Ama` — so a later "what is my sister's name?" must match the whole blob's keywords, and the two facts can never be updated or recalled independently. Fix direction (NOT in the -6 scope by design — clause boundaries with "and" are ambiguous: "my sister's name is Ama and I like her cooking" should split; "I use FastAPI and uvicorn" should probably not): split on explicit enumeration cues ("two things", "first/second", "1) 2)", "; " list shapes) rather than bare "and", cap per-write facts, and keep the one-fact path unchanged. Repro: same OTT-30 probe in `scripts/lm_edge_sets_b8.py`, then `SELECT content FROM vector_facts`. Verify on the live bar (store+echo on real provider).

---

- [ ] **B-2026-09-10-4** (P2, test hermeticity — S458 finding at exit gate): **Two "grounded date" acceptance-gate tests hard-code the day they were written — time-bomb failures the day after.** `tests/core/test_injected_context_gate.py::TestGroundedClass::test_date_question_with_real_weekday` and `tests/core/test_acceptance_gate.py::test_gate_accepts_zero_tool_date_answer_without_replan` pass the literal "Today is **Wednesday, September 9, 2026**" and expect validity against the REAL clock — both failed 2026-09-10 (proved in isolation: 2 failed in 2.47s). These are the ONLY two NEW failures in ci-check beyond the documented 22-failure Windows baseline (S458 run, 24 failed / 3023 passed); S457's macOS run was green because the dates still matched. Fix shape: compute the expected date string in-test (`datetime.now()`) or freeze the clock at the seam the checker reads — never hard-code today's date in a test that consults the real clock. (Set by S458, 2026-09-10) **Addendum (S465, 2026-09-11):** the exit gate's NEW-failure set shows a THIRD member of this family — `tests/core/test_acceptance_gate.py::test_gate_still_rejects_zero_tool_fabricated_date` — same hard-coded-date root cause, same fix shape; this item's scope is now all three, still the sole exit-gate pytest blocker.

---

- [ ] **B-2026-09-10-5** (P3, tools/browser — S460 sweep): **Live-verify the browser tool family against a real `agent-browser` install** — B-2026-07-31-4 (BrowserAgent DOM upgrade), B-2026-08-30-10 (content capture + `open` fix) and B-2026-08-30-11 (batch/extract/links) all shipped unit/e2e-mocked but were explicitly left UNVERIFIED against the real CLI (no agent-browser on the dev machine — still true on this Windows box, 2026-09-10). Also owed from that workstream: prompt-steering so the agent PREFERS `batch` for multi-step browse flows, and the bounded browse→web_fetch fallback-ladder decision (cf. B-2026-08-30-3's steer-don't-hide rule). Prereq: `npm install -g agent-browser`; completion = live before/after per live-testing protocol. (Set by S460 — supersedes the verification residuals of those three swept tombstones.)

---

- [ ] **B-2026-09-10-6** (P3, frontend/tools UI — owner-requested proposal): **One shared tool display-alias mechanism; today the human-facing tool names live in two ad-hoc copies.** `frontend/src/components/chat/ToolSteps.tsx` has a hardcoded `toolLabels: Record<string, string>` map (line ~59) and `frontend/src/components/panels/AgentWorkspace.tsx` has its own `toolLabel()` helper (line ~50); both fall back to `name.replace(/_/g,' ')` + capitalize when unmapped. They can drift, and every new tool (e.g. `dir_explorer`) must be added in both places. PROPOSED MECHANISM: one shared module `frontend/src/lib/toolDisplay.ts` exporting `TOOL_DISPLAY_ALIASES: Record<string, string>` plus a single `toolDisplayName(rawName)` helper (same fallback heuristic), imported by ToolSteps + AgentWorkspace (+ any future surface); seed entries `dir_explorer: "Explorer"` and `browse: "Browser"` (owner-stated UI names, 2026-09-10); aliases are display-only — never sent to the model. Optional later: per-tool icons in the same module. Acceptance: both components render identical labels from the one source; a unit test pins the alias map. (Set by S459, 2026-09-10)
---

- [ ] **B-2026-09-10-8** (P2, agent/tool-surface — S464 finding): **`grep_search` is registered and routed but sits in NO model-facing tier, so the model can never call it.** `backend/src/tools/grep_search.py` registers `grep_search` under `Intent.GREP_SEARCH` (B-2026-08-23-31, commit `f632ca6`), and `agents/selection.py` + `agent/tool_dispatch.py` both map that intent — but the name is absent from `TOOL_DEFINITIONS`, `CORE_TOOL_NAMES` AND `LONG_TAIL_TOOL_NAMES` in `backend/src/core/agent/tool_schemas.py`. It was never exposed, not dropped later (`git log -S'"grep_search"' -- tool_schemas.py` is empty); the tier-split assertion `CORE | LONG_TAIL == catalog` passes only because it is in no tier at all. Live cost (S464, bankofai/qwen3.8-flash): the prompt "Search all text files in my Documents folder for the word 'invoice'" selected `shell` and hand-rolled `grep -rniE`, because the one bounded content-search tool is invisible — and the shell guard deliberately PERMITS bounded greps (B-2026-08-25-1), so nothing fails loudly. DECIDE one: (a) expose it — add to `TOOL_DEFINITIONS` + a tier, `AGENT_ALLOWED_TOOLS`, an `INTENT_TOOL_SCOPES` entry, and a real classifier route, minding Session 400's "one search front door" rationale (a second name-affinity search tool can re-split weak-model traffic), then live-verify selection per ADR-40; or (b) retire it — delete the registration, the `Intent.GREP_SEARCH` member, its `selection.py`/`tool_dispatch.py` routes, and `tests/tools/test_grep_search.py`. Until one lands, the explorer harness's `content_search` probe cannot pass. (Set by Elena/S464, 2026-09-10)

---

- [ ] **B-2026-09-11-1** (P2, observability/benchmark — S465 finding): **`provider_usage` never reaches the SSE `done` event, so per-turn token cost is unmeasurable from the outside.** The agent loop accumulates per-call usage (`_provider_usage` → `total_prompt_tokens`/`total_completion_tokens`/`llm_calls`) and yields it on the final chunk (`StreamChunk(done=True, usage=...)`), but the wire `done` event is bare `{"type": "done"}` — verified live on bankofai/qwen3.8-flash (`scratch/sse-KIT-2-*.sse` from the S465 run; the server log likewise carries zero usage lines). The conversational fast-path additionally emits `provider_usage={}` (agent_runtime.py, the `_is_canned`/fast-usage branches), so even a wired emitter would show nothing on direct answers. Consequence: the token-efficiency half of the benchmark design (input/output tokens per test, quality-per-token score, the harness's efficiency summary) records null for every test even though the harness plumbing (`_usage_tokens`) is ready. Fix shape: forward the loop's usage dict into the SSE done payload, and report the fast-path's real usage instead of `{}`; then re-run a benchmark subset and confirm `usage_tokens` populates. (Set by Zuri/S465, 2026-09-11)

- [ ] **B-2026-09-11-2** (P2, agent/context-honesty — S466 finding, observed live in the user's app chat during the S464 dir_explorer live-test window, bankofai/qwen3.8-flash): **The model misattributes tool results to the wrong tool in prose, and when asked how it knows, it CONFABULATES an introspective capability the backend does not provide — it will confidently claim to re-read a tool-call log its per-turn context never carries.** The arc (2026-09-11 app chat): asked to "use the explorer to locate my CV", the model ran `system_search` — the CORRECT choice (`dir_explorer` is {list,tree,stat} and cannot search by name) — but narrated the result as "the explorer tool works like a charm … scanned ~7k entries, time-budget-partial" (system_search's output signature, misattributed). Probed twice ("did you use explorer or system_search?", "how do you know when you haven't tested it?"), it corrected itself, then asserted: "My context window carries the actual tool-call log (the function name I invoked and its raw result), so the ground truth is readable — when I claim 'I used X', I look at the function name that produced the result." That mechanism does NOT exist across turns: WITHIN a turn the loop appends the assistant `tool_calls` block + `role:"tool"` result messages (`backend/src/core/agent/loop.py` ~3285-3306), so same-turn misattribution is a pure prose/attention failure with ground truth in view; but the NEXT turn's prompt keeps only the last-8 history rows FILTERED to user/assistant roles — tool rows are explicitly skipped (`backend/src/core/agent_runtime.py` ~1505) — and the only surviving trace is the ParentSession rolling summary's per-turn one-liner `did <tool>(args)` (`backend/src/core/parent_session.py:162-169`; <=3 tools, 120 chars, no raw results). The full truth IS persisted (messages table: role='tool' rows + tool_calls JSON) and shown in the UI tool pills — the model just has no path to it. Consequence: weak-model self-reports about tool use are untrustworthy exactly when the user asks "which tool / how do you know", and the model papers over the gap with a plausible false mechanism instead of "I can't re-check that". Fix shapes (architectural — design first, live-verify per protocol): (a) include compact tool rows in the recent tail so "I can check the log" becomes TRUE; (b) answer "which tool did you use?" deterministically from the persisted messages timeline routed in as a fact, instead of trusting model recall; (c) minimal: steering that tool attribution may cite only the current turn's trace or the summary line, and must never assert a re-readable log. (Set by S466, 2026-09-11)
