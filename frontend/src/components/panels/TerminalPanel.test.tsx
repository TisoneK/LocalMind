/**
 * Tests for TerminalPanel realtime cues (Session 215 — realtime-alive-ui).
 *
 * The terminal must feel live without animating high-volume output: a
 * blinking "executing…" cursor shows while a command runs, and the prompt
 * shows a ready cursor when idle and empty.
 */

import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { TerminalPanel } from './TerminalPanel';
import type { TerminalLine } from '../../types';

const line = (overrides: Partial<TerminalLine> = {}): TerminalLine => ({
  id: 'l0',
  type: 'output',
  content: 'hello world',
  timestamp: '09:00',
  ...overrides,
});

const noop = async () => undefined;

describe('TerminalPanel realtime cues', () => {
  it('renders output lines', () => {
    render(<TerminalPanel lines={[line({ content: 'build ok' })]} onExecute={noop} />);
    expect(screen.getByText(/build ok/)).toBeInTheDocument();
  });

  it('shows the live "executing…" cursor while a command runs', () => {
    render(<TerminalPanel lines={[line({ type: 'command', content: '$ pytest' })]} onExecute={noop} isRunning />);
    expect(screen.getByTestId('terminal-executing')).toBeInTheDocument();
    expect(screen.getByText('executing…')).toBeInTheDocument();
  });

  it('hides the executing cursor when nothing is running', () => {
    render(<TerminalPanel lines={[line()]} onExecute={noop} isRunning={false} />);
    expect(screen.queryByTestId('terminal-executing')).not.toBeInTheDocument();
  });

  it('offers a Cancel control while running', () => {
    render(<TerminalPanel lines={[]} onExecute={noop} isRunning onAbort={() => {}} />);
    expect(screen.getByTitle(/Cancel/i)).toBeInTheDocument();
  });
});
