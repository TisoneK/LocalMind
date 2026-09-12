# Review — B-2026-09-10-8: `grep_search` in no model-facing tier (expose or retire)

- **Session:** S472 (Buffy), 2026-09-11, local macOS checkout, core 1.0.4
- **Task:** owner: "Take B-2026-09-10-8 (grep_search sits in no model-facing tier — expose or retire it) and recommend which."
- **Deliverable:** a recommendation with code-level evidence. No product change this session — the choice is a product decision (it changes what the model can do) and both options are sized below.
- **Recommendation:** **RETIRE the tool — keep the machinery.** Take `grep_search` off every model-facing surface (it is already off, accidentally) and delete the misleading artifacts around it, but do not delete the scan/format engine: absorb it into `system_search` as `operation=content` (the already-open B-2026-08-25-2). Do not add a second local-search tool name.

## 1. Current state, verified in code (it is 100% dead for the model)

`grep_search` is a registered tool (`Intent.GREP_SEARCH`, `backend/src/tools/grep_search.py`, 230 lines, bounded: 50 results / 5 MB per file / heavy-dir + binary-extension skip / `file:line` output with `matches` + `files_scanned` metadata) that **no model can ever call**:

| Surface | grep_search present? | Evidence |
|---|---|---|
| `TOOL_DEFINITIONS` (the model-facing catalog: native `tools` param + in-prompt list) | **no** | no `"grep_search"` in `core/agent/tool_schemas.py` |
| `CORE_TOOL_NAMES` / `LONG_TAIL_TOOL_NAMES` (always-present vs `describe_tool`-loadable) | **no** | same file; `describe_tool` resolves only these two sets |
| `AGENT_ALLOWED_TOOLS` (the dispatch fence) | **no** | `core/agent/constants.py:211-246` |
| `INTENT_TOOL_SCOPES` | **no** | `constants.py:289+` — `FIND_PATH` and `SYSTEM_SEARCH` have scopes, `GREP_SEARCH` does not |
| classifier route (an intent can be emitted) | **no** | no producer of `Intent.GREP_SEARCH` anywhere in `backend/src` (only the two consumer maps: `agents/selection.py:83` → "coding", `core/agent/tool_dispatch.py:32` → "file_read") |
| non-agent context prose | **yes — and it is a lie** | `core/context_builder.py:296`: `- grep_search: Search file contents for text patterns (works without shell)` |

So neither path reaches it: the model cannot see it, cannot load it via `describe_tool`, would be fenced if it hallucinated the call, and no intent routes to it. The only live effect of its current state is **misleading prose**.

## 2. Two defects found while assessing (worth fixing under EITHER option)

1. **Phantom capability in the prompt.** `context_builder.build_context()`'s "## Available Tools" prose advertises `grep_search` to the model. The agent loop passes `include_tool_list=False` (`agent/loop.py:2701`, `:3134`), so this prose reaches the *other* callers of `build_context` — the model is told it has a tool it does not have. Same class as the phantom `grep_search` pointer removed from `dir_explorer`'s description in S464.
2. **Dead steer in the shell guard.** `tools/shell.py` `_INTERNAL_TOOLS` (line ~630) tells the model: *"'grep_search' is a LocalMind tool, not a shell command — … Emit a real tool call to grep_search instead."* The guard steers to a tool that is not on the surface. Either drop the name or point the steer at `system_search`.

Neither is a behavior regression on its own, but both are the same "system tells the model about an uncallable capability" defect — and they are exactly the artifacts an "expose" decision would legitimate.

## 3. The case for each option

