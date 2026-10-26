/**
 * Tests for useTheme.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { restoreAppearance, useTheme, resolveMode, THEMES } from './useTheme';

describe('useTheme', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('ships the Harness palette first — the DeepSeek Harness skin is the default', () => {
    expect(THEMES[0].id).toBe('harness');
  });

  it('applies the Harness theme', () => {
    const { result } = renderHook(() => useTheme());
    act(() => result.current.setTheme('harness'));
    expect(document.documentElement.getAttribute('data-theme')).toBe('harness');
  });

  it('resolveMode passes explicit modes through unchanged', () => {
    expect(resolveMode('dark')).toBe('dark');
    expect(resolveMode('light')).toBe('light');
  });

  it('resolveMode maps system to a concrete light/dark', () => {
    expect(['light', 'dark']).toContain(resolveMode('system'));
  });

  it('applies the chosen theme and mode to <html> and persists them', () => {
    const { result } = renderHook(() => useTheme());
    act(() => result.current.setTheme('iris'));
    act(() => result.current.setMode('light'));

    expect(document.documentElement.getAttribute('data-theme')).toBe('iris');
    expect(document.documentElement.getAttribute('data-mode')).toBe('light');

    const stored = JSON.parse(localStorage.getItem('localmind-theme') as string);
    expect(stored).toEqual({ theme: 'iris', mode: 'light', custom: null, tone: 1 });
  });

  it('system mode still resolves data-mode to a concrete value on <html>', () => {
    const { result } = renderHook(() => useTheme());
    act(() => result.current.setMode('system'));

    expect(result.current.mode).toBe('system');
    expect(['light', 'dark']).toContain(document.documentElement.getAttribute('data-mode'));
  });

  it('exposes the resolved mode for a concrete choice', () => {
    const { result } = renderHook(() => useTheme());
    act(() => {
      result.current.setTheme('warm');
      result.current.setMode('dark');
    });
    expect(result.current.theme).toBe('warm');
    expect(result.current.resolvedMode).toBe('dark');
  });

  // ── custom palette + tone ──

  it('applies a custom palette inline and persists it (fresh module reload)', () => {
    const custom = { name: 'Ocean', accent: '#3b82f6', background: '#0b1220', surface: '#16202f', text: '#e2e8f0' };
    const { result } = renderHook(() => useTheme());
    act(() => result.current.setCustomTheme(custom));

    expect(result.current.theme).toBe('custom');
    expect(result.current.custom).toEqual(custom);

    const el = document.documentElement;
    expect(el.getAttribute('data-theme')).toBe('custom');
    expect(el.style.getPropertyValue('--acc')).toBe('#3b82f6');
    expect(el.style.getPropertyValue('--s-base')).toBe('#0b1220');
    expect(el.style.getPropertyValue('--t-primary')).toBe('#e2e8f0');

    const stored = JSON.parse(localStorage.getItem('localmind-theme') as string);
    expect(stored.custom).toEqual(custom);
  });

  it('clearing the custom theme removes the inline palette and returns to Harness', () => {
    const { result } = renderHook(() => useTheme());
    act(() => {
      result.current.setCustomTheme({ name: 'X', accent: '#f00', background: '#000', surface: '#111', text: '#fff' });
      result.current.clearCustomTheme();
    });
    expect(result.current.theme).toBe('harness');
    expect(document.documentElement.style.getPropertyValue('--acc')).toBe('');
  });

  it('clamps tone into the 0.5–1.5 range and applies --ui-tone', () => {
    const { result } = renderHook(() => useTheme());
    act(() => result.current.setTone(3));
    expect(result.current.tone).toBe(1.5);
    act(() => result.current.setTone(0.85));
    expect(result.current.tone).toBe(0.85);
    expect(document.documentElement.style.getPropertyValue('--ui-tone')).toBe('0.85');
  });

  it('restoreAppearance applies persisted backend values', () => {
    act(() => restoreAppearance({
      theme: 'warm',
      mode: 'light',
      custom_theme: { name: 'Sunset', accent: '#f97316', background: '#1c1917', surface: '#292524', text: '#fafaf9' },
      tone: 1.1,
    }));
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe('warm');
    expect(result.current.mode).toBe('light');
    expect(result.current.tone).toBe(1.1);
  });
});
