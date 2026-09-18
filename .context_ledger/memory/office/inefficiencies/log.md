# Inefficiency Log (append-only, mandatory)

Every session appends one block — honestly. Friction you absorb silently
is friction the next agent hits blind. "None this session" is valid only
if literally nothing slowed you down.

Most inefficiencies are project-local (an environment quirk, a one-off
cost) and stay here. When one is actually **protocol-level** — the core
workflow itself made you slower and every project would hit it — mark it
`Upstream: candidate`. `ledger-sync harvest` collects those (and open
`flaws/`) into the package for an upstream fix. Unmarked entries are
never harvested.

Append-only, but prunable to cold storage: once an entry is explicitly
marked `RESOLVED` / `superseded` / fixed, move it **verbatim** into
`archive.md` in this directory so startup reads only the live entries.
`ledger-mem prune` reports which entries are archive-eligible; age alone
never makes an entry eligible.

<!-- TEMPLATE — copy below the last entry:
---
## YYYY-MM-DD — <agent> / <model>
- **Problem:** <what went wrong or was slower than it should be>
- **Cost:** <rough time/effort wasted>
- **Cause:** <root cause if known>
- **Workaround / fix:** <what worked, or "unresolved">
- **Prevent next time:** <protocol/context change that would have avoided it>
- **Upstream:** candidate  ← add this line ONLY for protocol-level friction
  worth a core fix; omit entirely for project-local friction.
-->

---
## 2026-09-12 — Amani / glm-5.3-flash (S1) — two shell-command-shape traps during the backlog re-row verification

- **Problem:** (1) Verifying the re-rowed backlog's escaped table cells failed twice: an inline `python -c "...(?<!\\)\|..."` died with `re.error: missing ), unterminated subpattern`, and the same pattern sent through a quoted `<< 'EOF'` heredoc landed on disk mangled (`\\` arrived as `\`) — quoted heredocs should not expand anything. A first `sed 's/\\\\//g'`-based check then reported two CORRECTLY-escaped rows as broken (it ate the escapes before counting) while masking the one row that genuinely had raw pipes. (2) A single ~90-line Bash command carrying THREE heredoc appends got truncated in flight — the second heredoc ran to end-of-input (bash warning "delimited by end-of-file"), silently appending the third command's text into the wrong file and dropping the third append entirely.
- **Cost:** two failed checker runs + one misleading false-flag pass + one file repair (the truncated session entry) ≈ 15 minutes.
- **Cause:** (1) the Bash tool's command string on this Windows box collapses doubled backslashes before heredoc/inline-script content is written — the same family as the `cmd //c` argument mangling (S460) and the `$VAR`-path mangle (S416); any check that strips escapes before counting also cannot distinguish "escaped pipe" from "raw pipe". (2) very long compound commands are not delivered intact.
- **Workaround / fix:** (1) anything containing backslashes — regexes, escaped pipes, Windows paths — goes through the Write tool into a script file, then runs; the checker counts RAW pipes per row (pipe not preceded by a backslash) instead of stripping escapes first; it caught the one genuine defect (regex literals inside B-2026-08-20-8) on the first try. (2) one heredoc append per Bash command; verify each file's tail immediately after appending.
- **Prevent next time:** never verify escaping with a tool that eats the escapes; never bundle multiple heredoc appends into one command on this box; when a heredoc warns "delimited by end-of-file", assume the LAST files in the command are corrupted or missing and check every tail before committing.

---
## 2026-09-14 — Njeri / qwen3.8-flash (S003)

- **Problem:** none this session — a clean sync-only session (core 1.0.6 → 1.1.1 migration + bookkeeping). The only slip was self-inflicted and caught instantly: a sed with the wrong spacing silently no-op'd on one placeholder (re-checked, fixed with a corrected pattern), and the backslash-mangling trap already logged above bit exactly once (a `--body-file C:\...` path) — the logged forward-slash workaround applied first try, zero extra cost.

