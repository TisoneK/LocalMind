import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { ActivityRail } from './ActivityRail';
import type { AgentRun, ToolCall } from '@/types';

vi.mock('@/components/panels/AgentWorkspace', () => ({
  AgentWorkspace: () => <div data-testid="run-details" />,
}));

const tool = (id: string, over: Partial<ToolCall> = {}): ToolCall => ({ id, name: 'shell', status: 'done', input: `cmd ${id}`, ...over });
const parent = (tools: ToolCall[]): AgentRun => ({
  id: 'p', name: 'parent', role: 'parent', status: 'running', depth: 0, startedAt: 0, tools,
});

describe('ActivityRail', () => {
  it('shows a quiet empty state when idle', () => {
    render(<ActivityRail runs={[]} isStreaming={false} />);
    expect(screen.getByText('idle')).toBeInTheDocument();
    expect(screen.getByText(/Nothing running/)).toBeInTheDocument();
  });

  it('lists what is running now, the plan with nested steps, agents and files', () => {
    render(
      <ActivityRail
        isStreaming
        runs={[parent([tool('a', { status: 'running' }), tool('b', { name: 'file_write', input: '/w/out.txt:\nx' })])]}
        todos={[
          { id: 'plan-0', text: 'Write output', completed: false, order: 0 },
          { id: 'plan-0-sub-0', text: 'Check state', completed: true, order: 1 },
        ]}
      />,
    );
    expect(screen.getByText('live')).toBeInTheDocument();
    expect(screen.getByText('Running command')).toBeInTheDocument();
    expect(screen.getByText('Write output')).toBeInTheDocument();
    expect(screen.getByText('Check state')).toBeInTheDocument();
    expect(screen.getByText('1/2 tools')).toBeInTheDocument();
    expect(screen.getByText('out.txt')).toBeInTheDocument();
  });

  it('keeps the detailed run tree one click away', () => {
    render(<ActivityRail runs={[parent([])]} isStreaming={false} />);
    expect(screen.queryByTestId('run-details')).toBeNull();
    fireEvent.click(screen.getByText('Run details'));
    expect(screen.getByTestId('run-details')).toBeInTheDocument();
  });
});
