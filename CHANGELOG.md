# Changelog

All notable changes to LocalMind are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- The web_search Actions card now shows **which search engine answered as a badge** (e.g. a small `BING` pill next to "Searching the web") instead of only in the result text. The agent loop reads the winning provider from the tool result metadata (generic `provider` key, falling back to web_search's `successful_provider`), carries it on the tool_call event, and it flows through the live SSE bridge and the persisted actions table — so the badge survives a reload too.
- Web search gains a **reliable no-key second free tier: Bing** (scraped organic results). Public SearXNG instances churn constantly (rate-limited / behind anti-bot within days), so the SearXNG fallback chain from the previous fix is a stopgap, not a dependable tier. DDG, Bing, and SearXNG now race in parallel — three independent free engines, so one provider being blocked no longer fails the whole search. Bing's `li.b_algo` organic blocks are parsed, its `/ck/a` redirect URLs are decoded back to the real destination, and challenge/captcha pages are detected and reported as such. Live-verified: Bing returns clean, decoded results and wins the race.
- Web search's SearXNG tier was effectively dead: the default instance (`searx.be`) sits behind an Anubis anti-bot page that answers HTTP 200 with HTML, so every request raised a raw `JSONDecodeError` and the tier never returned a result (the error message even leaked the parser error to the user). SearXNG now walks a fallback chain of instances — the configured `SEARXNG_URL` (comma-separated list supported) first, then curated public fallbacks, capped at 3 attempts — and detects non-JSON challenge pages and rate limits so it moves to the next instance instead of dying on the first. `json.JSONDecodeError` is caught explicitly with a friendly message, and the DDG provider no longer uses the deprecated `asyncio.get_event_loop()`.
- Leaving a chat and coming back no longer loses the Agent Workspace run tree or the Observe data. The Agents tab (parent/child runs, tool steps, evidence) and the phase strip were frontend-only live state rebuilt from SSE obs events and cleared on every session switch; the Observe panel read an in-memory engine dict that died on backend restart. The runtime now rebuilds the run tree + phase strip server-side from the request's obs events (mirroring the frontend's logic: delegation children, evidence entries, tool attachment) and persists them with the assistant message; the history endpoint returns them and the frontend restores the last turn's tree. The observation (merged metrics + structured snapshot summary) is written to a new per-session `observations` table at turn end, and the observability endpoint falls back to it on a cache miss — so the Observe panel survives a backend restart too.
- Leaving a chat and coming back no longer loses the context count, Actions pills, thinking blocks, or error cards. The `messages` table only stored role/content, so thinking, errors, tool-step timelines, and per-turn metrics were transient frontend state that vanished on reload. Each assistant message now persists those artifacts (thinking trace, raw error string, tool-call timeline with the same delegation output boundary as the live SSE bridge, and prompt/completion/latency metrics); the history endpoint returns them (error normalized at the presentation boundary per ADR-20) and the frontend restores the ThinkingBlock, ErrorMessage card, step pills, and reseeds the cumulative context counter from the per-message performance.
- The context counter in the top bar now counts tokens cumulatively across the whole conversation instead of showing just the last response's prompt — so it grows as you chat and matches the running total in the bottom-right stats bar (while a reply is streaming, the in-flight estimate is added on top).
- The "Why" block in the Actions tab (and the chat tool-step cards) is now hidden when the reasoning is empty or whitespace-only — an empty plan-step label no longer leaves a blank "Why" section (or a stray "why:" line) eating vertical space.
- The reasoning ("Thinking") block now has a maximum height with its own scrollbar instead of stretching the message indefinitely, a copy button at the bottom to copy the full thought process, and it auto-scrolls to the bottom so newly generated reasoning stays visible while it streams.
- Shell tool no longer rejects PowerShell cmdlets on Windows (live user bug): the model is told it's on PowerShell and emits commands like `Get-ChildItem -Path $env:USERPROFILE\Desktop`, but the legacy dispatch gate only routed known command tokens + shell operators, so every cmdlet fell through to the "NL dispatch is gone" rejection (`nl_dispatch_removed`) before reaching the shell. The gate now routes PowerShell-flavored commands (per the Session 189 detector) straight to `run_command`.
- The agent now chains related tools: the shell and file_write tool descriptions, the SHELL/FILE_WRITE planning workflows, the Operator persona, and the universal FOLLOW-THROUGH rule all now say explicitly that listing a folder is only the FIRST step when the user asked to create a file — after confirming the path, call `file_write` with that exact path instead of stopping after the listing.