### (a) Expose it
- **The design already assumed it.** `features/system-search-tool/manifest.md:38-39`: *"Phase 2 (content/semantic search) … are explicitly out of scope for the first cut — `grep_search` already covers literal content search"*; and line 154 lists *"Phase 2 content search wiring (`grep_search` visibility / semantic ranking)"*. Phase 1 shipped on the assumption that content search was covered; it is not covered today.
- **The capability gap is live-observed.** S464's bankofai/qwen3.8-flash trace: *"Search all text files in my Documents folder for the word 'invoice'"* → the model chose `shell` and hand-rolled `grep -rniE`. With the shell tool disabled, content search is **impossible** today.
- The engine is better-behaved than shell grep for a weak model (bounded, structured, skips heavy dirs, no OS-syntax differences).
- **Costs/risks:** it is a *second* local-search name next to `system_search`, and the project already paid for that mistake — S400 retired `find_path` from the always-present surface after a live zai trace showed weak models splitting traffic between two name-search tools by name-affinity (find_path picked 4/4 over the front door). `system_search`'s description says "use FIRST for any find/locate/discover question"; a third content-search path (shell's bounded grep, which the guard deliberately permits per B-2026-08-25-1, plus a new name) re-opens the split. It also buys schema budget on every call, and any cut/extension of this kind needs a fresh ADR-40 live selection trace on a weak model before shipping — which the project's standing rule treats as mandatory, not optional.

### (b) Retire it (recommended)
- The front-door rule is standing (S400) and was applied to this exact tool class; consistency argues for the same treatment.
- It removes a misleading prompt line and a dead steer instead of legitimizing them.
- **The capability is not lost** — it is *deferred to its rightful owner*: `system_search` `operation=content` (B-2026-08-25-2, already open, already scoped as "a `content` operation over `grep_search` machinery (bounded)"). That is one front door, one name, no new affinity collision, and the content path arrives with a purpose-built op (`operation=content` reads better to a weak model than a tool whose arg is a prose mini-language: `"<pattern> in <path>"` + `case:i` / `max:N` / `glob:*.py` suffixes).
- Cheaper and safer *now*: no schema budget change, no ADR-40 live-selection risk, no new model-facing name.

## 4. Recommended implementation shape (for the owner's go-ahead)

Retire the **surface**, keep the **engine**:
1. `core/context_builder.py` — drop the `grep_search` line from the "## Available Tools" prose (it is not available).
2. `tools/shell.py` — drop `grep_search` from `_INTERNAL_TOOLS` (or steer to `system_search`), so the guard stops instructing an uncallable call.
3. `backend/src/tools/grep_search.py` — stop registering it as a tool: move the scan + formatting logic to a plain module (e.g. `tools/_content_search.py`) with no `register_tool` call, so B-2026-08-25-2's `operation=content` can call it. Keep the bounds (50 / 5 MB / skip lists) exactly as they are — they are the reason to prefer it over raw shell grep.
4. Remove the dead wiring: `Intent.GREP_SEARCH` (`core/models.py:65`), `agents/selection.py:83`, `core/agent/tool_dispatch.py:32` (+ its permission entry), the `tools/__init__.py` import, and `api/routes/chat.py:101`'s display label; replace `tests/tools/test_grep_search.py` with tests that call the internal module, and drop the `Intent.GREP_SEARCH` exclusion from `tests/core/test_goal_interpreter.py:271`.
5. Leave `shell.py`'s bounded-grep path alone (B-2026-08-25-1 deliberately permits it) and let B-2026-08-25-2 wire `operation=content`.

If the owner instead picks **(a) expose**, the minimum honest version is: catalog entry + a tier (`LONG_TAIL` + `describe_tool` is the precedent set by `find_path`, so content search costs a describe round-trip rather than permanent schema weight) + `AGENT_ALLOWED_TOOLS` + an `INTENT_TOOL_SCOPES` entry + a real classifier route, **plus** the ADR-40 live selection trace showing the weak model still prefers `system_search` for name questions and picks a content op for content questions — and the `system_search` description must be re-worded so the two do not claim the same "use FIRST" space.

## 5. Verification of this review

Every claim above is a code read on `main` @ `c2bd0d2`-era tree (this session's HEAD), each cited with file + line above; the "no producer of `Intent.GREP_SEARCH`" claim is a repo-wide grep (`backend/src` + `tests`), and the tier/allow-list absences are greps of the named files. No live model trace was run — this is a wiring assessment, and the recommendation's risk assessment is drawn from the recorded live traces (S400 zai name-affinity, S464 bankofai shell-grep) rather than a new one. Anything shipped from §4 needs the standard gate + (for the front-door change) the ADR-40 live trace.
