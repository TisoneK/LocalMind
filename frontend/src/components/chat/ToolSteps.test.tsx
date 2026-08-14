/**
 * Tests for the ToolSteps Actions timeline (Session 210 — realtime-alive-ui).
 *
 * The full-mode render groups tool calls into a live "Actions" timeline
 * with a natural-language summary header, a connected step list, and a
 * terminal Done/working row. Compact mode stays a flat chip row.
 */

import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { ToolSteps } from './ToolSteps';
import type { ToolCall } from '../../types';

const call = (overrides: Partial<ToolCall> = {}): ToolCall => ({
  id: 't1',
  name: 'shell',
  status: 'done',
  input: '',
  ...overrides,
});

describe('ToolSteps — Actions timeline', () => {
  it('renders nothing when there are no tool calls', () => {
    const { container } = render(<ToolSteps toolCalls={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders the grouped timeline container', () => {
    render(<ToolSteps toolCalls={[call()]} />);
    expect(screen.getByTestId('action-timeline')).toBeInTheDocument();
  });

  it('summarizes completed calls in natural language', () => {
    render(
      <ToolSteps
        toolCalls={[
          call({ id: 'a', name: 'file_write', status: 'done' }),
          call({ id: 'b', name: 'shell', status: 'done' }),
          call({ id: 'c', name: 'shell', status: 'done' }),
        ]}
      />,
    );
    // "Wrote 1 file, Ran 2 commands"
    expect(screen.getByText(/Wrote 1 file/)).toBeInTheDocument();
    expect(screen.getByText(/Ran 2 commands/)).toBeInTheDocument();
  });

  it('shows a Done terminal row when all calls succeed', () => {
    render(<ToolSteps toolCalls={[call({ name: 'file_read', status: 'done' })]} />);
    expect(screen.getByText('Done')).toBeInTheDocument();
  });

  it('shows a "Done with errors" terminal row when a call failed', () => {
    render(
      <ToolSteps
        toolCalls={[
          call({ id: 'a', name: 'file_read', status: 'done' }),
          call({ id: 'b', name: 'code_exec', status: 'failed' }),
        ]}
      />,
    );
    expect(screen.getByText('Done with errors')).toBeInTheDocument();
  });

  it('shows a live "working…" row while a call is running', () => {
    render(
      <ToolSteps
        toolCalls={[
          call({ id: 'a', name: 'file_write', status: 'done' }),
          call({ id: 'b', name: 'shell', status: 'running' }),
        ]}
        isStreaming
      />,
    );
    expect(screen.getByText('working…')).toBeInTheDocument();
    // A still-running run has no Done row yet.
    expect(screen.queryByText('Done')).not.toBeInTheDocument();
  });

  it('renders each tool label in the timeline', () => {
    render(
      <ToolSteps
        toolCalls={[
          call({ id: 'a', name: 'edit_file', label: 'Edit File', status: 'done', input: 'x.py' }),
          call({ id: 'b', name: 'shell', label: 'Run smoke v2', status: 'done' }),
        ]}
      />,
    );
    expect(screen.getByText('Edit File')).toBeInTheDocument();
    expect(screen.getByText('Run smoke v2')).toBeInTheDocument();
  });

  it('compact mode renders a flat chip row, not the timeline', () => {
    render(<ToolSteps compact toolCalls={[call({ name: 'shell', label: 'Run', status: 'done' })]} />);
    expect(screen.queryByTestId('action-timeline')).not.toBeInTheDocument();
    expect(screen.getByText('Run')).toBeInTheDocument();
  });

  it('links a tool to its plan step when todoId is plan-N', () => {
    render(
      <ToolSteps toolCalls={[call({ name: 'shell', label: 'Run', status: 'done', todoId: 'plan-0' })]} />,
    );
    const timeline = screen.getByTestId('action-timeline');
    expect(within(timeline).getByText('Step 1')).toBeInTheDocument();
  });
});
