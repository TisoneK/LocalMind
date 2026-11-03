import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import { MarkdownContent } from './MarkdownContent';

/**
 * The owner's 2026-11-03 report: "The UI does not format the output in
 * style eg tables etc its just text." These pins hold the RENDER side of
 * the fix: the shared markdown pipeline turns the model's markdown into
 * real styled elements — a GFM table into a themed <table>, emphasis into
 * <strong>, fences into the code block — for BOTH well-formed GFM and the
 * degraded shapes the free-tier models actually emit (full-width
 * punctuation lookalikes, a missing delimiter row), which repairMarkdown
 * normalizes before render. The wire side (the backend must not mangle
 * the markdown in transit) is pinned live by scripts/live_test_markdown_render.py.
 */

const WELL_FORMED = [
  '## Plan comparison',
  '',
  'Here is the comparison — **Plan A** is cheaper:',
  '',
  '| Plan | Price | Speed |',
  '| --- | --- | --- |',
  '| Plan A | 1,500 | 10 Mbps |',
  '| Plan B | 2,800 | 40 Mbps |',
  '',
  'Run `pip install localmind` to start.',
].join('\n');

const DEGRADED = [
  '## Plan comparison',
  '',
  '| Plan ｜ Price ｜ Speed ｜',
  '｜－－－｜－－－｜－－－｜',
  '｜ Plan A ｜ 1,500 ｜ 10 Mbps ｜',
  '｜ Plan B ｜ 2,800 ｜ 40 Mbps ｜',
  '',
  'And a table with no delimiter row:',
  '',
  '| Plan | Price | Speed |',
  '| Plan A | 1,500 | 10 Mbps |',
  '| Plan B | 2,800 | 40 Mbps |',
].join('\n');

describe('MarkdownContent — well-formed GFM', () => {
  it('renders a GFM table as a themed table with header cells', () => {
    const { container } = render(<MarkdownContent text={WELL_FORMED} />);
    const table = container.querySelector('table');
    expect(table, 'the pipe table must render as a real <table>').not.toBeNull();
    expect(container.querySelectorAll('thead th')).toHaveLength(3);
    expect(container.querySelectorAll('tbody tr')).toHaveLength(2);
    // The themed card wrapper is present (not an unstyled browser default).
    expect(table!.closest('.overflow-x-auto')).not.toBeNull();
  });

  it('parses headings, emphasis, and inline code (no literal markers)', () => {
    const { container } = render(<MarkdownContent text={WELL_FORMED} />);
    // Headings render through the custom map as styled blocks (a <div>,
    // not h2) — the user-visible property is that the `##` marker PARSED
    // (never shown literally) and the text stands alone.
    expect(container.querySelector('h2')).toBeNull();
    expect(container.textContent).toContain('Plan comparison');
    expect(container.textContent).not.toContain('## Plan');
    expect(container.querySelector('strong')?.textContent).toBe('Plan A');
    expect(container.querySelector('code')?.textContent).toContain('pip install');
  });
});

describe('MarkdownContent — degraded GLM shapes still format', () => {
  it('renders a full-width-pipe table as a real table after repair', () => {
    const { container } = render(<MarkdownContent text={DEGRADED} />);
    const tables = container.querySelectorAll('table');
    expect(
      tables.length,
      'both degraded tables (full-width pipes, missing delimiter) must render as <table>'
    ).toBe(2);
    expect(container.querySelectorAll('thead th').length).toBeGreaterThanOrEqual(3);
  });

  it('leaves ｜ inside a fenced code block as code content', () => {
    const text = '```\n｜ a ｜ b ｜\n```';
    const { container } = render(<MarkdownContent text={text} />);
    expect(container.querySelector('table')).toBeNull();
    expect(container.textContent).toContain('｜ a ｜ b ｜');
  });

  it('keeps prose full-width punctuation untouched', () => {
    const { container } = render(<MarkdownContent text={'上海｜北京 note — ok'} />);
    expect(container.querySelector('table')).toBeNull();
    expect(container.textContent).toContain('上海｜北京 note — ok');
  });
});
