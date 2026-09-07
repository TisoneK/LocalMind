# Session 436 (Noah) — 2026-09-07 — right-click chat menus + export copy-to-clipboard

## Live verification traces (IAB browser on the vite dev build)

- **Input menu, found-bug repro:** value `alpha beta gamma`, selection 6..10
  ("beta") → Cut → clipboard got `beta`, value `alpha  gamma`; reopen menu
  without refocusing → Paste → value `alpha beta gamma`, caret 10. Exact
  round-trip AFTER the fix. BEFORE the fix (caret re-read at click time +
  rAF-only restore): paste landed at value end (e.g. `alpha  gammabeta`).
- **Mid-word paste:** caret 2 in `cut me re pleasehe` + clipboard `he` →
  Paste → `cuhet me re pleasehe`, caret 4-equivalent (captured target used).
- **Transcript menu (empty welcome transcript):** Copy disabled (no
  selection), no Copy-message item, Select all enabled → Select all yields a
  151-char selection → reopen → Copy enabled → clipboard write fired
  (151 chars).
- **Radix quirks learned:** item clicks need a pointerdown/up/click sequence
  (plain userEvent click doesn't trigger onSelect in this runtime); Radix
  renders `aria-disabled`/`data-disabled`, not the `disabled` property;
  a menu opened via synthetic contextmenu is not closed by a synthetic
  Escape on `document` — needed a real outside click or reload.
- **Clipboard in unfocused documents:** Chromium denies `writeText` when the
  document is not focused — the live app's ✗ Clipboard blocked flash is
  correct behavior, not a bug; in the real focused Electron window the write
  succeeds.

## Shared-tree incident (Amina / S437 concurrent on the same checkout)

- S437 published coordination events and a board update from the same `main`
  checkout while my feature was mid-flight, and committed my in-progress
  files as `fbffcac` (accurate message). I verified the commit content
  matched my working tree before continuing; no rebase or revert needed.
- The 2026-09-05 override mandates separate worktrees the moment a peer is
  live — the peer-side pass did not follow it (single shared checkout, no
  claim before touching my in-progress files). Logged in
  inefficiencies/log.md; not escalated since the outcome was clean and both
  agents' scopes stayed disjoint.
- User-visible side effect: the owner's Electron dev app HMR-watches this
  tree (port 3000), so my mid-edit states hot-reloaded into the running app
  — that was the "the program was running well until your changes" report.
  Tree verified consistent; the app renders and the copy flow works.

## Test-flake notes

- Full-suite runs during this session showed the SettingsModal
  timeout-boundary family and, once, FilePreviewDialog + one
  InputContextMenu/LeftPanel timeout — every one of those files passes in
  isolation (56/56 combined run). Matches the S416-documented
  parallel-load flake pattern; nothing pinned to the new components.
- vitest + userEvent: Radix portal items ignore plain userEvent clicks under
  this setup; tests use fireEvent clicks on items and assert
  `aria-disabled` instead of `toBeDisabled()`.
