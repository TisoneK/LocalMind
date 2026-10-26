/**
 * useTheme — the runtime theme switcher (multi-palette).
 *
 * Six palettes shipped in globals.css, selected by `data-theme`
 * (graphite | iris | warm) and `data-mode` (light | dark) on <html>. This
 * hook is the single source of truth for the user's choice: it persists to
 * localStorage, applies the attributes to <html>, and — for mode 'system' —
 * tracks the OS preference live. A tiny inline script in index.html applies
 * the stored choice before first paint (no flash); this module re-applies on
 * load and shares state across components via useSyncExternalStore.
 *
 * Adds:
 *   - `custom`: a user-defined palette {name, accent, background, surface,
 *     text} applied as inline CSS custom properties on <html> when
 *     theme === 'custom' (derived tokens via color-mix in globals.css).
 *   - `tone`: UI brightness multiplier (0.5–1.5, default 1) applied as
 *     `--ui-tone` on <html>, consumed by `body { filter: brightness(...) }`.
 * Both are persisted to localStorage AND to the backend settings.json via
 * POST /api/settings/appearance so the choice survives restarts.
 */

import { useSyncExternalStore } from 'react';

export type ThemeName = 'harness' | 'graphite' | 'iris' | 'warm' | 'custom';
export type ModePref = 'light' | 'dark' | 'system';

export interface CustomTheme {
  name: string;
  accent: string;
  background: string;
  surface: string;
  text: string;
}

export interface ThemeState {
  theme: ThemeName;
  mode: ModePref;
  /** User-defined palette (only meaningful when theme === 'custom'). */
  custom: CustomTheme | null;
  /** UI brightness multiplier 0.5–1.5 (1 = unchanged). */
  tone: number;
}

export const THEMES: { id: ThemeName; label: string; blurb: string; swatch: string }[] = [
  { id: 'harness', label: 'Harness', blurb: 'DeepSeek Harness — graphite, hairline borders, one blue accent', swatch: '#5686fe' },
  { id: 'graphite', label: 'Graphite', blurb: 'Neutral slate, emerald accent', swatch: '#34d399' },
  { id: 'iris', label: 'Midnight Iris', blurb: 'Deep ink, indigo and teal', swatch: '#818cf8' },
  { id: 'warm', label: 'Warm Ink', blurb: 'Warm charcoal, gold and sage', swatch: '#f0b429' },
  { id: 'custom', label: 'Custom', blurb: 'Your own palette, defined in Settings', swatch: 'linear-gradient(45deg,#34d399,#818cf8,#f0b429)' },
];

const STORAGE_KEY = 'localmind-theme';
const THEME_IDS: ThemeName[] = ['harness', 'graphite', 'iris', 'warm', 'custom'];
const MODE_IDS: ModePref[] = ['light', 'dark', 'system'];

const hasWindow = typeof window !== 'undefined';

function darkMedia(): MediaQueryList | null {
  if (!hasWindow || typeof window.matchMedia !== 'function') return null;
  return window.matchMedia('(prefers-color-scheme: dark)');
}

function parseCustom(raw: unknown): CustomTheme | null {
  if (!raw || typeof raw !== 'object') return null;
  const c = raw as Record<string, unknown>;
  if (typeof c.accent !== 'string' || typeof c.background !== 'string' || typeof c.surface !== 'string' || typeof c.text !== 'string') {
    return null;
  }
  return {
    name: typeof c.name === 'string' && c.name.trim() ? c.name : 'Custom',
    accent: c.accent,
    background: c.background,
    surface: c.surface,
    text: c.text,
  };
}

function load(): ThemeState {
  const fallback: ThemeState = { theme: 'harness', mode: 'dark', custom: null, tone: 1 };
  if (!hasWindow) return fallback;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as Partial<ThemeState>;
    return {
      theme: THEME_IDS.includes(parsed.theme as ThemeName) ? (parsed.theme as ThemeName) : 'harness',
      mode: MODE_IDS.includes(parsed.mode as ModePref) ? (parsed.mode as ModePref) : 'dark',
      custom: parseCustom(parsed.custom),
      tone: typeof parsed.tone === 'number' && parsed.tone >= 0.5 && parsed.tone <= 1.5 ? parsed.tone : 1,
    };
  } catch {
    return fallback;
  }
}

