import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { AgentWorkspace } from './AgentWorkspace';
import type { AgentRun } from '@/types';

const runs: AgentRun[] = [
  {
    id: 'parent-1',
    name: 'parent',
    role: 'parent',
    task: 'Investigate the failing request',
    status: 'running',
    depth: 0,
    startedAt: 1000,
    tools: [],
  },
  {
    id: 'child-1',
    name: 'research',
    role: 'child',
    parentId: 'parent-1',
    task: 'Find the upstream behavior',
    status: 'completed',
    depth: 1,
    startedAt: 1100,
    completedAt: 2100,
    tools: [
      {
        id: 'tool-1',
        name: 'web_search',
        label: 'Search upstream docs',
        status: 'done',
        input: 'agent orchestration',
        duration: 1000,
      },
    ],
  },
];

describe('AgentWorkspace', () => {
  it('renders the parent and delegated child as a nested run tree', () => {
    render(<AgentWorkspace runs={runs} />);

    expect(screen.getByTestId('agent-workspace')).toBeInTheDocument();
    expect(screen.getByText('Parent Agent')).toBeInTheDocument();
    expect(screen.getByText('research')).toBeInTheDocument();
    fireEvent.click(screen.getByText('research'));
    expect(screen.getByText('Search upstream docs')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  it('renders the empty state before the first turn starts', () => {
    render(<AgentWorkspace runs={[]} />);
    expect(screen.getByText(/workspace will appear when a turn starts/i)).toBeInTheDocument();
  });
});
