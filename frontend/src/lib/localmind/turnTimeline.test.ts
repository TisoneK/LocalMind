import { describe, expect, it } from 'vitest';
import { buildTurn, toolLabel } from './turnTimeline';
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

  it('names a reasoning-only reply instead of a bare "Done"', () => {
    const t = buildTurn({ thinking: 'hmm', thinkMs: 15800 });
    expect(t.summary).toBe('Thought for 15.8s');
    expect(buildTurn({ thinking: 'hmm' }).summary).toBe('Thought');
  });

  it('does not repeat the whole query when the label already says it', () => {
    const t = buildTurn({ toolCalls: [tool('a', { name: 'web_search', label: 'Searching: weather Kisumu now', input: 'weather Kisumu now' })] });
    expect(t.steps[0].detail).toBeUndefined();
  });

  it('drops a sub-second thought beside real work, but keeps it when it is all there is', () => {
    const withWork = buildTurn({ thinking: 'hm', thinkMs: 147, toolCalls: [tool('a')] });
    expect(withWork.steps.map((s) => s.kind)).toEqual(['tool']);
    const alone = buildTurn({ thinking: 'hm', thinkMs: 147 });
    expect(alone.steps.map((s) => s.kind)).toEqual(['thought']);
    const longThought = buildTurn({ thinking: 'hm', thinkMs: 5000, toolCalls: [tool('a')] });
    expect(longThought.steps.map((s) => s.kind)).toEqual(['thought', 'tool']);
  });

  it('says the answer is being written once reply text is streaming and no tool is running', () => {
    const t = buildTurn({ toolCalls: [tool('a')], content: 'Based on the results…' }, { isStreaming: true });
    expect(t.activeLabel).toBe('Writing the answer');
    const thinking = buildTurn({ toolCalls: [tool('a')], content: '' }, { isStreaming: true });
    expect(thinking.activeLabel).toBe('Thinking about the result');
  });
});


describe('a check that finds nothing', () => {
  const missing = tool('m', {
    name: 'file_task',
    status: 'failed',
    output: "[Tool 'file_task' returned error_type='not_found'] No file found.",
  });

  it('is shown as done with a "not found" note, not as a failure', () => {
    const t = buildTurn({ toolCalls: [missing, tool('w', { name: 'file_write' })] });
    expect(t.steps[0]).toMatchObject({ state: 'done', note: 'not found' });
    expect(t.counts.failed).toBe(0);
    expect(t.summary).toBe('Ran 2 tools');
  });

  it('still counts a genuine failure', () => {
    const t = buildTurn({ toolCalls: [tool('s', { name: 'shell', status: 'failed', error: 'boom' })] });
    expect(t.counts.failed).toBe(1);
  });

  it('does not excuse other tools that merely mention not_found', () => {
    const t = buildTurn({
      toolCalls: [tool('w', { name: 'file_write', status: 'failed', output: "error_type='not_found'" })],
    });
    expect(t.counts.failed).toBe(1);
  });

  it('names a code run instead of repeating the code as its title', () => {
    const tool = { id: 'c', name: 'code_exec', status: 'done', label: 'Executing: import subprocess, sys r = subpro...', input: 'import subprocess, sys\nr = subprocess.run(...)' } as never;
    expect(toolLabel(tool, 'done')).toBe('Ran Python');
    expect(toolLabel(tool, 'running')).toBe('Running Python');
  });

  it('shows each phase of reasoning where it happened, not as one growing block', () => {
    const turn = buildTurn(
      {
        thinking: 'plan the folder\n\ncheck the result',
        thinkMs: 5000,
        thinkingSegments: [
          { text: 'plan the folder', ms: 2000, afterTools: 0 },
          { text: 'check the result', ms: 3000, afterTools: 1 },
        ],
        toolCalls: [
          { id: 'a', name: 'shell', status: 'done', input: 'mkdir x', output: '', iteration: 1 } as never,
          { id: 'b', name: 'shell', status: 'done', input: 'ls x', output: '', iteration: 2 } as never,
        ],
      },
      { isStreaming: false },
    );
    const kinds = turn.steps.map((s) => (s.kind === 'thought' ? `thought:${s.detail}` : s.kind));
    expect(kinds).toEqual(['thought:plan the folder', 'tool', 'thought:check the result', 'tool']);
  });

  it('keeps a single Thought block when there is only one phase of reasoning', () => {
    const turn = buildTurn(
      { thinking: 'just one', thinkMs: 4000, thinkingSegments: [{ text: 'just one', ms: 4000, afterTools: 0 }] },
      { isStreaming: false },
    );
    expect(turn.steps.filter((s) => s.kind === 'thought')).toHaveLength(1);
  });
});
