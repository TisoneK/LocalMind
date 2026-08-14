/**
 * Tests for useTheme (Session 218 — theming-multi-palette).
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useTheme, resolveMode } from './useTheme';

describe('useTheme', () => {
  beforeEach(() => {
    localStorage.clear();
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
    expect(stored).toEqual({ theme: 'iris', mode: 'light' });
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
});