### Removed
- Deleted the legacy request-time intent system: `thinking_dispatcher.py`, `execution_graph.py`, `workspace/orchestrator.py` (+ `workspace/manager.py`), and `engine/routing_helpers.py` had no production callers since the parent-agent runtime replaced the request pipeline (Session 201). Their data contracts (`TaskProfile`, `OrchestrationPlan`, `ExecutionMode`, `SafetyLevel`, `ExecutionConstraints`, `UnderstandingResult`, `ValidationResult`) and dead constants/helpers were deleted with them. The parent AgentLoop is the only routing path — every turn classifies the tier, then the plan EMERGES from tool evidence.
- Parent initialization is now strictly classify-only (rebuild Step 1): the init decision no longer carries `facts`/`ambiguities`/`tool_names`/`plan_steps`/`success_criteria` (parsed fields, `plan_text()` rendering, the streaming `understanding_details` block, upfront `todo_created` events, and the init-fed acceptance criteria were all deleted). A model that returns legacy fields is ignored, not preserved. The tool catalog is no longer accepted by `build_initialization_prompt`.

### Added
- Thinking/reasoning is now re-enabled for z.ai GLM models (ADR-41): the adapter no longer unconditionally sends `thinking: {type: disabled}` on every z.ai call — a workaround for the ThinkingDispatcher's 10s timeout, a component deleted in Session 239. GLM-4.5-Flash and other reasoning models now think by default, so they answer with complete, well-formed replies instead of ~28-token terse cuts. Tunable via `LOCALMIND_THINKING=disabled` (opt-out), and never disabled for GLM-5.3+ (which rejects `thinking.type=disabled`). `LOCALMIND_REASONING_EFFORT` sets the effort level for GLM-5.2+ only.
- Thinking-aware timeouts (ADR-41): when the active adapter has thinking enabled, the per-call timeout rises from 45s to 180s (`LOCALMIND_REASONING_TIMEOUT_SECS`), the plan/init/orchestrator stream budgets rise from 8s/10s to 30s (`LOCALMIND_REASONING_PLAN_TIMEOUT_SECS`), and the total-turn wall-clock cap rises from 180s to 360s (`LOCALMIND_REASONING_MAX_WALL_CLOCK_SECS`) — a slow free tier spends 30-170s per call thinking, so a multi-step turn (init + tool + answer) needs more than the 180s default to finish. The per-call timeout, iteration cap, and bounded recovery retries remain the spin protections, and a model that only thinks and never answers still fails fast.
- The agent loop now forwards `StreamChunk.thinking` on ALL final-answer streaming paths (MiniMax buffer flush, mid-stream, and the hit-limit forced-final synthesis), so reasoning reaches the ThinkingBlock even on the tail of a turn instead of being dropped.
- Reasoning-model thinking is now tunable from the Settings UI (and documented in `backend/.env.example`): a Reasoning section lets you enable/disable model thinking, set the reasoning per-call and plan timeouts, and pick a reasoning-effort level for GLM-5.2+. Values persist in `settings.json` via `POST /api/settings/thinking` and win over env vars (`LOCALMIND_THINKING`, `LOCALMIND_REASONING_TIMEOUT_SECS`, `LOCALMIND_REASONING_PLAN_TIMEOUT_SECS`, `LOCALMIND_REASONING_EFFORT`), which the adapter and the loop's timeout selection both honor.
- On-demand tool loading (ADR-40 option C): the 16 long-tail tools (`browse`, `delegate`*, `sql`, `csv`, `json`, `best_of_n_edit`, `propose_*`, `add/update_subgoal`, `create_plan`, `skill`, `diagnostics`) are no longer sent in the model's `tools` parameter on every call. A new `describe_tool` meta-tool (mirroring the `skill` loader) loads a specific tool's full schema into the `tools` param for the rest of the run when the model needs it. The 14 core tools stay always-present lean. The per-call tool catalog drops from ~16,937 to ~7,851 chars (~54% fewer tokens/call; ~68% vs the pre-ADR-40 catalog).
- Long shell and Python execution output now keeps both its beginning and end within the 4000-character limit, so trailing errors remain visible.
- Browser automation can now inspect rendered DOM/HTML, captured network requests, and browser console messages, with bounded output and sensitive-data guidance
- Added Z.ai as a new LLM provider — offers free access to GLM-5.2, GLM-5.1, GLM-5, GLM-5-Turbo, GLM-4.7 (limited-time free) and GLM-4.5-Flash (always free). Sign up at `z.ai/manage-apikey/billing` to get an API key, then select "Z.ai (GLM-5.2 free)" in Settings. The model dropdown shows all available GLM models live from Z.ai's `/models` endpoint
- Automatic retry on HTTP 429 (rate limit) responses — the adapter now retries up to 2 times (3 total attempts) with exponential backoff (2s, then 4s), respecting the provider's `Retry-After` header when present. This makes transient per-minute burst limits (common on Cerebras's free tier) invisible to the user in most cases. Only 429s are retried; permanent errors (400/401/402/403/404) fail immediately without wasting time
- Added 4 new free-tier-friendly LLM providers: Cerebras (1M tokens/day free), SambaNova, Google Gemini, and Chutes AI — all selectable from the Settings panel
- New providers appear in the model selector, health endpoint, and startup logging alongside the existing 14 providers
- New `LOCALMIND_ALLOWED_FOLDERS` environment variable — comma-separated list of folders the file explorer is allowed to read. Lets users on non-standard layouts (e.g. `/srv/projects`, `D:\Code`) expose their actual work folders without editing source code. Empty = default set (home + common dev folders)
- New `backend/.env.example` file documenting every configuration variable with its default and a one-line description. Contributors no longer need to read `config.py` to discover available settings
- API keys entered via Settings are now validated immediately after saving — the backend runs a lightweight health check against the provider and reports whether the key works. The key is saved regardless (the user may be offline), but the UI shows a clear warning if validation fails, so typos are caught before the first chat message
- Settings dialog now supports keyboard navigation — Escape closes the modal, Tab is trapped inside (can't escape to elements behind the backdrop), and focus is restored to the element that opened the modal when it closes. Screen readers announce the dialog via `role="dialog"` and `aria-modal`
- Regression tests for the SSRF redirect bypass fix — verifies that redirects to private IPs (cloud metadata, localhost) are blocked, redirects to public URLs are followed, and multi-hop redirect chains are validated at every hop

### Added
- Themes. Settings now has an Appearance section where you can pick between three color themes — Graphite, Midnight Iris, and Warm Ink — and choose Light, Dark, or System (follows your OS). Your choice is remembered and applies instantly, with no flash when the app starts.

### Changed
- The agent now sends much leaner tool descriptions to the model on every call — each tool is summarized with its purpose and safety rules instead of a full manual. The tool catalog is about a third smaller (~2,000 fewer tokens per call), which gives free-tier models more budget for actually answering and trips per-minute rate limits less often. Tool selection was verified live on both a weak free model and a fast cloud provider.
- When a provider rate-limits the follow-up synthesis call after a tool already succeeded, the agent now preserves the verified tool evidence and returns a degraded evidence response instead of rendering the entire turn as a failed provider request.
- The agent's opening acknowledgement now appears in the chat as the first line of its reply, and its understanding now lives in the thinking block only — neither is buried in the Agent Workspace anymore.
- The agent's thinking now separates what it knows (facts) from what it must assume (ambiguities), so you can watch it resolve uncertainty instead of seeing a one-line objective.
- A turn that passes its acceptance check can no longer end with no reply — the agent always produces at least a summary of what it verified.
- Refreshed the color scheme. The interface no longer uses green for everything — the default is now a calm, neutral graphite with emerald used only as an accent, which is easier on the eyes and lets your content stand out. Under the hood this is a full theming system: three palettes (Graphite, Midnight Iris, Warm Ink), each in light and dark, are ready to ship — a picker to switch between them in Settings is coming next.
- The terminal now has a blinking cursor at the prompt when it's ready, and shows a live "executing…" cursor while a command is running so you can tell the shell is working even before any output appears. Command output itself is not animated, so fast output stays smooth.
- The Agents view now animates parent and delegated child agents (and their tool steps) into the tree as they start, and highlights the agent that's currently working, so you can follow delegated work as it happens.
- The action list in the side panel now animates each step in as it happens and clearly marks the step running right now, so it matches the live "Actions" card in the chat.
- The task plan now shows which step the agent is working on right now — the active step is highlighted with a spinner and stands out from the rest, finished steps check off with a little animation, and new steps slide in as the plan is built. The plan also stays visible while the agent works (it used to disappear while tools were running), so you can watch it progress. Motion is disabled automatically if your system prefers reduced motion.
- The agent's reasoning ("thinking") now streams live with a blinking cursor, so you can watch it being written as it happens, and a small pulsing indicator shows while the agent is still thinking. Once it finishes, the block is labelled "Thought process" with the time it took. Motion is disabled automatically if your system prefers reduced motion.
- The agent's tool activity in chat now appears as a single live "Actions" card instead of a stack of separate boxes. It shows a plain-language summary of what happened ("Wrote 1 file, Ran 2 commands"), lists each step on a connected timeline, and ends with a "Done" line. While the agent is working, the card opens on its own and the active step gently pulses so you can watch it happen in real time; it tidies itself away once finished. Motion is turned off automatically if your system prefers reduced motion.
- Lightened the dark green UI palette across backgrounds, panels, borders, and secondary text to improve readability while preserving the dark-only identity.
- Chat now emits a server-side acknowledgement as its first SSE event, before title persistence, memory retrieval, adapter setup, or model generation, so slow turns never appear silent while the agent starts.
- Replaced the request-time execution pipeline with the LocalMind parent-agent runtime. `Engine` now enters one parent `AgentLoop` for every non-blocked turn; lifecycle services retain safety, persistence, memory, observability, abort, and steering while tool choice, delegation, evaluation, replanning, and synthesis stay inside the parent loop. The legacy `_pipeline.py` module is deleted.
- Substantive parent-agent turns now expose a concise lifecycle — acknowledgement, planning summary, next-action progress, and verification — while keeping raw provider planner/reasoning tokens internal to the task state and evidence loop.
- Parent tool observations now remain intermediate evidence: web-search results return to the parent loop for follow-up fetching, replanning, verification, or final synthesis instead of being emitted as the chat answer immediately.
- Redesigned the API Keys section in Settings — removed the confusing dual-list pattern (stored keys list + separate "Select provider" dropdown) and replaced it with a single unified list where each provider has an inline "Add Key" or "Update" button that expands the key form right there. No more scrolling through a dropdown to find a provider — just click the button on the provider you want
- Provider list in the Settings panel now shows ALL providers in a single scrollable grid — previously only the first 8 appeared as buttons and the rest were hidden behind a "More providers..." dropdown that was easy to miss. Now all 18 providers (plus Ollama) are visible at once in a 2-3 column grid that scrolls if needed
- Provider list in the Settings panel is now sorted alphabetically (A–Z) by display name, making any provider easy to find regardless of when it was added
- The Settings panel no longer hardcodes any model IDs — default models now come live from the backend (`GET /api/settings`), and the full model list comes live from each provider (`GET /api/models?provider=...`). When a provider deprecates a model, only the backend needs updating and the frontend follows automatically. Previously the frontend duplicated every provider's default model ID in a hardcoded array, which drifted from the backend and caused 404 errors when providers deprecated models
- The app now applies the `dark` class to the `<html>` element by default. LocalMind is a dark-only app — this ensures all shadcn/ui components (which use `dark:` Tailwind variants) render correctly in the dark theme. The light theme variables in `globals.css` are retained for future theming support
- The `human_size` byte-formatting helper is now shared from `core/utils.py` instead of being duplicated in `shell.py` and `filesystem.py`. A bug fix or new unit will now propagate to all callers automatically

### Changed
- Windows now uses the custom LocalMind title bar instead of the native frame — the Electron window is fully frameless on Windows and the TitleBar's own minimize/maximize/close buttons (wired through IPC) are the window controls. macOS keeps the system traffic lights (`hiddenInset`) and Linux keeps the native frame, so the custom buttons render only where they are needed. The maximize button also shows a restore icon when the window is maximized, and double-clicking the bar toggles maximize/restore like the native Windows title bar.

### Fixed
- Reduced the input tokens sent on every model call: the list of available tools was being sent up to three times (once as the real tool API, once as a text copy pasted into the instructions, and once inside the base instructions). Removed the redundant text copy — verified ~2,700 fewer tokens per call on z.ai/GLM, with tool use unaffected. This is especially helpful on small free tiers where a bloated request leaves little room for the reply.
- Fixed a rare case where the end of a streamed reply could be dropped for models that send their answer in many small pieces — the reader stopped early after detecting it was a text answer. It now reads the whole response.
- Fixed GLM-4.5-flash's tendency to give very short/terse answers — that was NOT a limitation of the free model: the adapter was unconditionally disabling its reasoning (`thinking: {type: disabled}`) on every z.ai call, a workaround for a deleted component (the ThinkingDispatcher, removed Session 239). With thinking re-enabled (ADR-41), the same model streams live reasoning and produces complete answers (live-verified before/after on z.ai/glm-4.5-flash: ~91-char truncated vs complete).
- Fixed "Agent loop failed — empty_response" after long thinking on z.ai/GLM (Session 256): with thinking on, a slow free tier sometimes streams a full reasoning burst and then returns no answer and no tool call — the model "thinks but doesn't act" — which previously failed the whole turn. The loop now does bounded retries with a continue-nudge when reasoning streamed but nothing else arrived (up to 2, `LOCALMIND`-tunable via `_MAX_EMPTY_REASONING_RECOVERIES`); exhausting them still fails fast (the think-only protection stays).
- Fixed chat replies appearing twice after closing and reopening a chat. The guaranteed-persist safety net (which runs when a stream is interrupted) checked the OLDEST messages instead of the most recent one, so from the second turn onward every reply was written to history twice; the dedup now looks at the latest messages.
- Clicking "New Chat" now returns the left panel to the Chat tab and the right panel to the Agents tab, and resets the context-window counter to zero — a fresh conversation no longer inherits the previous one's tabs or token count.
- Live and just-finished actions in the Actions tab now render as the same expandable cards as the post-session history instead of compact one-line pills, so you can inspect a running step's input/output mid-execution. Action cards also gained a scrollable body, copy buttons for each section, the step number stacked above the card (giving the action container full width), and pretty, color-coded JSON input.
- Fixed the agent welding words together in tool-based answers (text like "HereHere arethe trending stories"). The final synthesis of web-search and other tool results was trimming each streamed fragment individually, which ate the space between fragments; it now preserves them so the answer reads normally.
- Fixed the action history panel crashing when a tool call's duration was missing. A `null` duration (which can arrive from the backend where `undefined` cannot) slipped past the display check and crashed the whole panel when it tried to format it; the panel now only shows a duration when it's an actual number.
- Fixed tool-required tasks failing on some models (e.g. Gemini Flash) that returned an empty or text-only reply on the first tool call instead of invoking a tool — the turn used to end with an "empty response" error. The agent now forces a tool call on the first tool step (standard `tool_choice: required`) and, if the model still won't call a tool, nudges it once before falling back to the honest error. Verified live: "list my projects" now runs the tool and returns the listing.
- Fixed the token count being wildly overstated for quick replies. It was counting the full context the agent prepared but didn't actually send for a simple reply (which grew as the conversation got longer); it now reports what was really sent — e.g. a greeting shows ~900 tokens instead of ~5,000.
- Fixed the Settings dialog losing focus about once a second, which made it impossible to paste or type an API key. Fields now stay focused while you type.
- Fixed missing spaces in quick replies and the thought process (text like "Hey!Notmuch,justhere…"). Streamed text was having the spaces between fragments trimmed away before being shown; they're now preserved, so replies and reasoning read normally.
- The "Thought process" now shows the agent's actual reasoning about your request, not a copy of the final answer. Previously, for quick replies, the same text appeared as both the thinking and the answer (and again in the Agent panel); the thinking line now reflects what the agent understood you wanted, kept separate from its reply.
- Usage-limit and quota errors now appear right away. If your provider reports that you're out of free/daily quota or credits, LocalMind stops immediately and shows the error, instead of retrying for 20+ seconds first.
- Polished light mode: fixed a few spots (the decision strip under replies, file names on hover, and some row hovers) that used fixed colors and could look wrong or vanish on the new light themes.
- Replaced the prompt-shaped greeting/conversation routing shortcut with a model-owned parent initialization decision. Every turn now asks the parent LLM to choose `direct`, `clarify`, or `execute`; tool work receives a visible plan before the parent loop, while direct answers complete from the same initialization call.
- Fixed the live chat stream going silent while the parent agent waited on a slow model or tool. Heartbeats now flush pending parent tool progress and bounded results immediately, while preserving delegated child-output privacy and the normal metrics/observation queue.
- Fixed current time/date requests accidentally emitting rejected shell commands such as `Get-Date`. The parent loop now corrects clock queries to `sysinfo` and returns the verified local date/time unchanged, preventing synthesis from corrupting dates.
- Removed the legacy pre-loop sub-agent heuristic and decomposition path. Cross-domain delegation now starts inside the selected parent agent through scoped delegation tools, preserving parent context and synthesis.
- Fixed delegated child tool results appearing as user-facing output. Child progress remains visible in the Actions panel, while raw child results stay inside the parent-agent tool context for synthesis.
- Fixed current-weather synthesis selecting an older dated search result when a same-day result was available. Time-sensitive search extraction now filters stale dated blocks and returns an honest gap report when current evidence cannot be verified, with regression coverage.
- Fixed weather web searches failing after the provider returned results because the agent loop passed a structured `reasoning` keyword that the web-search result handler did not accept. The handler now accepts that existing call contract, with regression coverage.
- Fixed provider prompt-token telemetry not reaching the Observe panel. OpenAI-compatible and Ollama adapters now normalize real prompt/completion usage, preserve terminal/tool-call usage through AgentLoop and Engine paths, and fall back safely when a provider rejects optional streaming usage fields.
- Fixed the Observe panel's live performance metrics staying blank during streaming. Latency now follows the active request clock, current prompt-token telemetry is used for Context Tokens when available, and completion tokens are never mislabeled as context.
- Fixed file-upload failures being silently buried as an empty assistant response. Upload/storage errors now use the same typed streaming events as other chat failures, so the UI displays the error and cleanly ends the response.
- Fixed the frontend chat stream dropping the final SSE event when a response closes without a trailing newline. The parser now flushes pending decoder and event-buffer state before completing, with regression coverage for unterminated events.
- Fixed the "Tools execution failure" bug where the agent ran tools (shell, file_write, etc.) but then showed a uselessly generic fallback message ("I wasn't able to complete that request. The tool may have failed or returned no useful output. Please try rephrasing your request."). Root cause found via real-model testing against Zen/DeepSeek-v4-flash-free: two adapter bugs in `openai_compat.py`. (1) DeepSeek rejects requests where the last message is a `tool` role — returns HTTP 400 "Upstream request failed". The agent loop sends this format after every tool execution. Fix: `chat_with_tools` appends a synthetic `user` message when the last message is `tool` role. (2) DeepSeek produces 80+ reasoning chunks before the tool_call delta arrives; Phase 1 detection was breaking at chunk 15 (during reasoning), falling through to Phase 2b which silently dropped the tool_call deltas. Fix: Phase 1 now only breaks if it's seen actual content (not just reasoning); reasoning-only streams keep reading until content or tool_calls arrives (hard cap: 500 chunks). The fallback messages were also revised to surface actual tool inputs/outputs from the trace instead of guessing "overload" — honest evidence > speculation
- Fixed the iteration limit being too low for multi-step tasks. `MAX_ITERATIONS` was 3 (lowered in Session 31 to fit a 90s wall-clock cap) — the model did 3 reconnaissance calls (checking state before acting, exactly what we want) and hit the cap before the actual work. Raised to 8 (configurable via `LOCALMIND_MAX_ITERATIONS` env var). `MAX_WALL_CLOCK_SECS` raised from 90s to 180s (configurable via `LOCALMIND_MAX_WALL_CLOCK_SECS`). 8 iterations gives room for: reconnaissance (2-3 calls) + actual work (3-5 calls) + verification (1-2 calls). The wall-clock cap is the real safety net against a spinning model, not the iteration cap
- Fixed the fallback messages misdiagnosing "iteration limit reached" as "model overload" or "context overflow". Sessions 21-31 kept guessing "overload" when the actual cause was the iteration cap. When `trace.hit_limit` is True, the fallback now explicitly says "I hit my iteration limit (N iterations) before completing the task. This is NOT a model overload or context-overflow issue" and suggests "tell me to continue" — not "switch to a larger model" (the model didn't fail, it ran out of steps). This kills the misdiagnosis pattern that sent users down wrong paths across multiple sessions
- Added a universal "check before acting" safety workflow (`backend/data/workflows/safety.md`). Every tool invocation that creates, writes, modifies, or deletes something must first check whether the target already exists or has content, and adapt the plan based on what's found — never act on an assumed state. Applies to shell (mkdir/rm/cp), file tools (file_write/edit_file/file_task), code_exec, web tools, and memory_op. Includes the subdirectory adaptation: when the target is non-empty and unrelated to the task, scope work into a subdirectory instead of dumping alongside existing files. Injected into the agent system prompt for all agent intents. Fixes the bug where the model ran `mkdir` before checking if the directory existed, and barreled into a non-empty unrelated folder instead of creating a `hello_world/` subdirectory
- Fixed the uselessly generic "I wasn't able to complete that request. The tool may have failed or returned no useful output. Please try rephrasing your request." message that appeared when the model returned an empty stream after tool execution (common with free-tier models — overload or context window overflow). The agent loop now surfaces what tools actually ran (with status + error snippets for failures) via a trace summary, and the engine's last-resort fallback now names the intent + suggests concrete next steps (switch model, one step at a time, re-run) instead of mis-attributing the failure to the user's phrasing
- Fixed a security vulnerability where `web_fetch` could be tricked into fetching internal network addresses (cloud metadata endpoints, localhost services, private IPs) via HTTP redirects. The SSRF protection validated the initial URL but `follow_redirects=True` let httpx follow 302 responses to internal addresses without re-validation. The adapter now follows redirects manually and re-runs the SSRF check on every redirect target, blocking any hop that resolves to a private/loopback/link-local address
- Fixed Anthropic provider returning blank responses when streaming — the adapter was reading the non-streaming response format (`content` array) from streaming SSE events, which use a completely different shape (`content_block_delta` events with `delta.text`). Streaming now correctly parses Anthropic's event format, including `message_stop` for completion and `stop_reason` for content-filter detection
- Fixed `LOCALMIND_SHELL_ENABLED` default value documented in README — was listed as `true`, but the actual default in `config.py` is `false` (disabled by default for safety)
- Fixed `ProviderConfig.headers` type annotation — was `dict = None` (None not assignable to dict), now `dict | None = None`

### Security
- Closed an SSRF redirect bypass in the `web_fetch` tool. A malicious public URL could return a 302 redirect to an internal address (e.g. `http://169.254.169.254/latest/meta-data/` to steal cloud IAM credentials, or `http://localhost:11434/` to access the Ollama API). The previous code used `follow_redirects=True` which let httpx follow redirects without re-validating them. The fix implements manual redirect following with SSRF re-validation on every hop
- Fixed Gemini returning 400 errors after v0.5.6 — the `safety_settings` field is NOT supported by Gemini's OpenAI-compatible endpoint (it returns "Unknown name 'safety_settings': Cannot find field"). Removed the injection entirely; the finish_reason detection added in v0.5.6 remains as the safety net, surfacing a clear error when Gemini's filter triggers instead of a blank response
- Fixed Gemini returning empty responses on follow-up messages — Gemini's safety filters were silently blocking responses to normal queries (sports scores, news, etc.), producing a blank chat with no error. The adapter now detects `finish_reason=SAFETY`/`content_filter` to surface a clear error message instead of a blank response
- Fixed the synthesizer silently producing empty output when the LLM returned a near-empty response (less than 10 characters) — now falls back to smart extraction so the user always sees something useful, even if the LLM was filtered or produced garbage
- Fixed Chutes AI base URL — was pointing to the management API (`api.chutes.ai`); now correctly points to the inference endpoint (`llm.chutes.ai`). Also updated the default model to `deepseek-ai/DeepSeek-V3.2-TEE` since all current Chutes models are TEE-suffixed
- Fixed model selector not showing available models for Cerebras, Gemini, and Chutes — these providers expose OpenAI-compatible `/models` endpoints, so the selector now lists live models (matching the existing Zen behavior)
- Fixed provider errors (invalid API key, rate limit, network failure) appearing as garbled text in the chat instead of a clear error message — error responses now surface as a proper error notification
- Fixed `asyncio` not imported in `ollama.py` — streaming chat was crashing with `NameError`
- Fixed undefined `secondary_intent` in engine pipeline — secondary intent routing now works
- Fixed `ToolCallResult` undefined in `openai_compat.py` — added `TYPE_CHECKING` import
- Fixed file-upload error handler in `chat.py` — `exc` was out of scope due to PEP 3110
- Fixed `_chunk_text` infinite loop when `overlap >= chunk_size`
- Fixed broken test suite — stale imports in `test_file_reader.py` and `test_web_search.py`
- Fixed 15 pre-existing test failures — mock signature mismatch and path bugs
- Fixed 5 TypeScript errors in frontend — `tsc -b` now passes clean
- Fixed Windows-only `dev:backend` script — now cross-platform via `scripts/dev-backend.js`
- Fixed 7 bare-except errors in `installed_programs.py`
- Fixed Pydantic V1 `class Config` deprecation warnings (3 locations)

### Added
- Comprehensive `README.md` (was empty — 0 bytes)
- `eslint.config.js` flat config for frontend — `npm run lint` works again
- `scripts/dev-backend.js` — cross-platform backend launcher
- GitHub Actions CI workflow (`.github/workflows/ci.yml`)
- `REVIEW.md` — agent review with 24 findings catalogued by severity

### Changed
- Aligned backend version from `0.1.0-dev` to `0.5.0` (was mismatched with frontend/electron)
- Updated `ARCHITECTURE.md` to reflect v4.0 ThinkingDispatcher codebase
- Updated `CONTRIBUTING.md` to document the actual direct-to-main workflow
- Ran `ruff --fix` — cleared 228 auto-fixable lint errors (862 → 613)

### Security
- Replaced bare `except:` with specific exception types in `installed_programs.py`

---

## [0.5.0] — 2025-01

### Added
- **Browser agent tool** — real web interaction via headless Chromium (navigate, click, fill forms, scroll, screenshot, execute JS)
- **Workflow system** — stream plan as thinking tokens + create todos from steps + mark todos complete as tools execute (full plan→execute→track cycle)
- **Full file metadata** — modified, created, extension, symlink detection
- **Context injection** — full system info (hostname, user, CPU, tools, memory count) injected into every prompt
- **Deliberative thinking** — result verification + Observe field mapping
- **Date/time injection** — current date/time injected into every prompt

### Fixed
- Atomic `settings.json` writes — never lose settings again
- Stop Ollama code paths from running when adapter is Zen
- Thinking timer showing 0s + added milliseconds for short thinking
- Enforced concise structured responses — no more walls of text
- Model now interprets intent instead of mechanically echoing user's message
- Epoch timestamps in chat + Observe tab all dashes + intent never sent
- 3 runtime errors from user's startup log
- LLM title prompt giving verbatim examples + sidebar never refreshed
- Second message hangs forever — queue await + isStreaming stuck
- Explicit done chunk on all return paths — UI was dormant because stream never signaled completion
- `NameError: 'tools' not defined` in agent loop call — second message crash
- Agent loop path missing done chunk — Observe tab showed — for all metrics
- Diagnostic logging for adapter issues + `/api/models/debug` endpoint

---

## [0.4.0] — 2025-01

### Added
- **Real-time thinking tokens** — stream actual LLM reasoning tokens, removed placeholders
- **File explorer** — default path, dispatcher progress, dedup, observe sync

### Changed
- Removed "conversation mode" tool ban + fixed default CWD to `~`
- Started backend before frontend to eliminate ECONNREFUSED spam

### Fixed
- 6 critical bugs making the UI look broken
- All remaining audit issues (C5-C6, H1-H9, M1-M8, L3-L10)
- npm audit vulnerabilities in frontend

---

## [0.3.0] — 2025-01

### Added
- **Settings modal** in frontend

### Changed
- **Engine refactor** — split `engine.py` into `engine/` package (helpers, memory, persistence, reflection submodules)
- UI model display syncs with backend active model
- Backend `settings.json` is source of truth, not frontend localStorage
- Removed all hardcoded model fallbacks from frontend

### Fixed
- Adapter now reads model from settings — the actual root cause of model sync issues
- Path bug + skip Ollama warmup for cloud adapters
- Frontend retries 503s automatically to eliminate startup console spam

---

## [0.2.0] — 2025-01

### Added
- **SSRF protection** in `web_fetch` tool
- **Settings file permissions** restriction and key revocation
- **Memory safety gate** tests

### Changed
- Removed 1,848 lines of dead classifier code

### Fixed
- Closed critical security vulnerabilities in backend
- Repaired corrupted safety regex and runtime bugs
- Fixed test collection errors
- Restored missing API client module and fixed runtime bugs in frontend

---

## [0.1.0] — 2025-01

### Added
- Initial release of LocalMind
- FastAPI backend with Ollama adapter
- File reader tool (PDF, DOCX, CSV, XLSX, code, images)
- Web search tool (DuckDuckGo)
- Memory tool (persistent semantic memory via sqlite-vec)
- Code executor tool (Python, sandboxed)
- File writer tool (permission-gated)
- React frontend with chat interface
- Electron desktop wrapper
- CLI (Typer)
- pytest test suite

[Unreleased]: https://github.com/TisoneK/LocalMind/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/TisoneK/LocalMind/releases/tag/v0.5.0
[0.4.0]: https://github.com/TisoneK/LocalMind/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/TisoneK/LocalMind/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/TisoneK/LocalMind/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/TisoneK/LocalMind/releases/tag/v0.1.0
