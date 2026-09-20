# Notes: stage-prompts (append-only while alive)

## 2026-09-19 — Imani (S024)
- Method that worked: tap the HTTP layer (requests AND streamed responses) in a harness outside the repo;
  it found three input/adapter bugs no log showed. Keep doing this before changing any prompt.
- Serial runs only per provider key; count `429` per run; a "valid" run needs a clean final synthesis
  (look for "rate-limited on my final synthesis" in the answer), not just no error event.
- The repo's HEAD moves while agents work — never score against the live repo; use the fixture.
- glm-4.5-flash with thinking ON: reasoning-only replies were an ADAPTER bug (fixed), not model behavior.

## 2026-09-20 — Imani (S024), first DeepSeek round
- Prompt rules are load-bearing: removing the multi-part/act-not-announce paragraph made DeepSeek stop after
  one tool 15/15 times. Any compaction must be eval-gated, rule by rule.
- Score BOTH gathered evidence and the final answer: evidence 13/15 vs final answer 5/15 exposed a context bug
  (tool-result stubbing), not a prompt problem. Reading the tool results AS THE MODEL SAW THEM at its final call
  (from the captured request) is what showed the mid-list cut.
- Never rebase/checkout the tree an experiment reads (a peer commit with provider failover landed mid-run);
  use a detached snapshot worktree. Failover stays inert if the scratch settings hold one key.
- A test that scans the real home (`Path.home()`) hangs once the machine holds a big tree (worktree
  node_modules) — fixed by isolating HOME in tests/tools/test_system_search.py.

