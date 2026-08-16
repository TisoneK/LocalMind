/**
 * Tests for ActionHistory (Session 213 — realtime-alive-ui).
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

  it('expands an action to reveal copy buttons for input and output', () => {
    render(
      <ActionHistory
        actions={[
          action({ id: 'a1', label: 'Run command', input: 'ls -la', output: 'total 4', iteration: 1 }),
        ]}
      />,
    );
    fireEvent.click(screen.getByText('Run command'));
    // The input also appears in the collapsed header preview, so it renders twice.
    expect(screen.getAllByText('ls -la').length).toBeGreaterThan(0);
    expect(screen.getByText('total 4')).toBeInTheDocument();
    // One copy button per body section (input + output).
    expect(screen.getAllByTitle('Copy')).toHaveLength(2);
  });

  it('copies the section text when a copy button is clicked', () => {
    writeText.mockClear();
    render(
      <ActionHistory
        actions={[action({ id: 'a1', label: 'Run command', input: 'ls -la', iteration: 1 })]}
      />,
    );
    fireEvent.click(screen.getByText('Run command'));
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
    fireEvent.click(screen.getByText('Write config'));
    // JSON keys are rendered as blue spans (the key token includes the colon).
    const key = screen.getByText('"name":');
    expect(key.className).toContain('text-brand-blue');
    // The numeric value is colour-coded purple.
    const num = screen.getByText('2');
    expect(num.className).toContain('text-brand-purple');
  });
});