export function resolveMode(mode: ModePref): 'light' | 'dark' {
  if (mode !== 'system') return mode;
  return darkMedia()?.matches ? 'dark' : 'light';
}

let state: ThemeState = load();
const listeners = new Set<() => void>();

/** Apply the custom palette as inline CSS custom properties on <html>.
 *  globals.css derives the remaining surface/line/secondary tokens from these
 *  anchors via color-mix under [data-theme="custom"]. */
function applyCustom(custom: CustomTheme | null) {
  if (!hasWindow) return;
  const el = document.documentElement;
  if (!custom) {
    el.style.removeProperty('--acc');
    el.style.removeProperty('--s-base');
    el.style.removeProperty('--s-1');
    el.style.removeProperty('--s-2');
    el.style.removeProperty('--t-primary');
    return;
  }
  el.style.setProperty('--acc', custom.accent);
  el.style.setProperty('--s-base', custom.background);
  // surface + one step up pair well with the graphitedark base ramp; the CSS
  // gradient derives --s-0/--s-3/--line/--t-secondary etc. from these.
  el.style.setProperty('--s-1', custom.surface);
  el.style.setProperty('--s-2', custom.surface);
  el.style.setProperty('--t-primary', custom.text);
}

function apply(s: ThemeState) {
  if (!hasWindow) return;
  const el = document.documentElement;
  el.setAttribute('data-theme', s.theme);
  el.setAttribute('data-mode', resolveMode(s.mode));
  applyCustom(s.theme === 'custom' ? s.custom : null);
  // Tone: 0.5–1.5 brightness filter on body (consumed in globals.css).
  el.style.setProperty('--ui-tone', String(s.tone));
}

function emit() {
  for (const l of listeners) l();
}

function setState(next: Partial<ThemeState>) {
  state = { ...state, ...next };
  if (hasWindow) {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch {
      // localStorage may be unavailable (private mode, sandbox) — still apply.
    }
  }
  apply(state);
  emit();
}

// Apply once on module load, and keep 'system' mode live with the OS.
if (hasWindow) {
  apply(state);
  darkMedia()?.addEventListener('change', () => {
    if (state.mode === 'system') {
      apply(state);
      emit();
    }
  });
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

/** Imperative restore for non-component callers (client.ts startup sync). */
export function restoreAppearance(appearance: {
  theme?: string;
  mode?: string;
  custom_theme?: { name?: string; accent?: string; background?: string; surface?: string; text?: string } | null;
  tone?: number;
}) {
  const next: Partial<ThemeState> = {};
  if (appearance.theme && THEME_IDS.includes(appearance.theme as ThemeName)) next.theme = appearance.theme as ThemeName;
  if (appearance.mode && MODE_IDS.includes(appearance.mode as ModePref)) next.mode = appearance.mode as ModePref;
  if (appearance.custom_theme) next.custom = parseCustom(appearance.custom_theme);
  if (typeof appearance.tone === 'number') next.tone = Math.min(1.5, Math.max(0.5, appearance.tone));
  if (Object.keys(next).length) setState(next);
}

export function useTheme() {
  const snapshot = useSyncExternalStore(
    subscribe,
    () => state,
    () => state,
  );
  return {
    theme: snapshot.theme,
    mode: snapshot.mode,
    resolvedMode: resolveMode(snapshot.mode),
    custom: snapshot.custom,
    tone: snapshot.tone,
    setTheme: (theme: ThemeName) => setState({ theme }),
    setMode: (mode: ModePref) => setState({ mode }),
    setCustomTheme: (custom: CustomTheme) => setState({ theme: 'custom', custom }),
    clearCustomTheme: () => setState({ theme: 'harness', custom: null }),
    setTone: (tone: number) => setState({ tone: Math.min(1.5, Math.max(0.5, tone)) }),
  };
}