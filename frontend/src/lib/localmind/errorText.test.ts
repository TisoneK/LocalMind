import { describe, expect, it } from 'vitest';
import { stripFallbackErrorText } from './errorText';

describe('stripFallbackErrorText', () => {
  it('removes the loop fallback when it is the whole reply', () => {
    expect(stripFallbackErrorText('⚠️ The model ran into an issue. Please try again, or switch to a larger model for this task.')).toBe('');
  });

  it('removes the rate-limit fallback', () => {
    expect(stripFallbackErrorText('The model provider rate-limited my request. Please try again in a moment.')).toBe('');
  });

  it('keeps a real partial answer that came before the failure', () => {
    const text = 'Here is what I found so far: the file has 3 rows.\n\n⚠️ The model ran into an issue. Please try again, or switch to a larger model for this task.';
    expect(stripFallbackErrorText(text)).toBe('Here is what I found so far: the file has 3 rows.');
  });

  it('leaves ordinary text alone', () => {
    expect(stripFallbackErrorText('All done.')).toBe('All done.');
  });
});
