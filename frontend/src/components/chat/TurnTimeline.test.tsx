import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { TurnTimeline } from './TurnTimeline';
import type { ToolCall } from '@/types';

function tool(id: string, name: string, duration: number, status: ToolCall['status'] = 'done'): ToolCall {
  return { id, name, label: name, status, input: '', duration };
}

describe('TurnTimeline', () => {
  it('renders segments for thinking + each tool with proportional widths', () => {
    render(
      <TurnTimeline
        thinkMs={5000}
        toolCalls={[tool('t1', 'web_search', 12000), tool('t2', 'web_fetch', 3000)]}
      />,
    );
    const bar = screen.getByTestId('turn-timeline');
    expect(bar).toBeInTheDocument();
    // total = 20s → header shows the composed total
    expect(screen.getByText('20s')).toBeInTheDocument();
    // legend entries carry the per-segment durations
    expect(screen.getByText('Thinking')).toBeInTheDocument();
    expect(screen.getByText('web_search')).toBeInTheDocument();
    // thinking segment width ≈ 25% (5s / 20s); assert it's present with a title
    const thinking = bar.querySelector('[title^="Thinking"]') as HTMLElement;
    expect(thinking).toBeTruthy();
    expect(thinking.getAttribute('title')).toContain('5.0s');
    expect(thinking.style.width).toBe('25%');
  });

  it('does not double-count: segment widths reflect the fix (thinking excludes tool time)', () => {
    // thinking 5s + tools 15s = 20s total; the 12s tool is 60%, not diluted by
    // a thinking timer that (pre-fix) would have spanned the tools.
    render(<TurnTimeline thinkMs={5000} toolCalls={[tool('t1', 'web_search', 12000), tool('t2', 'web_fetch', 3000)]} />);
    const bar = screen.getByTestId('turn-timeline');
    const search = bar.querySelector('[title^="web_search"]') as HTMLElement;
    expect(search.style.width).toBe('60%');
  });

  it('marks a failed tool with the error color', () => {
    render(<TurnTimeline thinkMs={2000} toolCalls={[tool('t1', 'shell', 4000, 'failed')]} />);
    const bar = screen.getByTestId('turn-timeline');
    expect(bar.querySelector('[title^="shell"]')?.className).toContain('bg-brand-red');
  });

  it('renders nothing for a trivial (single-segment) turn', () => {
    // thinking only, no tools → one block, not worth a bar
    const { container } = render(<TurnTimeline thinkMs={3000} toolCalls={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders nothing when no durations are measured', () => {
    const { container } = render(
      <TurnTimeline toolCalls={[{ id: 't1', name: 'web_search', status: 'running', input: '' }]} />,
    );
    expect(container.firstChild).toBeNull();
  });
});
