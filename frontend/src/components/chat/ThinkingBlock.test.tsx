/**
 * Tests for ThinkingBlock (Session 211 — realtime-alive-ui).
 *
 * The block renders the model's reasoning; while streaming it stays open
 * with a live indicator, and once finished it shows a duration and the
 * "Approach" label (Session 332-E — was "Thought process", exposing
 * internal reasoning). Structured "[Label] detail" step lines render
 * the label as a chip.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ThinkingBlock } from './ThinkingBlock';

const writeText = vi.fn();
beforeEach(() => {
  writeText.mockClear();
  Object.assign(navigator, {
    clipboard: { writeText: (...args: unknown[]) => { writeText(...args); return Promise.resolve(); } },
  });
});

describe('ThinkingBlock', () => {
  it('renders the reasoning content while streaming', () => {
    render(<ThinkingBlock thinking="Weighing two approaches" isStreaming />);
    expect(screen.getByText(/Weighing two approaches/)).toBeInTheDocument();
  });

  it('shows the "Working" label while streaming', () => {
    render(<ThinkingBlock thinking="reasoning…" isStreaming />);
    expect(screen.getByText('Working')).toBeInTheDocument();
  });

  it('shows the "Approach" label and duration once finished', () => {
    render(<ThinkingBlock thinking="Considered the trade-offs" thinkMs={2400} isStreaming={false} />);
    expect(screen.getByText('Approach')).toBeInTheDocument();
    expect(screen.getByText('2.4s')).toBeInTheDocument();
  });

  it('renders a structured step label as a chip', () => {
    render(<ThinkingBlock thinking="[Web Search] Search: nairobi weather" isStreaming />);
    expect(screen.getByText('Web Search')).toBeInTheDocument();
    expect(screen.getByText(/Search: nairobi weather/)).toBeInTheDocument();
  });

  it('accepts a ThinkingStep object as well as a string', () => {
    render(<ThinkingBlock thinking={{ id: 't1', content: 'From an object', collapsed: false }} isStreaming />);
    expect(screen.getByText(/From an object/)).toBeInTheDocument();
  });

  it('collapses the reasoning by default once the turn is done (ADR-36)', () => {
    // Collapse-after-done: when not streaming, the block starts collapsed so
    // only the "Approach" header shows — not a persistent scrollback.
    render(<ThinkingBlock thinking="hidden reasoning" isStreaming={false} />);
    expect(screen.getByText('Approach')).toBeInTheDocument();
    expect(screen.queryByText(/hidden reasoning/)).not.toBeInTheDocument();
  });

  it('expands a collapsed block on click for review (ADR-36)', () => {
    render(<ThinkingBlock thinking="expandable reasoning" isStreaming={false} />);
    expect(screen.queryByText(/expandable reasoning/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByText('Approach'));
    expect(screen.getByText(/expandable reasoning/)).toBeInTheDocument();
  });

  it('bounds the reasoning height with a scrollable container (Session 265)', () => {
    render(<ThinkingBlock thinking="long reasoning" isStreaming />);
    const scroller = screen.getByTestId('thinking-scroll');
    expect(scroller.className).toContain('max-h-64');
    expect(scroller.className).toContain('overflow-y-auto');
    expect(scroller.className).toContain('custom-scrollbar');
  });

  it('copies the full reasoning via the bottom copy button (Session 265)', () => {
    render(<ThinkingBlock thinking="copyable reasoning" isStreaming />);
    fireEvent.click(screen.getByTitle('Copy reasoning'));
    expect(writeText).toHaveBeenCalledWith('copyable reasoning');
  });

  it('auto-scrolls new reasoning content into view (Session 265)', () => {
    // jsdom has no layout, so scrollHeight is 0 by default; fake it to assert
    // the effect pins scrollTop to the container bottom on content growth.
    const { rerender } = render(<ThinkingBlock thinking="first chunk" isStreaming />);
    const scroller = screen.getByTestId('thinking-scroll');
    Object.defineProperty(scroller, 'scrollHeight', { value: 500, configurable: true });

    rerender(<ThinkingBlock thinking="first chunk second chunk" isStreaming />);
    expect(scroller.scrollTop).toBe(500);
  });
});
