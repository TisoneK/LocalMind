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
