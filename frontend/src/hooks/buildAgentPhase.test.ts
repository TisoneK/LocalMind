/**
 * Tests for the buildAgentPhase helper (Session 181 — F4 Frontend Phase Visibility).
 *
 * The helper converts backend obs event payloads into AgentPhase entries
 * for the phase strip in ChatMessage. Each event type carries different
 * payload fields; these tests pin the extraction logic for each.
 */

import { describe, it, expect } from 'vitest';
import { buildAgentPhase } from './useLocalMind';

describe('buildAgentPhase', () => {
  // ── plan_nodes_created ─────────────────────────────────────────────────

  it('handles plan_nodes_created with node_count + ids', () => {
    const phase = buildAgentPhase('plan_nodes_created', {
      node_count: 3,
      node_ids: ['node-1', 'node-2', 'node-3'],
      intent: 'shell',
    });
    expect(phase).not.toBeNull();
    expect(phase!.type).toBe('plan_created');
    expect(phase!.label).toBe('Plan built — 3 steps');
    expect(phase!.detail).toBe('node-1 → node-2 → node-3');
  });

  it('returns null for plan_nodes_created with count=0', () => {
    const phase = buildAgentPhase('plan_nodes_created', { node_count: 0 });
    expect(phase).toBeNull();
  });

  it('handles singular count (1 step, not 1 steps)', () => {
    const phase = buildAgentPhase('plan_nodes_created', {
      node_count: 1,
      node_ids: ['node-1'],
    });
    expect(phase!.label).toBe('Plan built — 1 step');
  });

  // ── plan_node_advanced ────────────────────────────────────────────────

  it('handles plan_node_advanced with completed status', () => {
    const phase = buildAgentPhase('plan_node_advanced', {
      node_id: 'node-2',
      new_status: 'completed',
      subgoal: 'Read /etc/hostname',
      iteration: 1,
    });
    expect(phase).not.toBeNull();
    expect(phase!.type).toBe('node_advanced');
    expect(phase!.label).toContain('node-2');
    expect(phase!.label).toContain('✓');
    expect(phase!.label).toContain('Read /etc/hostname');
    expect(phase!.iteration).toBe(1);
  });

  it('handles plan_node_advanced with failed status', () => {
    const phase = buildAgentPhase('plan_node_advanced', {
      node_id: 'node-3',
      new_status: 'failed',
      subgoal: 'Run pytest',
    });
    expect(phase!.label).toContain('✗');
  });

  it('returns null for plan_node_advanced without node_id', () => {
    const phase = buildAgentPhase('plan_node_advanced', {
      new_status: 'completed',
      subgoal: 'X',
    });
    expect(phase).toBeNull();
  });

  it('truncates long subgoal text to 100 chars', () => {
    const longSubgoal = 'A'.repeat(200);
    const phase = buildAgentPhase('plan_node_advanced', {
      node_id: 'node-1',
      new_status: 'completed',
      subgoal: longSubgoal,
    });
    expect(phase!.label.length).toBeLessThan(200);
  });

  // ── agent_loop_gate_passed ────────────────────────────────────────────

  it('handles agent_loop_gate_passed with intent', () => {
    const phase = buildAgentPhase('agent_loop_gate_passed', {
      intent: 'shell',
      iteration: 3,
    });
    expect(phase!.type).toBe('gate_passed');
    expect(phase!.label).toContain('shell');
    expect(phase!.label).toContain('Verified');
    expect(phase!.iteration).toBe(3);
  });

  it('handles agent_loop_gate_passed without intent', () => {
    const phase = buildAgentPhase('agent_loop_gate_passed', {});
    expect(phase!.label).toBe('Verified — acceptance gate passed');
  });

  // ── agent_loop_gate_failed_replan ─────────────────────────────────────

  it('handles agent_loop_gate_failed_replan with unmet list', () => {
    const phase = buildAgentPhase('agent_loop_gate_failed_replan', {
      intent: 'file_write',
      iteration: 2,
      unmet: ['file exists at /tmp/foo', 'no errors in output'],
    });
    expect(phase!.type).toBe('gate_failed_replan');
    expect(phase!.label).toContain('file_write');
    expect(phase!.label).toContain('Replanning');
    expect(phase!.detail).toContain('file exists at /tmp/foo');
    expect(phase!.detail).toContain('no errors in output');
  });

  it('limits unmet detail to 3 entries', () => {
    const phase = buildAgentPhase('agent_loop_gate_failed_replan', {
      intent: 'shell',
      unmet: ['one', 'two', 'three', 'four', 'five'],
    });
    expect(phase!.detail).toContain('one');
    expect(phase!.detail).toContain('two');
    expect(phase!.detail).toContain('three');
    expect(phase!.detail).not.toContain('four');
  });

  // ── orchestrator_replan_* ────────────────────────────────────────────

  it('handles orchestrator_replan_start', () => {
    const phase = buildAgentPhase('orchestrator_replan_start', {
      intent: 'shell',
      iteration: 2,
    });
    expect(phase!.type).toBe('orchestrator_replan_start');
    expect(phase!.label).toContain('Orchestrator notified');
    expect(phase!.label).toContain('shell');
  });

  it('handles orchestrator_replan_done with confidence', () => {
    const phase = buildAgentPhase('orchestrator_replan_done', {
      confidence: 0.3,
      intent: 'file_write',
    });
    expect(phase!.type).toBe('orchestrator_replan_done');
    expect(phase!.label).toContain('0.30');
    expect(phase!.label).toContain('file_write');
  });

  it('handles orchestrator_replan_failed with error', () => {
    const phase = buildAgentPhase('orchestrator_replan_failed', {
      error: 'RuntimeError: simulated crash',
    });
    expect(phase!.type).toBe('orchestrator_replan_failed');
    expect(phase!.detail).toContain('RuntimeError');
  });

  // ── agent_loop_failure ───────────────────────────────────────────────

  it('handles agent_loop_failure with reason', () => {
    const phase = buildAgentPhase('agent_loop_failure', {
      reason: 'iteration_limit',
    });
    expect(phase!.type).toBe('agent_loop_failure');
    expect(phase!.label).toBe('Agent loop terminated');
    expect(phase!.detail).toContain('iteration_limit');
  });

  it('handles agent_loop_failure with failure_type', () => {
    const phase = buildAgentPhase('agent_loop_failure', {
      failure_type: 'empty_response',
    });
    expect(phase!.detail).toContain('empty_response');
  });

  // ── unknown event types ───────────────────────────────────────────────

  it('returns null for unknown event type', () => {
    const phase = buildAgentPhase('unknown_event_type', { foo: 'bar' });
    expect(phase).toBeNull();
  });

  it('returns null for undefined event type', () => {
    const phase = buildAgentPhase(undefined as any, {});
    expect(phase).toBeNull();
  });

  // ── defensive: missing payload ───────────────────────────────────────

  it('handles null data defensively', () => {
    const phase = buildAgentPhase('agent_loop_failure', null);
    // Should not crash; label/detail may be defaults.
    expect(phase).not.toBeNull();
    expect(phase!.label).toBe('Agent loop terminated');
  });

  it('handles undefined data defensively', () => {
    const phase = buildAgentPhase('agent_loop_failure', undefined);
    expect(phase).not.toBeNull();
  });

  // ── id stability ──────────────────────────────────────────────────────

  it('generates unique ids for repeated calls', () => {
    const data = { intent: 'shell', iteration: 1 };
    const phase1 = buildAgentPhase('agent_loop_gate_passed', data);
    const phase2 = buildAgentPhase('agent_loop_gate_passed', data);
    expect(phase1!.id).not.toBe(phase2!.id);
  });
});
