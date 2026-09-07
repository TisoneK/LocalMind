import { describe, expect, it } from 'vitest';
import { stripMarkdownToPreview } from './previewText';

describe('stripMarkdownToPreview', () => {
  it('strips bold markers (the sidebar showed raw ** pairs)', () => {
    expect(stripMarkdownToPreview('🌤️ **15°C (59°F)** right now')).toBe(
      '🌤️ 15°C (59°F) right now',
    );
  });

  it('strips table pipes including |---| separators', () => {
    const md = 'Forecast:\n| time | temp |\n|---|---|\n| 5 AM | 15°C |';
    expect(stripMarkdownToPreview(md)).toBe('Forecast: time temp 5 AM 15°C');
  });

  it('keeps link label text and drops the URL', () => {
    expect(stripMarkdownToPreview('see [the docs](https://example.com)')).toBe(
      'see the docs',
    );
  });

  it('drops fenced code blocks and inline-code backticks', () => {
    expect(stripMarkdownToPreview('run:\n```bash\nls -la\n```\nthanks')).toBe(
      'run: thanks',
    );
    expect(stripMarkdownToPreview('use `npm test` now')).toBe('use npm test now');
  });

  it('strips headers, quotes, bullets, and emphasis', () => {
    const md = '## Summary\n> quoted\n- item **one**\n- item _two_';
    expect(stripMarkdownToPreview(md)).toBe('Summary quoted item one item two');
  });

  it('collapses newlines and whitespace into a single line', () => {
    expect(stripMarkdownToPreview('line one\n\nline two   three')).toBe(
      'line one line two three',
    );
  });

  it('returns empty string for empty input', () => {
    expect(stripMarkdownToPreview('')).toBe('');
  });

  it('leaves plain text untouched', () => {
    expect(stripMarkdownToPreview('just a normal preview sentence.')).toBe(
      'just a normal preview sentence.',
    );
  });
});
