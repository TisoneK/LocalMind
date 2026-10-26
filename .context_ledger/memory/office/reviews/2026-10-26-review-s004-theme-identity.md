# S004 Review — Theme re-identity: the palettes are ours (2026-10-26)

**Agent:** Ezra (S004) | **Model:** GLM (Z.ai) | **Platform:** Linux cloud sandbox
**Scope:** product (frontend theme system + backend settings API) + ledger memory
**Status:** shipped, verified, pushed

## What was asked

The owner picked names for the two palettes whose identity the app had
borrowed: the default skin becomes **Graphite Blue**, the emerald-accent
palette becomes **Graphite Green**. The rename had to be a creative
re-identity — not a blind scrub: the vendor adapter for the DeepSeek API
stays (that is a provider, not an identity), and generic engineering
"harness" vocabulary (test harness, agent harness) stays. The owner then
added two directives: the upcoming commit must not carry the moved-away-from
name anywhere, and **Graphite Blue must be the default palette, in dark
mode, on every path**.

## What shipped

- **Identity rename (`c4b5d8f8`):** theme id `graphite-blue` ("Graphite Blue",
  blue accent `#5686fe`) and id `graphite` re-labelled "Graphite Green"
  (emerald accent `#34d399`). Touched: `useTheme.ts` (ThemeName union, THEMES
  labels/blurbs/swatches, default appearance, clearCustomTheme), `index.html`
  (`data-theme` attribute + the no-flash pre-paint script), `globals.css`
  (all three selector blocks: dark, light, and the bare surface mapping), and
  the backend (`valid_themes`, `SettingsResponse` default, `_read_appearance`
  fallbacks). SettingsModal's "Reset to built-in theme" now returns to
  graphite-blue.
- **Clean break instead of an alias:** the first draft kept a compat alias so
  stored choices under the retired id would migrate. The owner's directive
  (no name in the commit) closed that door — the alias strings themselves
  would have carried it. A stored choice under the retired id now falls back
  to the default, which is the same look, so nothing visible changes for the
  user. Zero occurrences of the retired id remain in source, commit messages,
  CHANGELOG entries, or new ledger text; dated S002 history keeps its
  provenance untouched.
- **Latent product bug fixed on the way:** the backend's `valid_themes` never
  contained the default palette's original id, so saving the default from
  Settings always failed with a silently-swallowed 400. Worse: the fresh-install
  fallback in `_read_appearance()` served the GREEN palette, so a new user got
  Graphite Green despite every frontend default saying blue. All backend
  default sites now read `graphite-blue` + `dark`.
- **Comment provenance scrubbed:** "Ported from …" attributions in
  `sessionReading.ts` (+test), `ChatStatsStrip.tsx`, `CenterPanel.tsx` were
  rewritten as our own contract wording.
- **Ledger memory (`145b9561`):** `system/ui-architecture.md` records the
  decision and the migration semantics.

## Migration design (clean break)

Three persistence paths existed for a theme choice: localStorage
(`localmind-theme`), the pre-paint script in `index.html`, and the backend
settings file. With the alias removed, an unknown id takes the same route in
all three: it fails validation and the default (Graphite Blue, dark) applies.
Because the retired id and the new default render identically, a user who had
saved the old default sees no visual change; users who had saved OTHER
palettes keep them (their ids were never renamed — only the emerald palette's
display label changed, and ids are what get stored).

## Verification

- Frontend: vitest **618/618 across 59 files** at commit time (**619/619** on
  the rebased tree after the peer's composer tests landed; includes the
  reworked tests: an unknown id is ignored and the default applies;
  graphite-blue persists); production build (`tsc -b && vite build`) clean.
- Backend: `tests/api/test_config_adapter.py` **14/14** (includes POSTing
  every built-in id round-trip).
- **Live test** (isolated harness: port 8765, scratch `LOCALMIND_HOME`, never
  port 8000, probe kept sandbox-side at
  `/home/z/my-project/scripts/test_theme_default_live.py`): fresh home →
  `GET /api/settings` serves `theme="graphite-blue"`, `mode="dark"`; all four
  built-in ids POST→GET round-trip; an unknown id → HTTP 400 with the last
  valid value kept.
- Ledger gates: pre-commit, integration, and exit (full CI + bookkeeping
  currency) — run for the closeout; results in the session entry.

## Friction logged this session

- `flaws/log.md`: the supervisor had to ask "Pushed??" — commits sat unpushed
  against the standing push policy while the board and session log went stale.
  Correction + standing rule recorded there.
- `inefficiencies/log.md`: palette ids are validated by two independent lists
  (frontend `THEME_IDS`, backend `valid_themes`); the mismatch shipped
  silently until the default-save bug surfaced.

## Open items (owner's call)

- Four S002-era **published** commit messages still carry the retired borrowed
  name. Scrubbing them requires rewriting published history plus a force-push;
  deliberately left as-is until the owner decides.
- Broader docs sweep of generic "intelligence harness" concept language was
  scoped out (generic vocabulary, not borrowed identity).
