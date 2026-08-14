/**
 * useTheme — the runtime theme switcher (Session 218, theming-multi-palette).
 *
 * S217 shipped six palettes in globals.css, selected by `data-theme`
 * (graphite | iris | warm) and `data-mode` (light | dark) on <html>. This
 * hook is the single source of truth for the user's choice: it persists to
 * localStorage, applies the attributes to <html>, and — for mode 'system' —
 * tracks the OS preference live. A tiny inline script in index.html applies
 * the stored choice before first paint (no flash); this module re-applies on
 * load and shares state across components via useSyncExternalStore.
 */

import { useSyncExternalStore } from 'react';

export type ThemeName = 'graphite' | 'iris' | 'warm';
export type ModePref = 'light' | 'dark' | 'system';

export interface ThemeState {
  theme: ThemeName;
  mode: ModePref;
}

export const THEMES: { id: ThemeName; label: string; blurb: string; swatch: string }[] = [
  { id: 'graphite', label: 'Graphite', blurb: 'Neutral slate, emerald accent', swatch: '#34d399' },
  { id: 'iris', label: 'Midnight Iris', blurb: 'Deep ink, indigo and teal', swatch: '#818cf8' },
  { id: 'warm', label: 'Warm Ink', blurb: 'Warm charcoal, gold and sage', swatch: '#f0b429' },
];

const STORAGE_KEY = 'localmind-theme';
const THEME_IDS: ThemeName[] = ['graphite', 'iris', 'warm'];
const MODE_IDS: ModePref[] = ['light', 'dark', 'system'];

const hasWindow = typeof window !== 'undefined';

function darkMedia(): MediaQueryList | null {
  if (!hasWindow || typeof window.matchMedia !== 'function') return null;
  return window.matchMedia('(prefers-color-scheme: dark)');
}

function load(): ThemeState {
  const fallback: ThemeState = { theme: 'graphite', mode: 'dark' };
  if (!hasWindow) return fallback;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as Partial<ThemeState>;
    return {
      theme: THEME_IDS.includes(parsed.theme as ThemeName) ? (parsed.theme as ThemeName) : 'graphite',
      mode: MODE_IDS.includes(parsed.mode as ModePref) ? (parsed.mode as ModePref) : 'dark',
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

function apply(s: ThemeState) {
  if (!hasWindow) return;
  const el = document.documentElement;
  el.setAttribute('data-theme', s.theme);
  el.setAttribute('data-mode', resolveMode(s.mode));
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
    setTheme: (theme: ThemeName) => setState({ theme }),
    setMode: (mode: ModePref) => setState({ mode }),
  };
}
