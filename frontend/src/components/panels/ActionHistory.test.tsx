/**
 * Tests for ActionHistory (Session 213 — realtime-alive-ui).
 *
 * The left-panel action trace groups a turn's steps into a numbered,
 * connected chain under the plan step they serve, and emphasises the
 * step currently running so the trace feels alive.
 */

import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ActionHistory } from './ActionHistory';
import type { ActionItem } from '../../types';

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
});
