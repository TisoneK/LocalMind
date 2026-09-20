/**
 * Tests for TerminalPanel realtime cues.
 *
 * The terminal must feel live without animating high-volume output: a
 * blinking "executing…" cursor shows while a command runs, and the prompt
 * shows a ready cursor when idle and empty.
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
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

describe('TerminalPanel command blocks', () => {
  it('shows a real recorded duration in the command header, formatted', () => {
    render(
      <TerminalPanel
        lines={[
          line({ id: 'c1', type: 'command', content: 'rm -f desktop.ini', duration: 370, exitCode: 0 }),
          line({ id: 'c2', type: 'command', content: 'pytest', duration: 7300, exitCode: 0 }),
        ]}
        onExecute={noop}
      />,
    );
    // Sub-second durations render as ms; multi-second as one-decimal seconds.
    expect(screen.getByText('370ms')).toBeInTheDocument();
    expect(screen.getByText('7.3s')).toBeInTheDocument();
  });

  it('does not invent a duration when none was recorded', () => {
    render(
      <TerminalPanel lines={[line({ id: 'c1', type: 'command', content: 'ls' })]} onExecute={noop} />,
    );
    // No duration, no error, not running → no meta readout at all (honest).
    expect(screen.queryByText(/\d+ms/)).not.toBeInTheDocument();
    expect(screen.queryByText('error')).not.toBeInTheDocument();
    expect(screen.getByText(/^ls$/)).toBeInTheDocument();
  });

  it('renders loose output that precedes any command', () => {
    render(
      <TerminalPanel
        lines={[line({ id: 'o0', type: 'output', content: 'boot log line' })]}
        onExecute={noop}
      />,
    );
    expect(screen.getByText('boot log line')).toBeInTheDocument();
  });
});

describe('TerminalPanel command grouping', () => {
  it('collapses a command\'s output when its toggle is clicked', () => {
    render(
      <TerminalPanel
        lines={[
          line({ id: 'c1', type: 'command', content: 'ls' }),
          line({ id: 'o1', type: 'output', content: 'file-a.txt' }),
          line({ id: 'o2', type: 'output', content: 'file-b.txt' }),
        ]}
        onExecute={noop}
      />,
    );
    // Output is visible by default (expanded), with a collapse toggle showing
    // the child count (2).
    expect(screen.getByText('file-a.txt')).toBeInTheDocument();
    const toggle = screen.getByTitle('Collapse output');
    expect(toggle).toHaveTextContent('2');
    // Collapse → the two output lines are hidden; the command stays.
    fireEvent.click(toggle);
    expect(screen.queryByText('file-a.txt')).not.toBeInTheDocument();
    expect(screen.queryByText('file-b.txt')).not.toBeInTheDocument();
    expect(screen.getByText(/^ls$/)).toBeInTheDocument();
    // Re-expand.
    fireEvent.click(screen.getByTitle('Expand output'));
    expect(screen.getByText('file-a.txt')).toBeInTheDocument();
  });
});

describe('TerminalPanel input', () => {
  it('is focused as soon as it opens', () => {
    render(<TerminalPanel lines={[]} onExecute={noop} />);
    expect(screen.getByPlaceholderText(/enter command/i)).toHaveFocus();
  });

  it('runs what you typed on ONE Enter even while suggestions are showing', async () => {
    const onExecute = vi.fn().mockResolvedValue(undefined);
    const onTabComplete = vi.fn().mockResolvedValue([{ text: 'dir /b', type: 'history' }]);
    render(<TerminalPanel lines={[]} onExecute={onExecute} onTabComplete={onTabComplete} />);
    const box = screen.getByPlaceholderText(/enter command/i);
    fireEvent.change(box, { target: { value: 'dir' } });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 250)); // let the suggestions arrive
    });
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(onExecute).toHaveBeenCalledWith('dir');
  });

  it('takes the highlighted suggestion only after you arrowed to it', async () => {
    const onExecute = vi.fn().mockResolvedValue(undefined);
    const onTabComplete = vi.fn().mockResolvedValue([{ text: 'dir /b', type: 'history' }]);
    render(<TerminalPanel lines={[]} onExecute={onExecute} onTabComplete={onTabComplete} />);
    const box = screen.getByPlaceholderText(/enter command/i) as HTMLInputElement;
    fireEvent.change(box, { target: { value: 'dir' } });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 250));
    });
    fireEvent.keyDown(box, { key: 'ArrowDown' });
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(onExecute).not.toHaveBeenCalled();
    expect(box.value).toBe('dir /b');
  });

  it('takes focus back when a command finishes', () => {
    const { rerender } = render(<TerminalPanel lines={[]} onExecute={noop} isRunning />);
    rerender(<TerminalPanel lines={[]} onExecute={noop} isRunning={false} />);
    expect(screen.getByPlaceholderText(/enter command/i)).toHaveFocus();
  });
});
