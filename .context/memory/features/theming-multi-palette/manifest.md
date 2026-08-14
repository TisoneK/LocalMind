<!-- Feature manifest — update-in-place. -->
# Feature: theming-multi-palette

- **Slug:** theming-multi-palette
- **Started:** 2026-08-14 (Session 217)
- **Status:** active
- **Ledger:** see `.context/memory/features/ledger.md`

## Goal
User wants the "too green" UI redesigned into a real theming system:
3 palettes — **Graphite & Emerald**, **Midnight Iris**, **Warm Ink** —
each in **light and dark**, user-selectable in Settings. Reverses the
Session-103 dark-only decision (ADR-31).

## Architecture (S217, shipped)
Legacy `--brand-*` tokens map ONCE onto semantic anchors (`--acc*`,
`--s-*`, `--t-*`, `--line*`, `--warn/--danger/--info/--alt`, `--code-text`)
in `globals.css`; shadcn/ui tokens route through the same anchors. Each
theme × mode sets only the ~25 anchors → whole app + shadcn retheme with
ZERO component changes. Applied via `<html data-theme data-mode>`. ANSI
(`--brand-gh-*`) + scrollbars vary by mode only. Default = graphite dark.

## Sessions
- [x] **S217 — token architecture + 6 palettes** (done 2026-08-14, `40930e0`,
  ADR-31): anchor layer + all 6 theme×mode blocks; default graphite dark;
  accent-tinted selection. Verified all 6 combos resolve via data attrs
  (incl. shadcn `--background`), default renders clean, 173 tests/build green.
- [ ] S218 — runtime: `useTheme` hook (persist localStorage + apply data
  attrs + system-mode matchMedia listener), no-FOUC init script in
  index.html, theme+mode picker in SettingsModal.
- [ ] S219 — light-mode contrast sweep + hunt hardcoded hex that dodges
  the tokens (grep components for literal `#`/`rgb(`); real visual pass.

## Constraints
- Zero component churn (anchor mapping preserves `--brand-*` names).
- Preserve relative surface ordering from the original palette.
- The `--brand-green`/`--brand-amber` NAMES are now legacy (hold accent/
  warn roles); a future session may rename to semantic classes.
