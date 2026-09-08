<!-- Feature notes — append-only. -->
# theming-multi-palette — notes

## Session 217 (2026-08-14) — token architecture + 6 palettes
Restructured `globals.css`: 25 semantic anchors, `--brand-*` + shadcn
tokens mapped onto them, 6 theme×mode blocks (graphite/iris/warm ×
light/dark), per-mode ANSI palette, accent-tinted `::selection`. Default
`:root` = graphite dark (so no-attribute load works). Verified in-browser
by flipping `document.documentElement.dataset.theme/mode` and reading
computed `--brand-green`/`--brand-bg-base`/`--background` for all 6 — all
correct; shadcn `--background` tracks `--brand-bg-base`. App renders clean
(body bg #12161d graphite), no console errors. 173 tests / build green.
`40930e0` + changelog `ca4801a`.

Naming wart to note: `--brand-green` now holds the accent (emerald in
graphite, indigo in iris, gold in warm) — the color-named tokens are
legacy role-holders. Kept the names to avoid a risky component-wide
rename; a future session could migrate components to `text-accent` etc.

Next (S218): `useTheme` hook + Settings picker. Persist to localStorage
key e.g. `localmind-theme` = {theme, mode}; apply `data-theme`/`data-mode`
on `<html>`; for mode='system' add a matchMedia('(prefers-color-scheme:
dark)') listener. Add a no-FOUC inline script in index.html that reads
localStorage and sets the attributes BEFORE first paint.

## Session 218 (2026-08-14) — runtime switcher + Settings picker
`useTheme` hook (useSyncExternalStore module store; localStorage
`localmind-theme`; applies data-theme/data-mode; system-mode matchMedia
listener). No-flash inline script in index.html. SettingsModal Appearance
section (3 theme cards + Light/Dark/System toggle). Browser-verified the
no-flash init (iris/light applied pre-paint on reload). 178 tests / tsc /
build green. `810323b` + changelog `fdac625`. Next S219: light-mode
contrast sweep + grep components for hardcoded hex/rgb that dodge tokens.

## Session 219 (2026-08-14) — light-mode color correctness (feature COMPLETE)
Grepped `src/components` for non-token colors. Fixed AgentPhases
(`text-*-400` → brand tokens; undefined `text-brand-muted/60`,
`text-brand-fg-muted`, `text-brand-muted/70` → real tokens — these
rendered NO color, a latent bug), FileExplorer `group-hover:text-white`
→ `text-brand-green`, and `bg-white/[0.0x]` hovers → `bg-brand-border/4x`.
Kept modal `bg-black/50` backdrops + shadcn filled-button `text-white`
(correct both modes). 178 tests / tsc / build green. `6979fe3`.

**FEATURE COMPLETE (S217-219):** 3 palettes × light/dark, Settings-
selectable + persisted + no-flash. Palettes are v1 — a human visual/taste
pass per palette (esp. warm-light muddiness, accent contrast on light) is
the only remaining follow-up, tunable purely in the globals.css anchor
blocks. Grep to re-audit: `grep -rnE '#[0-9a-fA-F]{6}|bg-white/|-(blue|green|amber|red|purple)-[0-9]{3}' frontend/src/components`.