---
## 2026-09-15 — Zuri / qwen3.8-flash (S004) — the live-test provider switch is a settings-file edit, not an env var

- **Problem:** (1) `LOCALMIND_ADAPTER=zai` on the harness server env did nothing — the server still dialed bankofai (log proved it). The scratch tracehome's `settings.json` pins `adapter`, and it wins over the env var. **This is the S445/S451-logged trap re-hit** (prior instances recorded in `system/ai-models.md` observations, not in this office's log): the lesson was in the registry but not in `live-testing.md`'s harness section, and one failed run went by before the boot log was read. (2) bankofai is QUOTA-EXHAUSTED (`credit insufficient balance: balance=0` — a 400, not a 429): the primary live-test provider is unusable until the owner tops up or re-keys. (3) Minor self-inflicted: one Edit-tool call anchored an `old_string` that spanned the start of the next test block and silently deleted its body — caught by re-reading the file, fixed in one pass.
- **Cost:** one failed live-test run + one settings-inspection cycle + one test-file repair ≈ 10 minutes.
- **Cause:** (1) `system/live-testing.md` says "provider/model is set in the settings file, NOT backend/.env" but the harness scripts also pass `LOCALMIND_ADAPTER` — implying the env var works; it does not override the settings file. (2) account balance, not code. (3) Edit-tool block replacement: anchoring on a test's closing lines + the NEXT test's opening swallows the gap.
- **Workaround / fix:** to switch providers for a live test, edit `scratch/tracehome/settings.json` (`adapter` + `model` fields; keys untouched) — verified working on zai/glm-4.5-flash. When inserting a test before an existing one, anchor `old_string` on the full opening of the target test and re-add it verbatim in `new_string` (done for the repair).
- **Prevent next time:** fixed at the source this session — `system/live-testing.md`'s gotchas now state the settings file beats `LOCALMIND_ADAPTER` (check the boot log's adapter line) and that a bankofai 400 "insufficient balance" is a hard outage, not a rate limit (fall back to zai, do not retry).

---
## 2026-09-15 — Neema / qwen3.8-flash (S6) — unprovisioned collab worktree vs. the product-requiring pre-commit gate

- **Problem:** in a fresh collab worktree (mandatory while a peer is live, per the project override), the pre-commit gate's `tsc` and `ruff` steps fail — the worktree has no `node_modules`/`.venv` (they live only in the main checkout). The gate reported FAILED on a memory-only (markdown) commit. Worse, piping the gate through `| tail -3` masked its exit code, so the chained command committed anyway under a red gate.
- **Cost:** ~10 minutes of diagnosis + one re-verification cycle (the checks then re-run manually from the provisioned main checkout, both green).
- **Cause:** gates.conf assumes a provisioned tree; the kickoff/override mandate worktrees but say nothing about provisioning them or about which gate steps are meaningful in an unprovisioned one. Also my own shell pattern: `cmd | tail` returns tail's status, not cmd's.
- **Workaround / fix:** for memory-surface-only commits in a worktree — run the memory-meaningful steps directly (`check-conflict-markers.sh`, `check-backlog-duplicates.sh`, `git diff --cached --check`), which all run dependency-free, and verify the product steps (ruff/tsc) from the main checkout when its product tree equals origin/main; full `ci-check.sh` (incl. pytest + eslint) run at exit from the provisioned main checkout.
- **Prevent next time:** never pipe a gate through `tail`/`head` and chain commits — run it bare and read the verdict; a worktree where `git add` touched only `.context_ledger/**.md` cannot break tsc/ruff, and the two memory scripts are the gate's actually-relevant teeth.
- **Upstream:** candidate — the protocol's collab-worktree flow should state which gate steps degrade when the worktree is unprovisioned (every collaboration project hits this).

---
## 2026-09-15 — Imani / qwen3.8-flash (S008) — Windows console traps: cp1252 stdout and commit-message quoting

