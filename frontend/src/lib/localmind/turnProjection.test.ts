import { describe, it, expect } from 'vitest';
import { projectTrajectory, asList, cleanTitle, type ProjectionEvent } from './turnProjection';
import { md5Hex } from './md5';

const NOW = 1_000;

function toolId(tool: string, iter: number | string, args: string): string {
  const hash = args ? `-${md5Hex(args).slice(0, 6)}` : '';
  return `tc-${tool}-iter${iter}${hash}`;
}

describe('projectTrajectory', () => {
  it('projects a simple tool turn: deterministic id, merged start+done, evidence, ack, title', () => {
    const args = '{"path": "/notes"}';
    const events: ProjectionEvent[] = [
      { type: 'agent_initialization_ack', data: { acknowledgement: 'Sure — looking now.' } },
      { type: 'agent_initialization_done', data: { mode: 'execute', objective: 'list notes', title: 'List notes folder' } },
      { type: 'agent_loop_start', data: {} },
      { type: 'tool_call', data: { tool: 'dir_explorer', label: 'Exploring: /notes', status: 'started', tool_args: args, iteration: 1, reasoning: 'see files' } },
      { type: 'tool_call', data: { tool: 'dir_explorer', label: '', status: 'done', output: 'a.md', latency_ms: 42, tool_args: args, iteration: 1, provider: 'local' } },
      { type: 'evidence_to_parent', data: { tool: 'dir_explorer', iteration: 1, evidence_chars: 4, failed: false } },
      { type: 'agent_loop_done', data: { intent: 'file', iterations: 1 } },
    ];
    const proj = projectTrajectory(events, { task: 'list my notes', now: NOW });

    // Flat timeline: one row (start+done collapsed by id), last event wins wholesale.
    expect(proj.toolCalls).toHaveLength(1);
    const tc = proj.toolCalls[0];
    expect(tc.id).toBe(toolId('dir_explorer', 1, args));
    expect(tc.status).toBe('done');
    expect(tc.duration).toBe(42);
    expect(tc.provider).toBe('local');

    // Run tree: parent carries the merged tool (reasoning from start survives),
    // the evidence, the title and the lifecycle phases in narrative order.
    expect(proj.agentRuns).toHaveLength(1);
    const parent = proj.agentRuns[0];
    expect(parent.role).toBe('parent');
    expect(parent.title).toBe('List notes folder');
    expect(parent.tools).toHaveLength(1);
    expect(parent.tools[0].reasoning).toBe('see files'); // merged from the started event
    expect(parent.tools[0].status).toBe('done');
    expect(parent.evidence).toHaveLength(1);
    expect(parent.phases?.map((p) => p.type)).toEqual(['acknowledged', 'initialized', 'working', 'turn_done']);

    expect(proj.acknowledgement).toBe('Sure — looking now.');
    expect(proj.agentPhases).toEqual([]); // strip holds decision history only
  });

  it('nests a delegated child run and routes the child tool by agent tag', () => {
    const events: ProjectionEvent[] = [
      { type: 'delegation_started', data: { target_agent: 'research', run_id: 'child-research-1', task: 'find sources', depth: 1 } },
      { type: 'tool_call', data: { tool: 'web_search', label: 'Searching', status: 'done', output: 'r', latency_ms: 300, tool_args: '{"query":"x"}', iteration: 1, agent: 'research' } },
      { type: 'delegation_completed', data: { target_agent: 'research', run_id: 'child-research-1', status: 'completed' } },
    ];
    const proj = projectTrajectory(events, { task: 'research', now: NOW });
    expect(proj.agentRuns).toHaveLength(2);
    const child = proj.agentRuns[1];
    expect(child.role).toBe('child');
    expect(child.status).toBe('completed');
    expect(child.tools).toHaveLength(1);
    expect(child.tools[0].agent).toBe('research');
    // Parent owns no tools (the tool was routed to the child).
    expect(proj.agentRuns[0].tools).toHaveLength(0);
  });

  it('builds the decision strip (plan/gate/orchestrator/degraded) with deterministic ids', () => {
    const events: ProjectionEvent[] = [
      { type: 'plan_nodes_created', data: { node_count: 2, node_ids: ['n1', 'n2'] } },
      { type: 'agent_loop_gate_failed_replan', data: { intent: 'search', unmet: ['no source', 'stale'], iteration: 1 } },
      { type: 'orchestrator_replan_done', data: { intent: 'search', confidence: 0.75 } },
      { type: 'agent_loop_degraded', data: { provider_error_code: 'payment_required', provider: 'bankofai', terminal: true, evidence_preserved: true } },
    ];
    const proj = projectTrajectory(events, { task: 'weather', now: NOW });
    expect(proj.agentPhases.map((p) => [p.id, p.type])).toEqual([
      ['phase-plan-1', 'plan_created'],
      ['phase-gate-fail-2', 'gate_failed_replan'],
      ['phase-orch-done-3', 'orchestrator_replan_done'],
      ['phase-degraded-4', 'agent_loop_degraded'],
    ]);
    expect(proj.agentPhases[0].detail).toBe('n1 → n2');
    expect(proj.agentPhases[1].detail).toBe('Unmet: no source; stale');
    expect(proj.agentPhases[2].label).toContain('confidence 0.75');
    expect(proj.agentPhases[3].label).toBe('Provider died — evidence delivered as gathered');
  });

  it('marks the parent failed and keeps a trivial turn tree when there is a root error', () => {
    const proj = projectTrajectory(
      [{ type: 'agent_loop_failure', data: { reason: 'criteria unmet' } }],
      { task: 'x', now: NOW, rootError: 'provider_dead' },
    );
    expect(proj.agentRuns[0].status).toBe('failed');
    expect(proj.agentRuns[0].error).toBe('provider_dead');
    expect(proj.agentPhases[0].type).toBe('agent_loop_failure');
  });

  it('drops a bare parent-only node when nothing structural was recorded', () => {
    // Only non-trajectory events (intent/token/metrics) → no tools, evidence,
    // phases or children → nothing worth restoring. Mirrors
    // build_workspace_artifacts' has_content guard.
    const proj = projectTrajectory([{ type: 'intent_classified', data: { primary: 'chat' } }], { task: 'hi', now: NOW });
    expect(proj.agentRuns).toEqual([]);
  });

  it('collects the injected-item ledger across surfaces, opaque items included', () => {
    const events: ProjectionEvent[] = [
      { type: 'context_injected', data: { surface: 'init_classify', items: [{ kind: 'environment.clock', source: 'system clock', text: '05:00 EAT', chars: 9 }] } },
      { type: 'context_injected', data: { surface: 'loop_turn', items: [{ kind: 'unknown', source: '', text: 'opaque' }] } },
    ];
    const proj = projectTrajectory(events, { task: 'time', now: NOW });
    expect(proj.injectedItems).toHaveLength(2);
    expect(proj.injectedItems?.[0].surface).toBe('init_classify');
    expect(proj.injectedItems?.[1].kind).toBe('unknown');
    expect(proj.injectedItems?.[1].chars).toBe(6); // defaulted to text length
  });

  it('recovers a Python-repr stringified node_ids list', () => {
    const proj = projectTrajectory(
      [{ type: 'plan_nodes_created', data: { node_count: 3, node_ids: "['n1', 'n2', 'n3']" } }],
      { task: 'x', now: NOW },
    );
    expect(proj.agentPhases[0].detail).toBe('n1 → n2 → n3');
  });

  it('is a pure function of the event order — same events, same output', () => {
    const events: ProjectionEvent[] = [
      { type: 'tool_call', data: { tool: 'file_read', status: 'done', tool_args: '{"path":"a"}', iteration: 1 } },
    ];
    const a = projectTrajectory(events, { task: 't', now: NOW });
    const b = projectTrajectory(events, { task: 't', now: NOW });
    expect(a).toEqual(b);
  });
});

describe('asList', () => {
  it('passes through real arrays and recovers repr strings', () => {
    expect(asList(['a', 'b'])).toEqual(['a', 'b']);
    expect(asList("['a', 'b']")).toEqual(['a', 'b']);
    expect(asList('[1, 2, 3]')).toEqual([1, 2, 3]);
    expect(asList('not a list')).toEqual([]);
    expect(asList(undefined)).toEqual([]);
  });
});

describe('cleanTitle', () => {
  it('collapses whitespace and caps at 40 chars', () => {
    expect(cleanTitle('  List   the\nnotes ')).toBe('List the notes');
    expect(cleanTitle('x'.repeat(50))).toHaveLength(40);
  });
});
