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
    // S296: root parent runs are now labelled by turn ("Turn 1") and grouped.
    expect(screen.getByText('Turn 1')).toBeInTheDocument();
    expect(screen.getByText('research')).toBeInTheDocument();
    fireEvent.click(screen.getByText('research'));
    expect(screen.getByText('Search upstream docs')).toBeInTheDocument();
    // S296: the workspace now groups by turn — one parent turn here.
    expect(screen.getByText('Turns')).toBeInTheDocument();
  });

  it('renders the empty state before the first turn starts', () => {
    render(<AgentWorkspace runs={[]} />);
    expect(screen.getByText(/workspace will appear when a turn starts/i)).toBeInTheDocument();
  });

  it('surfaces a running (alive) run in the header count and status', () => {
    render(<AgentWorkspace runs={runs} />);
    // parent-1 is running → header shows an active count and the node "working".
    expect(screen.getByText('1 active')).toBeInTheDocument();
    expect(screen.getByText('working')).toBeInTheDocument();
  });

  it('renders the active-agent lifecycle phases inside the run node', () => {
    const withPhases: AgentRun[] = [
      {
        ...runs[0],
        phases: [
          { id: 'p1', type: 'initializing', label: 'Getting started — understanding your request', timestamp: 1000 },
          { id: 'p2', type: 'understanding', label: 'Understanding your request', detail: 'the user wants the file listed', timestamp: 1100 },
          { id: 'p3', type: 'initialized', label: 'Understood — execute mode', timestamp: 1200 },
          { id: 'p4', type: 'working', label: 'Working — executing the plan', timestamp: 1300 },
          { id: 'p5', type: 'turn_done', label: 'Turn complete', detail: '3 iterations', timestamp: 1400 },
        ],
      },
    ];
    render(<AgentWorkspace runs={withPhases} />);

    // Lifecycle strip renders inside the (default-expanded) parent node.
    expect(screen.getByText('Lifecycle')).toBeInTheDocument();
    expect(screen.getByTestId('run-phase-initializing')).toBeInTheDocument();
    expect(screen.getByTestId('run-phase-understanding')).toBeInTheDocument();
    expect(screen.getByTestId('run-phase-turn_done')).toBeInTheDocument();
    expect(screen.getByText('Getting started — understanding your request')).toBeInTheDocument();
    expect(screen.getByText('the user wants the file listed')).toBeInTheDocument();
    expect(screen.getByText('3 iterations')).toBeInTheDocument();
  });
});
