# Session 462 notes — explorer-tool implementation (Njeri / qwen3.8-flash, Windows)

2026-09-10. Feature: explorer-tool. Implementing `dir_explorer` per
`docs/explorer_tool_design.md` + manifest map.

## Live-verification log (Session 274 bar — evidence in scratch/)

Provider landscape this session (all three configured providers, keys never printed):

- **zen / deepseek-v4-flash-free** (design-named primary): DOWN. Both attempts
  (zen-primary, zen-retry) → HTTP 400 `"Model is unavailable"` from the OpenCode
  Zen upstream on every call. Server + adapter healthy (clean error envelope).
  Evidence: scratch/server-direxplore-zen-primary.log (400 lines),
  results-direxplore-zen-primary.json, results-direxplore-zen-retry.json.
- **bankofai / deepseek-v4-flash** (workhorse per live-testing.md): ACCOUNT
  EMPTY. All six prompts → 400 `credit insufficient balance: balance=0`.
  Not retryable from this side — owner needs to top up.
  Evidence: results-direxplore-bankofai-run.json, server-direxplore-bankofai-run.log.
- **zai / glm-4.5-flash** (THE mandatory weak-model gate): FLAKY but SUFFICIENT.
  Intermittent `network_error` ("Cannot connect to zai") and one 120s-timeout
  context_overflow, but completed turns gave every verdict the gate asks:

| Prompt | Result | Evidence |
|---|---|---|
| "What's in my Documents folder?" | **PASS** dir_explorer/list — real 24-entry listing, "scan complete · names only" footer, presented grounded | sse-direxplore-zai-weak-list_documents.sse |
| "Sketch the structure of my LocalMind project" | **PASS** dir_explorer/tree — `186 entries shown · depth limit 2 · scanned 186 · deeper levels cut · scan complete`, heavy dirs `(skipped)` | sse-direxplore-zai-weak-tree_project.sse |
| "Does notes.txt exist in Documents before I save?" | **PASS** dir_explorer/stat (zai-retry, 310s) | sse-direxplore-zai-retry-pre_write_stat.sse |
| "Find my CV under Documents" (regression) | **PASS** — system_search chosen, NOT explorer | sse-direxplore-zai-regress-find_by_name.sse |
| "Run git --version" (regression) | **PASS** — shell chosen, NOT explorer | sse-direxplore-zai-regress-real_shell.sse |
| "Search Documents for 'invoice'" (regression) | see below — repeated provider blocks | zai-grep2 artifacts |

The CORE-tier placement is justified by the weak-model gate: zai/glm-4.5-flash
picked dir_explorer for all three inspection phrasings AND kept
system_search/shell for their tasks (no name-affinity splitting — the exact
failure mode that demoted find_path in S400).

## Harness lessons (live_test_dir_explorer.py)

1. SSE `tool_call` events arrive as started+done PAIRS with the same `id` —
   dedupe or every tool looks like 2 calls.
2. The weak model sent PLAIN STRING args ("list C:\...\Documents True"),
   not JSON — the tool's `_parse_plain_query` absorbed it (good), but op
   extraction must fall back to the loop's structured `Exploring (op): path`
   label (it reads tool_args, not raw input).
3. Score BLOCKED ≠ FAIL: a provider outage must not count as a selection
   failure — the first zai run looked 0/6 but actually measured nothing on
   4 of its rows.

## Other findings

- The stale manifest pointer "update the tools_architecture_proposal.md pins":
  that July proposal doc holds NO schema pins; the real pins are
  `tests/core/test_tool_schemas_lean.py` (size budget + tool count) —
  both updated in the feature commit. Manifest corrected.
- Pre-change full-suite baseline on this tree: 24 failed / 3023 passed /
  4 skipped == the documented Windows baseline exactly; the 2 date bombs
  (B-2026-09-10-4) PASSED during the post-change subset run — the literal
  "September 9, 2026" comparisons flipped as the clock rolled (they're a
  known carry-over item; not mine).
- First live run showed 27 failures in a truncated pipe (my `| tail -5`
  ate the list); the 3 extras were the DNS-dependent
  test_web_fetch_ssrf::test_allows_public_urls trio — passed on rerun.
  Matches Juma's (S463) "4 isolated-pass SSRF flakes documented".
- Git Bash mangles `git show origin/main:path` (colon → path conversion);
  prefix `MSYS_NO_PATHCONV=1`.
