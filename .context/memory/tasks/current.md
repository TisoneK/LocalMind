# Current Task

**Status:** IDLE — Session 378 root-caused and fixed the repeated-listing flaw from the Windows "analyze the dev folder" transcript (the loop re-ran near-identical `Get-ChildItem` listings 5× because exact-match dedup missed cosmetic reformulations).

## Session 378 outcome

- **Repeated-listings dedup (`79716fa`):** structural inspection fingerprint (`_inspection_fingerprint`) folds same-target + same-flags read-only calls (shell listing/read prefixes, browse, git read ops, file_task, find_path) onto the per-turn cached observation. Flags that change the result set (`-Force`, `-type f`, `-maxdepth 1`) stay distinct; short bundles normalize (`-la` ≡ `-a -l`); presentation (`-AutoSize`, column lists) is dropped from the key. ANY possibly-mutating call (file_write/edit/code_exec, non-read git ops, compound/unknown shell) clears the cache, so a listing after a write always runs fresh — dedup never serves stale output.
- **Prompt rule 10 (`TOOL OUTPUT IS RETAINED`):** a `[...TRUNCATED DUE TO LENGTH...]` marker drops only the MIDDLE (head+tail survive) — never re-run a read just to change formatting/columns.
- **Budgets:** `test_prompt_size_budget.py` bumped +300–400 chars per execute intent for rule 10 (per the guardrail's justify-contract).
- **Verification:** 2488 backend passed / 2 skipped (13 new tests: fingerprint collapse/distinctness, mutation invalidation with 2 real runs, loop-level 1-run dedup); ruff clean (2 pre-existing loop.py E501s + budget-test I001 left untouched).
- **Next:** next open backlog item — B-2026-08-23-8 (goal-driven agent, High/architecture) or the UI-adjacent ones (-20 code-block preview rewrite, -21 time formatting, -22 token short-form, -24 no hardcoded CSS). Pre-existing untracked trace residue at `backend/Dev/` + `backend/scratch/` left untouched.