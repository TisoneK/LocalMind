import { describe, expect, it } from 'vitest';
import { cn } from './utils';

describe('cn (class merge helper)', () => {
  it('joins multiple class strings', () => {
    expect(cn('px-2', 'py-1', 'text-sm')).toBe('px-2 py-1 text-sm');
  });

  it('resolves conflicting Tailwind classes with later ones winning', () => {
    expect(cn('px-2', 'px-4')).toBe('px-4');
    expect(cn('bg-red-500', 'bg-blue-500')).toBe('bg-blue-500');
    expect(cn('px-2 py-1', 'px-4')).toBe('py-1 px-4');
  });

  it('filters falsy values', () => {
    expect(cn('px-2', false, undefined, null, 'py-1')).toBe('px-2 py-1');
    expect(cn(false, null, undefined, 0, '')).toBe('');
  });

  it('handles clsx-style conditional object and array inputs', () => {
    const isActive = true;
    const isDisabled = false;
    expect(cn('base', { 'is-active': isActive, 'is-disabled': isDisabled })).toBe(
      'base is-active',
    );
    expect(cn('base', ['px-2', 'py-1'])).toBe('base px-2 py-1');
  });

  it('returns an empty string for no inputs', () => {
    expect(cn()).toBe('');
  });

  it('deduplicates identical classes', () => {
    expect(cn('px-2', 'px-2')).toBe('px-2');
  });
});
