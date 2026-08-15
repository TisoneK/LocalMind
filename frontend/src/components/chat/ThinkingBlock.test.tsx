/**
 * Tests for ThinkingBlock (Session 211 — realtime-alive-ui).
 *
 * The block renders the model's reasoning; while streaming it stays open
 * with a live indicator, and once finished it shows a duration and the
 * "Thought process" label. Structured "[Label] detail" step lines render
 * the label as a chip.
 */

import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ThinkingBlock } from './ThinkingBlock';

describe('ThinkingBlock', () => {
  it('renders the reasoning content while streaming', () => {
    render(<ThinkingBlock thinking="Weighing two approaches" isStreaming />);
    expect(screen.getByText(/Weighing two approaches/)).toBeInTheDocument();
  });

  it('shows the "Thinking" label while streaming', () => {
    render(<ThinkingBlock thinking="reasoning…" isStreaming />);
    expect(screen.getByText('Thinking')).toBeInTheDocument();
  });

  it('shows the "Thought process" label and duration once finished', () => {
    render(<ThinkingBlock thinking="Considered the trade-offs" thinkMs={2400} isStreaming={false} />);
    expect(screen.getByText('Thought process')).toBeInTheDocument();
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
    // only the "Thought process" header shows — not a persistent scrollback.
    render(<ThinkingBlock thinking="hidden reasoning" isStreaming={false} />);
    expect(screen.getByText('Thought process')).toBeInTheDocument();
    expect(screen.queryByText(/hidden reasoning/)).not.toBeInTheDocument();
  });

  it('expands a collapsed block on click for review (ADR-36)', () => {
    render(<ThinkingBlock thinking="expandable reasoning" isStreaming={false} />);
    expect(screen.queryByText(/expandable reasoning/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByText('Thought process'));
    expect(screen.getByText(/expandable reasoning/)).toBeInTheDocument();
  });
});
