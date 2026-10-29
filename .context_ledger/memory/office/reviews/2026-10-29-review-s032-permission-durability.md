# Session review — Kiano (S032), 2026-10-29 — permission modes + durability barriers (§U item 5, rows H + J)

## What this session set out to do
The owner split a terse "pull and do durability and permission work" handoff
into three parallel sessions; this one owns the durability + permission lane of
**§U item 5** from `docs/reference-harness-gap-inventory.md`: row **J** (session
durability barriers) and row **H** (a permission-mode surface grown from the
propose-apply flow). Row D (spill fidelity) was explicitly not in this lane, and
the trajectory sibling covers row G.

## What I found before writing code
- The permission kernel already existed but was the wrong shape: a flat,
  **global** per-tool boolean dict (`settings.localmind_permissions`, config.py),
  checked in `dispatch_with_retry`. No named modes, no per-session pin, no
  fail-closed posture, no audit. (Row H: "partial — the propose-apply flow is
  the kernel of a mode system.")
- Session persistence is SQLite (`storage/db.py`), messages persisted at turn
  end. No crash-during-tool semantics. (Row J: "partial.")
- A real seam trap: `file_write` and `edit_file` do **not** go through
  `dispatch_with_retry` — they run via a typed-contract path in `loop.py`
  (`ToolRegistry.get("file_write").execute(...)`). A gate placed only at
  `dispatch_with_retry` would silently miss the two tools that matter most.
  The live test caught exactly this (probe A let a read-only write through on
  the first pass), which is why the enforcement is now a shared helper used by
  **both** paths.

## What I changed
- **`core/permission_mode.py`** (new): three named modes — `read_only`,
  `workspace_write` (default), `full` — and a *pure* `decide(mode, intent)` that
  denies file-effecting intents under read-only, permits them under
  workspace/full, and **fails closed** (denies) when the mode is unresolved.
  Effecting intents: file_write, file_edit, apply_proposed, shell, code_exec.
- **`storage/db.py`** (+ migration `014_permission_modes.sql`): `session_permissions`
  pins the mode per session durably (survives restart, never crosses sessions);
  `permission_audit` is the model-invisible record of every decision AND the
  write-ahead journal — an allowed effecting call is written `pending` before its
  body, resolved `done`/`failed` after. `reconcile_interrupted_effects()` runs on
  store open and moves any surviving `pending` row to `unknown` (interrupted call
  recovered, never silently re-executed). `delete_session`/`clear_all` clear both.
- **`core/agent/tool_dispatch.py`**: shared `gate_file_effect` / `resolve_file_effect`
  — the one policy. Session id comes from the existing `current_session_id()`
  contextvar (engine sets it per turn), so no loop plumbing was needed for the
  dispatch path. Fail-closed resolution: a missing store or a raised read denies;
  the *absence* of a session (unit tests, bootstrap) is the shipped default, so
  no-session behaviour never regressed.
- **`core/agent/loop.py`**: the same shared gate wraps the typed-contract path
  (file_write / edit_file) so every tool path is covered with no bypass.
- **`core/config.py`**: `is_path_allowed` now lifts its folder boundary only when
  the running session is pinned `full` (lazy, defensive — any failure keeps the
  boundary). This is the genuine workspace↔full distinction for the
  boundary-checking tools; raw `file_write` resolves home-anchored and never
  consulted the boundary, so full↔workspace is identical for it (documented).
- **API** (`api/routes/sessions.py`): `GET`/`POST /api/sessions/{id}/permission-mode`
  (unknown modes rejected so a bad value can't be persisted), `GET …/permission-audit`.

## Verification
- `tests/core/test_permission_mode.py` (pure decide + store round-trip + restart
  durability + audit + reconcile + the full-mode path lift) and
  `tests/core/agent/test_dispatch_permission_gate.py` (deny / allow+journal /
  fail-closed / pass-through) — 24 new tests.
- Full backend suite green (3764 passed / 2 skipped before the loop.py gate;
  re-run after it — see the session entry for the final count). tsc + eslint clean.
- **Live** (`scripts/live_test_permission_durability.py`, real server on 8765 with
  a wire-faithful fake provider — the §U precedent, and the gate is model-agnostic):
  probe A read-only denied a write before its body ran (file absent, deny audited);
  probe B workspace_write allowed it and the journal resolved pending→done; probe C
  the pin survived a real server restart; probe D a crash-left `pending` row was
  reconciled to `unknown` on the next boot. PASS.

## Still open (follow-ups filed)
- **Frontend selector** — the mode is fully enforced and API-exposed but not yet
  surfaced in Settings; row H's "one selector" is backend-complete, UI pending.
- **Mixed-intent effecting tools** — git (commit vs status), process (start vs
  logs), browse (click vs read) are effect-capable but their effect depends on the
  sub-command, so they are not yet mode-gated. Needs sub-command classification.
- Row **D** (spill/shadow fidelity) of §U item 5 remains, by scope, untouched here.
