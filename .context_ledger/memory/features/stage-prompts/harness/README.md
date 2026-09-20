# Stage-prompt experiment harness (S024, 2026-09-19)

Copied out of a temp scratchpad so the experiment can be rerun. Not product code.
Paths are hard-coded to the S024 machine (`/Users/bao/Code/LocalMind`, the worktree
`/Users/bao/Code/LocalMind-imani`, fixture `/Users/bao/s024-fixture`) — adjust the
constants at the top of `cmp_run.py` / `cmp_wrap.py` before use.

- `cmp_wrap.py` — boots `backend/server.py` behind an httpx tap. Variant `A` = current input;
  `C` = compact strict system prompt (COMPACT_HEAD, machine facts kept); `D` = C + one-sentence tool
  schema descriptions. Records every LLM request (messages, sizes). Never records headers or keys.
- `cmp_run.py <variant> <port> <tag>` — one isolated turn (scratch `LOCALMIND_HOME`, own port, key
  read via `scripts/harness_common.provider_key`, never printed), scored against the fixture.
- `cmp_runner.py <N>` — serial, interleaved A/C/D, retries a run that errored (60 s cooldown, 3 attempts).
- `cmp_stats2.py` — scores GATHERED EVIDENCE from the captured requests (robust to a rate-limited
  final synthesis) and reports clean-final correctness separately; Fisher exact + permutation tests.
- `resp_wrap.py` — taps the raw response stream (finish_reason, content/reasoning/tool-call sizes);
  this is what exposed the whitespace-content bug.

Fixture (recreate): `projects/{alpha,beta,gamma,delta,epsilon}`; `repo/` git repo with three commits,
latest subject `fix: handle empty config gracefully (#42)`; `repo/pkg/core` with 12 `.py` files
(6 top-level, 3 in `util/`, 3 in `io/`). Prompt: list the folders, the latest commit message, and the
`.py` count. Run ONE run at a time per provider key — parallel runs trip z.ai's 1302 rate limit.

## DeepSeek generalization (2026-09-20)
- `ds_wrap.py` / `ds_run.py` / `ds_runner.py` / `ds_stats.py`: provider- and task-generic versions.
  `PROVIDER`/`MODEL`/`TASK` (`list` = multi-part read-only lookup, scored from GATHERED EVIDENCE; `write` =
  create a file listing the folders and read it back, scored from the FILE STATE) come from env;
  `REPO_DIR` selects the code under test (use a FROZEN `git worktree add --detach` snapshot — a moving
  worktree contaminated the first attempt; never rebase the tree an experiment is reading).
  `python3 ds_runner.py <N> <provider> <model> [pause_s]`; then `python3 ds_stats.py <provider>`.
- `fx_runner.py`: 15 runs of variant A from a chosen worktree (used to verify the tool-result stubbing fix).
- Provider failover (`adapters/failover.py`) is inert in these runs because the scratch settings hold ONE key.

## Input-selection experiment (2026-09-20)
`s_wrap.py` (variant `S` = staged prompt emulated by request rewriting), `s_run.py` (5 tasks: list, write, edit, find, sys;
`find`/`sys` are tool-SELECTION tasks scored on the first tool), `s_runner.py` (A vs S), `s_stats.py`; `p2_runner.py` compares two
CODE TREES (main snapshot vs a worktree) with no rewriting — use this to verify a product change. Fixture and paths as above.
