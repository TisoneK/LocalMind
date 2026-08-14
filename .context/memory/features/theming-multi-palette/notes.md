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
