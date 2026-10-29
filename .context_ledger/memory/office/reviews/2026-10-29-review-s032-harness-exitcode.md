# Live-test harness exit codes — the proof that passed but exited 1

Follow-up to the friction S031 logged on 2026-10-29
(`office/inefficiencies/log.md`): three live-test harnesses printed `PASS`
and then exited non-zero, so a green proof read as a red command. S031 fixed
the pattern in the new `live_test_done_rules.py` and left the three older
harnesses for "whoever is next in them — one-line fix each." This session is
that follow-up. One of three concurrent isolated-worktree sessions split from a
single hand-off (the other two: durability+permissions, trajectory-view
projection); this one touched only the harness exit-code concern.

## Root cause (model- and env-agnostic)

Each harness runs its fake OpenAI-compatible provider on a
`ThreadingHTTPServer` thread **inside the harness process**, then on teardown
calls `kill_port(FAKE_PORT)`. `ThreadingHTTPServer.shutdown()` stops the serve
loop but does **not** close the listening socket — only `server_close()` does.
So at the moment of the sweep the fake's port is still held by the harness
itself. On Windows `kill_port` is `netstat -ano` → `taskkill /F` every PID
`LISTENING` on that port, and the only such PID is the harness: it taskkills
itself, silently, **after** `main()` has already printed `PASS` and returned 0.
The process dies by signal, so the shell sees a non-zero exit for a proof that
passed. (On POSIX `kill_port` is `pkill -f LOCALMIND_PORT=<port>`, which never
matches the harness command line, so the bug is Windows-only in effect — but
the left-open listening socket is the same on every platform, which is what
made an env-agnostic proof possible.)

This is not a weak-model or local-only symptom: it is a process-teardown
ordering bug in the harness itself, independent of any provider or model.

## The fix

`live_test_done_rules.py` (S031) already carries the correct teardown: close
the fake's listening socket before any port sweep, and drop the now-pointless
`kill_port(FAKE_PORT)` (nothing outside this process ever binds it). The same
change, line-for-line, is now in the three older harnesses:

- `scripts/live_test_provider_death_honesty.py`
- `scripts/live_test_identity_injection.py`
- `scripts/live_test_provenance_symmetry.py`

Each `finally` block went from `shutdown() → kill_port(PORT) →
kill_port(FAKE_PORT)` to `shutdown() → server_close() → kill_port(PORT)`, with
the same explanatory comment the reference harness carries. The pre-boot sweep
(`kill_port(PORT); kill_port(FAKE_PORT)` before `boot_fake()`, which clears a
stale listener left by a previously crashed run) is unchanged — it is correct
and necessary. Each `__main__` is `sys.exit(main())`, so once the process is no
longer killed during teardown, `main()`'s real 0/1/2 reaches the shell on both
the PASS and the FAIL path.

## Verification

- **Mechanism, env-agnostic (ran here):** a focused repro starts a
  `ThreadingHTTPServer` in-process, then models the Windows sweep as "which PIDs
  are LISTENING on the port" (read via `lsof`, the portable equivalent of the
  `netstat` the Windows path parses). After `shutdown()` alone the port is still
  held and the sweep set is `[<harness pid>]` — the self-kill. After
  `server_close()` the port is free and the sweep set is empty. So the fix
  removes the harness's own pid from the teardown sweep; its exit code survives.
- **Syntax:** all four harnesses `py_compile` clean; `ruff check backend/src`
  passes (backend untouched — scripts live outside the ruff target, so this only
  confirms no collateral).
- **Not run here, and why:** the real end-to-end harness run against the booted
  backend was not reproduced on this macOS host — (1) on POSIX the failure does
  not manifest (pkill no-op), so a real run exits correctly with or without the
  fix and proves nothing about the Windows path; (2) this machine has no node
  deps and the worktree's backend is ahead of the only installed venv, so a full
  live run would test mismatched backend code. The platform-independent
  mechanism proof above is the rigorous substitute; a Windows session can
  re-run the three harnesses to confirm the exit code end-to-end.

## Scope held

Backend/frontend product code untouched; no `.context_ledger/core/` writes. The
change is three identical teardown edits plus this session's bookkeeping.
