/**
 * Tests for AgentPhases component (Session 181 — F4 Frontend Phase Visibility).
 */

import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AgentPhases } from './AgentPhases';
import type { AgentPhase } from '../../types';

const basePhase = (overrides: Partial<AgentPhase> = {}): AgentPhase => ({
  id: 'phase-1',
  type: 'plan_created',
  label: 'Plan built — 3 steps',
  timestamp: Date.now(),
  ...overrides,
});

describe('AgentPhases', () => {
  it('renders nothing when phases is undefined', () => {
    const { container } = render(<AgentPhases />);
    expect(container.firstChild).toBeNull();
  });

  it('renders nothing when phases is empty', () => {
    const { container } = render(<AgentPhases phases={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders a single plan_created phase', () => {
    render(<AgentPhases phases={[basePhase({ type: 'plan_created', label: 'Plan built — 2 steps' })]} />);
    expect(screen.getByText('Plan built — 2 steps')).toBeInTheDocument();
    expect(screen.getByText('Plan built')).toBeInTheDocument(); // label prefix
  });

  it('renders a gate_passed phase with checkmark', () => {
    render(<AgentPhases phases={[basePhase({ id: 'p2', type: 'gate_passed', label: 'Verified — shell acceptance gate passed' })]} />);
    expect(screen.getByText('Verified — shell acceptance gate passed')).toBeInTheDocument();
    expect(screen.getByText('Verified')).toBeInTheDocument();
  });

  it('renders a gate_failed_replan phase with warning icon', () => {
    render(<AgentPhases phases={[basePhase({ id: 'p3', type: 'gate_failed_replan', label: 'Replanning — file_write criteria unmet', detail: 'Unmet: file exists at /tmp/foo' })]} />);
    expect(screen.getByText('Replanning — file_write criteria unmet')).toBeInTheDocument();
    expect(screen.getByText('Unmet: file exists at /tmp/foo')).toBeInTheDocument();
  });

  it('renders an orchestrator_replan_start phase', () => {
    render(<AgentPhases phases={[basePhase({ id: 'p4', type: 'orchestrator_replan_start', label: 'Orchestrator notified — shell failure' })]} />);
    expect(screen.getByText('Orchestrator notified — shell failure')).toBeInTheDocument();
  });

  it('renders an agent_loop_failure phase with red x', () => {
    render(<AgentPhases phases={[basePhase({ id: 'p5', type: 'agent_loop_failure', label: 'Agent loop terminated', detail: 'Reason: empty stream' })]} />);
    expect(screen.getByText('Agent loop terminated')).toBeInTheDocument();
    expect(screen.getByText('Reason: empty stream')).toBeInTheDocument();
  });

  it('renders multiple phases in order', () => {
    render(
      <AgentPhases
        phases={[
          basePhase({ id: 'p1', type: 'plan_created', label: 'Plan built — 2 steps' }),
          basePhase({ id: 'p2', type: 'gate_passed', label: 'Verified — file_write gate passed' }),
          basePhase({ id: 'p3', type: 'node_advanced', label: 'node-1 ✓ Read /etc/hostname' }),
        ]}
      />,
    );
    expect(screen.getByText('Plan built — 2 steps')).toBeInTheDocument();
    expect(screen.getByText('Verified — file_write gate passed')).toBeInTheDocument();
    expect(screen.getByText('node-1 ✓ Read /etc/hostname')).toBeInTheDocument();
  });

  it('renders iteration number when provided', () => {
    render(
      <AgentPhases
        phases={[basePhase({ id: 'p1', type: 'gate_failed_replan', label: 'Replanning', iteration: 2 })]}
      />,
    );
    expect(screen.getByText('iter 2')).toBeInTheDocument();
  });

  it('does not render iteration when not provided', () => {
    render(
      <AgentPhases
        phases={[basePhase({ id: 'p1', type: 'plan_created', label: 'Plan built' })]}
      />,
    );
    expect(screen.queryByText(/iter /)).not.toBeInTheDocument();
  });

  it('renders the strip with the test id', () => {
    render(<AgentPhases phases={[basePhase()]} />);
    expect(screen.getByTestId('agent-phases-strip')).toBeInTheDocument();
  });

  // ── lifecycle phases (bootup-telemetry session) ────────────────────────

  it('renders lifecycle phases with their meta labels', () => {
    render(
      <AgentPhases
        phases={[
          basePhase({ id: 'p-init', type: 'initializing', label: 'Getting started — understanding your request' }),
          basePhase({ id: 'p-initd', type: 'initialized', label: 'Understood — execute mode' }),
          basePhase({ id: 'p-work', type: 'working', label: 'Working — executing the plan' }),
          basePhase({ id: 'p-done', type: 'turn_done', label: 'Turn complete' }),
        ]}
      />,
    );
    expect(screen.getByText('Getting started — understanding your request')).toBeInTheDocument();
    expect(screen.getByText('Understood — execute mode')).toBeInTheDocument();
    expect(screen.getByText('Working — executing the plan')).toBeInTheDocument();
    // meta label prefixes render too (Turn complete matches both the meta
    // label and the phase label, so use getAllByText)
    expect(screen.getByText('Getting started')).toBeInTheDocument();
    expect(screen.getByText('Understood')).toBeInTheDocument();
    expect(screen.getByText('Working')).toBeInTheDocument();
    expect(screen.getAllByText('Turn complete').length).toBeGreaterThanOrEqual(1);
  });
});
