/**
 * Tests for the shared motion primitive.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook } from '@testing-library/react';

const state = vi.hoisted(() => ({ reduced: false }));
vi.mock('framer-motion', () => ({ useReducedMotion: () => state.reduced }));

import { useEnterMotion } from './motion';

beforeEach(() => {
  state.reduced = false;
});

describe('useEnterMotion', () => {
  it('animates in with the requested offset when motion is allowed', () => {
    const { result } = renderHook(() => useEnterMotion());
    const props = result.current.enter({ x: -6, duration: 0.22 });
    expect(result.current.reduce).toBe(false);
    expect(props.initial).toEqual({ opacity: 0, x: -6, y: 0 });
    expect(props.animate).toEqual({ opacity: 1, x: 0, y: 0 });
    expect(props.transition).toEqual({ duration: 0.22, ease: 'easeOut' });
  });

  it('skips the enter transition under reduced motion', () => {
    state.reduced = true;
    const { result } = renderHook(() => useEnterMotion());
    expect(result.current.reduce).toBe(true);
    expect(result.current.enter({ x: -6 }).initial).toBe(false);
  });

  it('defaults offset to 0 and duration to 0.2', () => {
    const { result } = renderHook(() => useEnterMotion());
    const props = result.current.enter();
    expect(props.initial).toEqual({ opacity: 0, x: 0, y: 0 });
    expect(props.transition.duration).toBe(0.2);
  });
});
