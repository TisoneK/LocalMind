import { describe, expect, it } from 'vitest';
import { buildTurn } from './turnTimeline';
import type { AgentPhase, AgentRun, ToolCall, TodoItem } from '@/types';

const tool = (id: string, over: Partial<ToolCall> = {}): ToolCall => ({
  id,
  name: 'shell',
  status: 'done',
  input: `cmd ${id}`,
  ...over,
});

const phase = (over: Partial<AgentPhase>): AgentPhase => ({
  id: 'p',
  type: 'gate_passed',
  label: 'Verified',
  timestamp: 0,
  ...over,
});

describe('buildTurn', () => {
  it('is empty and done for a plain reply', () => {
    const t = buildTurn({}, {});
    expect(t.steps).toEqual([]);
    expect(t.state).toBe('done');
    expect(t.summary).toBe('');
    expect(t.plan).toBeNull();
  });

  it('orders narration, thought, then tools', () => {
    const t = buildTurn({
      acknowledgement: 'On it.',
      thinking: 'consider',
      toolCalls: [tool('a')],
    });
    expect(t.steps.map((s) => s.kind)).toEqual(['narration', 'thought', 'tool']);
  });

  it('groups same-iteration tools into one parallel batch', () => {
    const t = buildTurn({
      toolCalls: [
        tool('a', { iteration: 1, status: 'running' }),
        tool('b', { iteration: 1 }),
        tool('c', { iteration: 2 }),
      ],
    });
    expect(t.steps).toHaveLength(2);
    expect(t.steps[0].kind).toBe('parallel');
    expect(t.steps[0].children).toHaveLength(2);
    expect(t.steps[0].state).toBe('running');
    expect(t.steps[1].kind).toBe('tool');
    expect(t.counts).toMatchObject({ tools: 3, running: 1 });
    expect(t.activeLabel).toBe('Running command');
  });

  it('never batches tools that carry no iteration', () => {
    const t = buildTurn({ toolCalls: [tool('a'), tool('b')] });
    expect(t.steps.map((s) => s.kind)).toEqual(['tool', 'tool']);
  });

  it('nests sub-agent tools under the agent and not at top level', () => {
    const child: AgentRun = {
      id: 'r1',
      name: 'explorer',
      role: 'child',
      status: 'running',
      depth: 1,
      startedAt: 0,
      tools: [tool('x', { status: 'running' })],
    };
    const t = buildTurn({ toolCalls: [tool('x', { status: 'running' }), tool('y')], agentRuns: [child] });
    expect(t.steps.map((s) => s.kind)).toEqual(['tool', 'agent']);
    expect(t.steps[1].children?.[0].tool?.id).toBe('x');
    expect(t.counts.agents).toBe(1);
    expect(t.state).toBe('running');
    expect(t.summary).toBe('Running 2 tools · 1 agent');
  });

  it('places checkpoints by iteration and keeps failures visible', () => {
    const t = buildTurn({
      toolCalls: [tool('a', { iteration: 1 }), tool('b', { iteration: 2 })],
      agentPhases: [
        phase({ id: 'g1', type: 'gate_failed_replan', label: 'Unmet', iteration: 1 }),
        phase({ id: 'g2', type: 'turn_done', label: 'ignored' }),
      ],
    });
    expect(t.steps.map((s) => s.kind)).toEqual(['checkpoint', 'tool', 'tool']);
    // A replan is a recovery: amber, not a failed step.
    expect(t.steps[0].state).toBe('done');
    expect(t.steps[0].tone).toBe('warn');
    expect(t.counts.failed).toBe(0);
  });

  it('uses past tense once a tool is done', () => {
    const t = buildTurn({ toolCalls: [tool('a')] });
    expect(t.steps[0].label).toBe('Ran command');
  });

  it('does not let an unfinished tool spin after the reply is over', () => {
    const t = buildTurn({ toolCalls: [tool('a', { status: 'running' })] }, { isStreaming: false });
    expect(t.state).toBe('done');
    expect(t.steps[0].state).toBe('pending');
    expect(t.counts.running).toBe(0);
    // It never reported back: say so instead of claiming it ran.
    expect(t.steps[0].note).toBe('no result');
    expect(t.counts.unfinished).toBe(1);
    expect(t.summary).toBe("1 didn't finish");
  });

  it('summarises a finished turn', () => {
    const t = buildTurn({ toolCalls: [tool('a'), tool('b', { status: 'failed' })] });
    expect(t.state).toBe('done');
    expect(t.summary).toBe('Ran 2 tools · 1 failed');
  });

  it('stays running while streaming with no tool active and surfaces status text', () => {
    const t = buildTurn({ statusText: 'Understanding your request…' }, { isStreaming: true });
    expect(t.state).toBe('running');
    expect(t.activeLabel).toBe('Understanding your request…');
  });

  it('does not repeat the target when the label already carries it', () => {
    const t = buildTurn({ toolCalls: [tool('a', { label: 'Exploring (list): /tmp/x', input: 'list /tmp/x' })] });
    expect(t.steps[0].detail).toBeUndefined();
  });

  it('says it is reading the result between tools, not the stale status line', () => {
    const t = buildTurn({ toolCalls: [tool('a')], statusText: 'Done — Exploring' }, { isStreaming: true });
    expect(t.activeLabel).toBe('Thinking about the result');
  });

  it('derives the plan and current item from todos', () => {
    const todos: TodoItem[] = [
      { id: '1', text: 'one', completed: true, order: 0 },
      { id: '2', text: 'two', completed: false, order: 1, status: 'running' },
      { id: '3', text: 'three', completed: false, order: 2 },
    ];
    const plan = buildTurn({}, { todos }).plan;
    expect(plan).toMatchObject({ done: 1, total: 3, currentIndex: 1 });
    expect(plan?.items.map((i) => i.state)).toEqual(['done', 'running', 'pending']);
  });

  it('nests sub-goal rows under their goal and leaves them out of the count', () => {
    const todos: TodoItem[] = [
      { id: 'plan-0', text: 'Create a', completed: false, order: 0 },
      { id: 'plan-0-sub-0', text: 'Check state', completed: false, order: 1 },
      { id: 'plan-0-sub-1', text: 'Write it', completed: false, order: 2 },
      { id: 'plan-1', text: 'Create b', completed: false, order: 3 },
    ];
    const plan = buildTurn({}, { todos }).plan;
    expect(plan?.total).toBe(2);
    expect(plan?.items[0].children?.map((c) => c.label)).toEqual(['Check state', 'Write it']);
    expect(plan?.items[1].children).toBeUndefined();
  });
});
