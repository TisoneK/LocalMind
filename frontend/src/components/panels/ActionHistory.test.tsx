/**
 * Tests for ActionHistory.
 *
 * The left-panel action trace groups a turn's steps into a numbered,
 * connected chain under the plan step they serve, and emphasises the
 * step currently running so the trace feels alive.
 */

import { describe, it, expect, vi, beforeAll } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ActionHistory } from './ActionHistory';
import type { ActionItem } from '../../types';

// jsdom provides no navigator.clipboard — stub it so the copy buttons work.
const writeText = vi.fn();
beforeAll(() => {
  Object.assign(navigator, {
    clipboard: { writeText: (...args: unknown[]) => { writeText(...args); return Promise.resolve(); } },
  });
});

const action = (overrides: Partial<ActionItem> = {}): ActionItem => ({
  id: 'a0',
  type: 'shell',
  label: 'Run command',
  detail: '',
  status: 'done',
  timestamp: '09:00',
  iteration: 1,
  ...overrides,
});

describe('ActionHistory', () => {
  it('shows an empty state with no actions', () => {
    render(<ActionHistory actions={[]} />);
    expect(screen.getByText('No actions yet.')).toBeInTheDocument();
  });

  it('renders action labels', () => {
    render(
      <ActionHistory
        actions={[
          action({ id: 'a1', label: 'Read config', type: 'file_read', iteration: 1 }),
          action({ id: 'a2', label: 'Run tests', type: 'shell', iteration: 2 }),
        ]}
      />,
    );
    expect(screen.getByText('Read config')).toBeInTheDocument();
    expect(screen.getByText('Run tests')).toBeInTheDocument();
  });

  it('renders the winning search engine as a badge', () => {
    render(
      <ActionHistory
        actions={[
          action({ id: 'a1', label: 'Searching the web', type: 'web_search', provider: 'bing', iteration: 1 }),
          action({ id: 'a2', label: 'Run tests', type: 'shell', iteration: 2 }),
        ]}
      />,
    );
    expect(screen.getByText('bing')).toBeInTheDocument();
    expect(screen.getByTitle('Answered by bing')).toBeInTheDocument();
    // Tools without a provider render no badge.
    expect(screen.queryByText('duckduckgo')).not.toBeInTheDocument();
  });

  it('groups actions under their plan step', () => {
    render(
      <ActionHistory
        actions={[
          action({ id: 'a1', label: 'Step A action', todoId: 'plan-0', iteration: 1 }),
        ]}
      />,
    );
    expect(screen.getByText('Step 1')).toBeInTheDocument();
  });

  it('renders a running action (alive emphasis path)', () => {
    render(
      <ActionHistory
        actions={[action({ id: 'a1', label: 'Running now', status: 'running', iteration: 1 })]}
      />,
    );
    // The label still renders; the running branch adds emphasis styling.
    expect(screen.getByText('Running now')).toBeInTheDocument();
  });

  it('reveals copy buttons for input and output (most-recent card auto-expands)', () => {
    render(
      <ActionHistory
        actions={[
          action({ id: 'a1', label: 'Run command', input: 'ls -la', output: 'total 4', iteration: 1 }),
        ]}
      />,
    );
    // The lone/most-recent action is expanded by default — no click needed.
    // The input also appears in the collapsed header preview, so it renders twice.
    expect(screen.getAllByText('ls -la').length).toBeGreaterThan(0);
    expect(screen.getByText('total 4')).toBeInTheDocument();
    // A shell action renders one console block (command + output) with a single
    // combined copy button (the terminal treatment).
    expect(screen.getAllByTitle('Copy')).toHaveLength(1);
  });

  it('copies the section text when a copy button is clicked', () => {
    writeText.mockClear();
    render(
      <ActionHistory
        actions={[action({ id: 'a1', label: 'Run command', input: 'ls -la', iteration: 1 })]}
      />,
    );
    // Auto-expanded (most recent) — click the copy button directly.
    fireEvent.click(screen.getAllByTitle('Copy')[0]);
    expect(writeText).toHaveBeenCalledWith('ls -la');
  });

  it('pretty-prints and colour-codes JSON input', () => {
    render(
      <ActionHistory
        actions={[
          action({
            id: 'a1',
            label: 'Write config',
            type: 'file_write',
            input: '{"name":"x","count":2}',
            iteration: 1,
          }),
        ]}
      />,
    );
    // Auto-expanded (most recent) — the JSON body renders without a click.
    // JSON keys are rendered as blue spans (the key token includes the colon).
    const key = screen.getByText('"name":');
    expect(key.className).toContain('text-brand-blue');
    // The numeric value is colour-coded purple.
    const num = screen.getByText('2');
    expect(num.className).toContain('text-brand-purple');
  });

  it('shows the Why block when reasoning has real content', () => {
    render(
      <ActionHistory
        actions={[action({ id: 'a1', label: 'Run command', reasoning: 'Plan step: list files', iteration: 1 })]}
      />,
    );
    // Auto-expanded (most recent) — the Why block renders without a click.
    expect(screen.getByText('Why')).toBeInTheDocument();
    expect(screen.getByText('Plan step: list files')).toBeInTheDocument();
  });

  it('hides the Why block when reasoning is empty or whitespace-only', () => {
    render(
      <ActionHistory
        actions={[
          action({ id: 'a1', label: 'Empty reason', reasoning: '   ', iteration: 1 }),
          action({ id: 'a2', label: 'Null reason', reasoning: null, iteration: 2 }),
        ]}
      />,
    );
    // The collapsed cards must not show a blank "why:" peek.
    expect(screen.queryByText(/why:/)).not.toBeInTheDocument();
    // Expanding a whitespace-reasoning card must not reveal an empty Why block.
    fireEvent.click(screen.getByText('Empty reason'));
    expect(screen.queryByText('Why')).not.toBeInTheDocument();
  });

  it('auto-expands the most-recent action and collapses older ones', () => {
    render(
      <ActionHistory
        actions={[
          action({ id: 'a1', label: 'Old step', input: 'old-in', output: 'old-output', iteration: 1 }),
          action({ id: 'a2', label: 'Newest step', input: 'new-in', output: 'new-output', iteration: 2 }),
        ]}
      />,
    );
    // The newest action (a2) is expanded → its output is visible.
    expect(screen.getByText('new-output')).toBeInTheDocument();
    // The older action (a1) is collapsed → its output is hidden.
    expect(screen.queryByText('old-output')).not.toBeInTheDocument();
    // Clicking the older one expands it (manual override).
    fireEvent.click(screen.getByText('Old step'));
    expect(screen.getByText('old-output')).toBeInTheDocument();
  });
});

describe('ActionHistory — redesigned bodies', () => {
  it('renders a shell action as a terminal block with a ❯ command line', () => {
    render(
      <ActionHistory
        actions={[action({ id: 'a1', type: 'shell', label: 'Run tests', input: 'pytest -q', output: '30 passed', iteration: 1 })]}
      />,
    );
    expect(screen.getByText('terminal')).toBeInTheDocument();
    expect(screen.getByText('❯')).toBeInTheDocument();
    expect(screen.getByText('30 passed')).toBeInTheDocument();
  });

  it('renders diff-shaped output with add/remove line washes', () => {
    render(
      <ActionHistory
        actions={[action({ id: 'a1', type: 'file_write', label: 'Edit config', output: 'ctx\n- old line\n+ new line', iteration: 1 })]}
      />,
    );
    expect(screen.getByText('Diff')).toBeInTheDocument();
    expect(screen.getByText('- old line')).toHaveClass('bg-brand-gh-red-bg');
    expect(screen.getByText('+ new line')).toHaveClass('bg-brand-gh-green-bg');
  });
});