- **Problem:** two one-shot losses to the shell rather than the code. (1)
  `scripts/lm_benchmark.py` prints a `→` per test line; under PowerShell's
  cp1252 console the run crashed mid-report with UnicodeEncodeError (server
  already booted, test already passed — pure output-encoding loss). (2)
  `git commit -m` with a message containing `{"type": "done"}` and escaped
  quotes broke parsing ("fatal: Invalid path '/done'").
- **Cost:** two reruns, ~3 minutes.
- **Cause:** (1) Python defaults stdout to the console codepage on Windows;
  the harness's own summary lines are non-ASCII. (2) PS 5.1 + git's argument
  quoting around embedded double quotes.
- **Workaround / fix:** set the Python UTF-8 mode env var (PEP 540,
  `PYTHONUTF8=1`) before any harness/benchmark/gate run on this box — it fixes
  BOTH the stdout codepage AND `read_text()` defaults (five
  source-grepping tests — `test_tool_execution_failure`,
  `test_iteration_limit_and_safety`, `test_obs_drain_bug`,
  `test_empty_agent_fix` — call `read_text()` on files containing a UTF-8
  emoji (`⏹` = byte 0x8f, invalid in cp1252) and fail ONLY because the default
  locale is cp1252; under `PYTHONUTF8=1` they pass). `PYTHONIOENCODING=utf-8`
  alone fixes stdout but NOT `read_text()`. Separately: write commit messages
  with embedded quotes or braces to a scratch file and use `git commit -F`.
- **Prevent next time:** both are the standing Windows pattern now — UTF-8 env
  for scripts, `-F` for fiddly messages.

---
## 2026-09-15 — Jabari / qwen3.8-flash (S010) — the harness port is shared office state: 8765 was already a peer's live server

- **Problem:** the standing live-test bar says "isolated 8765, never 8000". I
  launched my BEFORE-scenario backend on 8765 and it exited 42 (port in use).
  The occupant was a peer's still-running `server.py` (zai/glm-4.5-flash
  harness) — a process I must not kill. Reusing the single documented port for
  a second concurrent session's harness doesn't work when a peer is live.
- **Cost:** one failed launch + a `netstat`/`Win32_Process` detour to identify
  (and correctly NOT kill) the owner, ~4 minutes.
- **Cause:** "8765" is written as *the* harness port, but in a multi-agent
  office it's a shared resource with no claim protocol — the first session
  that boots owns it until it exits.
- **Workaround / fix:** pick a per-session free port (I used 8767 = 8765 +
  session offset) and verify it's free before launching. `Get-NetTCPConnection
  -LocalPort <p> -State Listen` or let the server's own exit-42 fail-fast tell
  you. Never kill the occupant — it's a teammate's harness, not an orphan.
- **Prevent next time:** in a live office, treat the harness port as
  per-session (offset by codename number) rather than the literal 8765; a
  quick listen-probe before boot is the discipline.

---
## 2026-09-15 — Tega / qwen3.8-flash (S009) — the cell-edit tool can write a phantom import and skip the definition it was told to add

- **Problem:** inserting the BestOfNSection component into ChatMessage.tsx
  via the IDE cell-edit tool produced a file with the usage line AND an
  import of a module that does not exist ('./BestOfNSection'), but NOT the
  component definition itself — a corruption no linter would call out by
  name (tsc did, but only after a full run).
- **Cost:** one tsc error hunt + manual re-edit; trust in 'successful' edit
  tool results now costs a verification pass.
- **Cause:** large multi-region inserts through the edit tool are applied
  heuristically; a same-file 'insert' can land the reference but mangle the
  definition block. The tool reported success.
- **Workaround / fix:** after ANY structural insert into an existing file,
  grep the actual file (Select-String for worktrees — workspace search only
  sees the main tree) for the symbol's definition and its import before
  compiling.
- **Prevent next time:** prefer one explicit replace_string_in_file anchored
  on surrounding code for adding definitions; treat cell-style inserts on
  code files as unverified until re-read.

---
## 2026-09-15 — Tega / qwen3.8-flash (S009) — async terminal mode strips Set-Location, silently running commands against the wrong tree

- **Problem:** a background (async) command written as
  `Set-Location <worktree>; <python> -m pytest ..\tests` was 'simplified'
  by the runner to just the python part — cwd stayed the MAIN tree, so the
  relative `..\tests` resolved to nothing (or worse: to the peer's tree).
  The first full-suite 'baseline' was actually measured in the wrong
  checkout.
- **Cost:** one mis-targeted 4-minute suite run + a confusing
  'file or directory not found'; re-ran to confirm.
- **Cause:** the async execution path rewrites the command line and drops
  the cd prefix; relative paths then silently mean something else.
- **Workaround / fix:** in worktree/peer-adjacent layouts, pass ABSOLUTE
  paths for test targets (and cwd via Set-Location only in sync mode), or
  verify the reported rootdir line of the tool output matches the intended
  tree.
- **Prevent next time:** never combine Set-Location + relative paths in an
  async terminal command; absolute paths are the habit here.

---
## 2026-09-16 — Baraka / qwen3.8-flash (S005) — shell-output traps recurred; plus the blind-transform near-miss

- **Problem:** (1) A long `python - << EOF` heredoc with multi-line replacement strings got truncated in flight AGAIN (known trap, logged 2026-09-12) and a `ValueError: not enough values to unpack` shipped from a half-applied tuple table; (2) piping the exit-gate through `grep | head -15` closed the pipe early and the gate VERDICT was lost, forcing a 7-minute full re-run; (3) a first-pass regex transform for tests/ demonstrably corrupted `demo.py`-style lines (spaced-punctuation cleanup firing on CODE lines) — caught by dry-run review before any write; (4) `git grep -v` with backslash paths silently matched nothing (Git Bash prints `\` paths).
- **Cost:** ~15 min (re-runs + bisect of pre-existing gate failures).
- **Cause:** Windows Git-Bash + long inline commands; head-truncated pipes hiding exit codes; over-clever global regex post-processing.
- **Workaround / fix:** replacement TABLES live in Write-tool'd scratch scripts (never inline heredocs); the exit gate redirects to a scratch file then greps the file; global "cleanup" regexes were deleted in favor of per-file exact pairs with count assertions; grep filters use forward-slash paths.
- **Prevent next time:** gate output goes to a file, always; dry-run any bulk transform and READ every changed line before writing; count-assert every table row.

---

## 2026-09-16 — Chemi / Qwen3.8 Flash (S013)

- **Problem:** the session's own Bash tool dropped a heredoc code-fence marker mid-command on this box (the same mangling family logged 2026-09-12 and 2026-09-15), which garbled one work-note into a stray fenced block; separately, my triage script's row parser terminated rows only on the FOLLOWING line, so a single-line row at EOF (the 84th) read as unterminated, and an aliasing bug (`lines[-1]` == `lines[0]` on single-line rows) briefly built the parking lot with orphan duplicate lines before verification caught the shape and the clean rerun fixed it.
- **Cost:** roughly six rerun-verify cycles and one contaminated working tree (rebuilt from git HEAD) ≈ 25 minutes.
- **Cause:** inline heredocs remain unreliable on this Windows box regardless of content; parser termination state that only updates between lines cannot validate the final row; and a build that mutates a list it also slices aliases the original.
- **Workaround / fix:** scripts and multi-line content go through the file-writing tool, never inline heredocs (re-learned); parsers track per-row completion immediately (end-of-row check on the same line); builds that substitute cells operate on the new string, not the aliased list.
- **Prevent next time:** same standing rule, now three-times-logged: nothing with backslashes, fences, or multi-line structure is trusted to an inline heredoc; verify counts and shapes immediately after any generated-file write (the orphan B- lines were caught by a shape assert, not by eye).

---

## 2026-09-17 — Buffy / model unknown (S014) — three tool-layer traps on the Windows box

- **Problem:** (1) the `code_search` tool is dead on this machine — every call
  fails with `ENOENT ... vendor/ripgrep/x64-win32/rg.exe` (the bundled ripgrep
  is missing from the Freebuff install), so content searching has to fall back
  to `grep -rn` in the terminal; (2) the live-trace harness aborted mid-run with
  `UnicodeEncodeError: 'charmap' codec can't encode character` the moment the
  model's answer contained a non-ASCII character — the Windows console is
  cp1252 and the trace printed model text to stdout, killing a run that had
  already spent provider calls; (3) the full backend suite exceeds the 600 s
  command ceiling (3094 tests), so a SYNC run is killed part-way with no
  results.
- **Cost:** ~10 minutes re-deriving search results through grep; one wasted
  live pass (three turns of provider calls) before the encode fix; two aborted
  full-suite runs.
- **Cause:** (1) a missing vendored binary in the desktop app's install, not
  project code; (2) `print()` of model output inherits the console encoding,
  and `errors="replace"` was never set on stdout; (3) the suite's wall time is
  roughly 20 minutes on this box under load.
- **Workaround / fix:** (1) use `grep -rn -E` with explicit file globs; (2) call
  `sys.stdout.reconfigure(errors="replace")` at the top of any live-trace script
  and run it with `PYTHONUTF8=1` (this also clears the long-standing cp1252
  UnicodeDecodeError family in the source-grepping tests — the same fix the
  queue item for `scripts/ci-check.sh` asks for); (3) launch the suite with
  `nohup ... &` writing to `scratch/<session>/pytest-full.log` and poll the log
  — the backgrounded process survives the tool call on this box, unlike a SYNC
  run against the 600 s ceiling.
- **Prevent next time:** in live-trace scripts, reconfigure stdout at entry
  (a trace must never die on its own output); for the full suite, always log to
  a file and poll. Neither is a product bug — recorded so the next session does
  not re-pay for the diagnosis.

---

## 2026-09-18 — Buffy / model unknown (Session 14, extended)

- **Problem:** (1) a backgrounded full-suite launch (`pytest ... &` inside a
  SYNC tool call) does not return when the child keeps the call's streams open —
  the call hangs until its timeout (this session: the 30 s ceiling, then the
  connection dropped); blindly re-launching on retry would have run two
  3000-test suites concurrently. (2) Seeding a live trace's store through the
  app's own `POST /api/memory` 503s on an embedder-less box (the route embeds
  every write; Ollama down, no cloud key) — the previous session's REST-seed
  plan cannot work here.
- **Cost:** one hung call plus a tasklist round-trip to notice the orphan;
  ~20 minutes of harness redesign (REST seed → direct insert) mid-trace.
- **Cause:** (1) the child survives the call (the nohup pattern holds) but the
  CALL does not return promptly — and after a connection drop the retry reflex
  is to relaunch, not to look; (2) the embed dependency in the REST route is by
  design; the seed only needed an equivalent row written another way.
- **Workaround / fix:** (1) after a dropped/hung background launch, check
  `tasklist | grep python` and the log file's growth BEFORE relaunching — the
  orphaned suite is usually still working; poll its tail and reuse it. (2) Seed
  by inserting `(id, content, metadata)` rows directly into `vector_facts`
  while the server runs — the store re-reads the table on every call
  (`list_all_with_metadata`, the forget ladder, the routing reads all see it
  immediately) — then verify through `GET /api/memory`. (3) For connection
  drops generally: the recovery that worked each time was the checkpoint gate +
  `git status` + re-reading `current.md`/roster/claim state before touching
  anything.
- **Prevent next time:** live harnesses that need a seeded store should ship
  the direct-insert seed (with the /api/memory verification) instead of the
  REST route; never re-launch a background suite without checking for the
  orphan first.

---
## 2026-09-18 — Zola / claude-sonnet-5 (S016)

- **Problem:** none this session — a clean sync-only session (pull + verify/status, no core update since the available bump is MAJOR).
