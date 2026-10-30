/**
 * The ONE trajectory projection — a pure function from the recorded obs-event
 * stream to the turn's trajectory (tool timeline + agent run tree + phase
 * strip + acknowledgement + injected-item ledger).
 *
 * Why this exists
 * ---------------
 * The trajectory used to be reconstructed TWICE from the same obs events: the
 * backend projected `ObsCollector.history()` at persist time (agent_workspace.py
 * → the `agent_runs`/`agent_phases` columns the UI shows on reload), while the
 * frontend ACCUMULATED the same events imperatively while streaming. Two code
 * paths, hand-kept in sync, that diverged (non-deterministic phase ids, lost
 * list payloads). The live view was an accumulator, not a projection of the
 * record.
 *
 * This module is a faithful, deterministic port of the backend's
 * `build_run_tree` / `build_agent_phases` / `_collect_tool_calls` /
 * `collect_injected_items` (backend/src/core/agent_workspace.py +
 * agent_runtime.py). The live stream now feeds the recorded events to this one
 * reducer, so the live view IS a projection of the record — identical to what
 * the server persists and the reload renders. A cross-language contract test
 * (turnProjection.contract.test.ts + backend test_trajectory_projection.py)
 * over shared fixtures keeps the two ports from drifting again.
 *
 * Pure and synchronous: no React, no network. Wall-clock timestamps are the one
 * non-determinism, so they are injected via `now` (and ignored by the contract
 * test). Everything else — ids included — is a deterministic function of the
 * events.
 */

import type { AgentPhase, AgentRun, InjectedItem, ToolCall } from '@/types';
import { md5Hex } from '@/lib/localmind/md5';

/** A recorded observation event, exactly as the backend's ObsCollector emits
 *  it ({type, data}) and the SSE `obs_event` channel delivers it. */
export interface ProjectionEvent {
  type: string;
  data?: Record<string, unknown>;
}

export interface TrajectoryProjection {
  toolCalls: ToolCall[];
  agentRuns: AgentRun[];
  agentPhases: AgentPhase[];
  acknowledgement?: string;
  injectedItems?: InjectedItem[];
}

// Mirrors agent_workspace._INTERNAL_DELEGATION_TOOLS.
const INTERNAL_DELEGATION_TOOLS = new Set(['delegate', 'delegate_parallel', 'delegate_inline']);

// Mirrors agent_workspace.RUN_LIFECYCLE_TYPES — narrated on the parent run node.
const RUN_LIFECYCLE_TYPES = new Set([
  'agent_initialization_start',
  'agent_initialization_understanding',
  'agent_initialization_ack',
  'agent_initialization_done',
  'agent_planning_done',
  'agent_thinker_start',
  'agent_thinker_done',
  'agent_loop_start',
  'agent_loop_done',
]);

// Mirrors agent_workspace._LIFECYCLE_PHASE_RANK (canonical narrative order).
const LIFECYCLE_PHASE_RANK: Record<string, number> = {
  initializing: 0,
  understanding: 1,
  acknowledged: 2,
  initialized: 3,
  planned: 4,
  thinking: 5,
  thinking_done: 6,
  working: 7,
  turn_done: 8,
};

function str(v: unknown): string {
  // Mirror of Python str() for the scalar shapes obs payloads carry. ObsCollector
  // already stringifies non-JSON-native values, so values arrive as strings,
  // numbers, booleans, lists or dicts.
  if (v === null || v === undefined) return '';
  if (typeof v === 'string') return v;
  if (typeof v === 'boolean') return v ? 'True' : 'False';
  return String(v);
}

function toInt(v: unknown): number | null {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? Math.trunc(n) : null;
}

/** Recover a list payload that ObsCollector.emit stringified via Python str()
 *  into a repr like "['a', 'b']". Mirrors agent_workspace._as_list so the
 *  projection recovers node_ids / unmet that the old live path dropped. */
export function asList(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  if (typeof value === 'string' && value.startsWith('[')) {
    // Python repr uses single quotes; JSON needs double. Try JSON first, then a
    // tolerant single→double swap for simple string/number lists.
    try {
      return JSON.parse(value);
    } catch {
      try {
        const swapped = value.replace(/'/g, '"');
        const parsed = JSON.parse(swapped);
        return Array.isArray(parsed) ? parsed : [];
      } catch {
        return [];
      }
    }
  }
  return [];
}

function visibleToolOutput(toolName: string, agent: string | null, output: string): string {
  if (agent || INTERNAL_DELEGATION_TOOLS.has(toolName)) return '';
  return output;
}

/** Deterministic tool id: tc-<tool>-iter<iteration>-<md5(args)[:6]>.
 *  Mirrors agent_workspace._tool_call_dict / chat._tool_call_payload. */
function toolId(data: Record<string, unknown>): string {
  const tool = str(data.tool) || 'unknown';
  const iteration = data.iteration === undefined || data.iteration === null ? '' : str(data.iteration);
  const argsStr = str(data.tool_args);
  const argsHash = argsStr ? `-${md5Hex(argsStr).slice(0, 6)}` : '';
  return `tc-${tool}-iter${iteration}${argsHash}`;
}

/** Convert a tool_call obs event payload into the frontend ToolCall shape.
 *  Mirrors agent_workspace._tool_call_dict (used by the run-tree merge). */
function toolCallDict(data: Record<string, unknown>): ToolCall & { runId?: string } {
  const tool = str(data.tool) || 'unknown';
  const label = data.label !== undefined ? str(data.label) : tool;
  const status = data.status !== undefined ? str(data.status) : 'running';
  const iterationRaw = data.iteration === undefined || data.iteration === null ? '' : str(data.iteration);
  const argsStr = str(data.tool_args);
  const agent = data.agent ? str(data.agent) : null;
  const duration = toInt(data.latency_ms);
  const retryCount = toInt(data.retry_count);
  const retryAttempts = Array.isArray(data.retry_attempts)
    ? (data.retry_attempts as ToolCall['retryAttempts'])
    : null;
  const iterNum = iterationRaw === '' ? undefined : Number(iterationRaw);
  return {
    id: toolId(data),
    name: tool,
    label: label || tool,
    status: status as ToolCall['status'],
    input: argsStr,
    output: visibleToolOutput(tool, agent, str(data.output)),
    duration: duration === null ? undefined : duration,
    ...(Number.isFinite(iterNum as number) ? { iteration: iterNum } : {}),
    ...(data.todo_id ? { todoId: str(data.todo_id) } : {}),
    ...(data.reasoning || data.thought ? { reasoning: str(data.reasoning) || str(data.thought) } : {}),
    ...(agent ? { agent } : {}),
    ...(data.provider ? { provider: str(data.provider) } : {}),
    ...(retryCount ? { retryCount } : {}),
    ...(retryAttempts ? { retryAttempts } : {}),
  };
}

/** Flat tool timeline (message.toolCalls). Mirrors agent_runtime._collect_tool_calls:
 *  dedupe by id, LAST event for an id wins wholesale (started → done collapses). */
function collectToolCalls(events: ProjectionEvent[]): ToolCall[] {
  const byId = new Map<string, ToolCall>();
  for (const evt of events) {
    if (evt.type !== 'tool_call') continue;
    const tc = toolCallDict(evt.data ?? {});
    byId.set(tc.id, tc);
  }
  return [...byId.values()];
}

function lifecyclePhase(
  evtType: string,
  data: Record<string, unknown>,
  nextId: (prefix: string) => string,
  now: number,
): AgentPhase | null {
  const iteration = data.iteration !== undefined && data.iteration !== null && data.iteration !== ''
    ? Number(data.iteration)
    : undefined;
  switch (evtType) {
    case 'agent_initialization_start':
      return { id: nextId('init-start'), type: 'initializing', label: 'Getting started — understanding your request', timestamp: now };
    case 'agent_initialization_understanding': {
      const text = str(data.understanding).trim();
      if (!text) return null;
      return { id: nextId('understanding'), type: 'understanding', label: 'Understanding your request', detail: text.slice(0, 160), timestamp: now };
    }
    case 'agent_initialization_ack': {
      const text = str(data.acknowledgement).trim();
      if (!text) return null;
      return { id: nextId('ack'), type: 'acknowledged', label: 'Acknowledged', detail: text.slice(0, 160), timestamp: now };
    }
    case 'agent_initialization_done': {
      const mode = str(data.mode);
      return {
        id: nextId('init-done'),
        type: 'initialized',
        label: mode ? `Understood — ${mode} mode` : 'Understood the request',
        detail: str(data.objective).slice(0, 160) || undefined,
        timestamp: now,
      };
    }
    case 'agent_planning_done':
      return { id: nextId('planned'), type: 'planned', label: 'Plan ready — proceeding step by step', timestamp: now, iteration };
    case 'agent_thinker_start':
      return { id: nextId('thinking'), type: 'thinking', label: 'Working out the approach', timestamp: now, iteration };
    case 'agent_thinker_done':
      return { id: nextId('think-done'), type: 'thinking_done', label: 'Approach ready', timestamp: now, iteration };
    case 'agent_loop_start':
      return { id: nextId('working'), type: 'working', label: 'Working — executing the plan', timestamp: now, iteration };
    case 'agent_loop_done': {
      const parts: string[] = [];
      if (data.direct) parts.push('answered directly');
      if (data.clarification) parts.push('asked for clarification');
      if (data.hit_limit) parts.push('iteration limit reached');
      const iters = toInt(data.iterations) ?? 0;
      if (iters) parts.push(`${iters} iterations`);
      return {
        id: nextId('turn-done'),
        type: 'turn_done',
        label: 'Turn complete',
        detail: parts.length ? parts.join('; ') : undefined,
        timestamp: now,
        iteration,
      };
    }
    default:
      return null;
  }
}

/** The agent run tree. Mirrors agent_workspace.build_run_tree exactly. */
function buildRunTree(
  events: ProjectionEvent[],
  opts: { task: string; rootId: string; now: number; rootError?: string | null; settled: boolean },
): AgentRun[] {
  const { task, rootId, now, rootError, settled } = opts;
  // The backend builds the tree at persist time, so the parent is always
  // completed/failed there. Live, the same projection runs every event while
  // the turn is still open — the parent must read "running" until the turn
  // settles, or the Agents tab would show it finished mid-stream.
  const parentStatus: AgentRun['status'] = settled ? (rootError ? 'failed' : 'completed') : 'running';
  const root: AgentRun & { evidence?: AgentRun['evidence'] } = {
    id: rootId,
    name: 'parent',
    role: 'parent',
    task,
    status: parentStatus,
    depth: 0,
    startedAt: now,
    ...(settled ? { completedAt: now } : {}),
    ...(rootError ? { error: rootError } : {}),
    tools: [],
    phases: [],
  };
  const runs: AgentRun[] = [root];
  const byId = new Map<string, AgentRun>([[rootId, root]]);
  const childByAgent = new Map<string, string>();
  let phaseCounter = 0;
  const nextId = (prefix: string) => `phase-${prefix}-${++phaseCounter}`;

  const attachTool = (tc: ToolCall & { runId?: string }) => {
    let runId = tc.runId;
    if (!runId && tc.agent) {
      const agent = tc.agent;
      if (childByAgent.has(agent) && byId.has(childByAgent.get(agent) as string)) {
        runId = childByAgent.get(agent);
      } else {
        for (let i = runs.length - 1; i >= 0; i--) {
          const r = runs[i];
          if (r.role !== 'parent' && r.name === agent && r.status === 'running') {
            runId = r.id;
            break;
          }
        }
      }
    }
    const target = byId.get(runId ?? rootId) ?? root;
    const tools = target.tools;
    for (let i = 0; i < tools.length; i++) {
      if (tools[i].id === tc.id) {
        // Merge, never clobber a present value with a missing one.
        const merged: Record<string, unknown> = { ...tools[i] };
        for (const [k, v] of Object.entries(tc)) {
          if (v !== null && v !== undefined && v !== '') merged[k] = v;
        }
        tools[i] = merged as unknown as ToolCall;
        return;
      }
    }
    tools.push(tc);
  };

  for (const evt of events) {
    const d = evt.data ?? {};
    if (evt.type === 'tool_call') {
      attachTool(toolCallDict(d));
    } else if (evt.type === 'delegation_started') {
      const agent = str(d.target_agent) || 'sub-agent';
      const runId = str(d.run_id) || `child-${agent}`;
      if (!byId.has(runId)) {
        const child: AgentRun = {
          id: runId,
          name: agent,
          role: 'child',
          parentId: rootId,
          task: str(d.task),
          status: 'running',
          depth: toInt(d.depth) ?? 1,
          startedAt: now,
          tools: [],
        };
        runs.push(child);
        byId.set(runId, child);
      }
      childByAgent.set(agent, runId);
    } else if (evt.type === 'delegation_completed') {
      let target = byId.get(str(d.run_id));
      if (!target) {
        const agent = str(d.target_agent);
        for (let i = runs.length - 1; i >= 0; i--) {
          if (runs[i].name === agent) {
            target = runs[i];
            break;
          }
        }
      }
      if (!target) continue;
      const raw = str(d.status);
      target.status = raw === 'completed' ? 'completed' : raw === 'timed_out' ? 'timed_out' : 'failed';
      target.completedAt = now;
      if (d.error_type) target.error = str(d.error_type);
    } else if (evt.type === 'evidence_to_parent') {
      const evidence = root.evidence ?? (root.evidence = []);
      evidence.push({
        tool: str(d.tool) || 'unknown',
        iteration: toInt(d.iteration) ?? 0,
        evidenceChars: toInt(d.evidence_chars) ?? 0,
        failed: Boolean(d.failed),
        timestamp: now,
      });
    } else if (RUN_LIFECYCLE_TYPES.has(evt.type)) {
      if (evt.type === 'agent_initialization_done') {
        const title = cleanTitle(str(d.title));
        if (title) root.title = title;
      }
      const phase = lifecyclePhase(evt.type, d, nextId, now);
      if (phase) {
        const agent = str(d.agent);
        let target: AgentRun = root;
        if (agent) {
          for (let i = runs.length - 1; i >= 0; i--) {
            if (runs[i].role !== 'parent' && runs[i].name === agent) {
              target = runs[i];
              break;
            }
          }
        }
        (target.phases ?? (target.phases = [])).push(phase);
      }
    }
  }
  // Canonical narrative order per run (stable sort by rank).
  for (const run of runs) {
    if (run.phases && run.phases.length) {
      run.phases = stableSort(run.phases, (a, b) =>
        (LIFECYCLE_PHASE_RANK[a.type] ?? 99) - (LIFECYCLE_PHASE_RANK[b.type] ?? 99));
    }
  }
  return runs;
}

/** The turn's action-oriented heading, sanitized identically here and in the
 *  backend (collapse whitespace, cap at 40). */
export function cleanTitle(raw: string): string {
  return raw.replace(/\s+/g, ' ').trim().slice(0, 40);
}

function stableSort<T>(arr: T[], cmp: (a: T, b: T) => number): T[] {
  return arr
    .map((v, i) => [v, i] as const)
    .sort((a, b) => cmp(a[0], b[0]) || a[1] - b[1])
    .map(([v]) => v);
}

/** The chat phase strip (message.agentPhases). Mirrors
 *  agent_workspace.build_agent_phases: the plan/gate/orchestrator/failure/
 *  degraded DECISION history only (lifecycle narration lives on the run tree). */
function buildPhaseStrip(events: ProjectionEvent[], now: number): AgentPhase[] {
  const phases: AgentPhase[] = [];
  let counter = 0;
  const nextId = (prefix: string) => `phase-${prefix}-${++counter}`;
  for (const evt of events) {
    const d = evt.data ?? {};
    const iteration = d.iteration !== undefined && d.iteration !== null && d.iteration !== ''
      ? Number(d.iteration)
      : undefined;
    switch (evt.type) {
      case 'plan_nodes_created': {
        const count = toInt(d.node_count) ?? 0;
        if (!count) break;
        const ids = asList(d.node_ids).map((i) => str(i));
        phases.push({
          id: nextId('plan'),
          type: 'plan_created',
          label: `Plan built — ${count} step${count === 1 ? '' : 's'}`,
          detail: ids.length ? ids.join(' → ') : undefined,
          timestamp: now,
        });
        break;
      }
      case 'plan_node_advanced': {
        const nodeId = str(d.node_id);
        if (!nodeId) break;
        const newStatus = str(d.new_status);
        const subgoal = str(d.subgoal).slice(0, 100);
        const icon = newStatus === 'completed' ? '✓' : newStatus === 'failed' ? '✗' : '~';
        phases.push({
          id: nextId('adv'),
          type: 'node_advanced',
          label: `${nodeId} ${icon} ${subgoal}`,
          detail: newStatus ? `status: ${newStatus}` : undefined,
          timestamp: now,
          iteration,
        });
        break;
      }
      case 'agent_loop_gate_passed': {
        const intent = str(d.intent);
        phases.push({
          id: nextId('gate-pass'),
          type: 'gate_passed',
          label: intent ? `Verified — ${intent} acceptance gate passed` : 'Verified — acceptance gate passed',
          timestamp: now,
          iteration,
        });
        break;
      }
      case 'agent_loop_gate_failed_replan': {
        const intent = str(d.intent);
        const unmet = asList(d.unmet).map((u) => str(u));
        phases.push({
          id: nextId('gate-fail'),
          type: 'gate_failed_replan',
          label: intent ? `Replanning — ${intent} criteria unmet` : 'Replanning — acceptance criteria unmet',
          detail: unmet.length ? `Unmet: ${unmet.slice(0, 3).join('; ')}` : undefined,
          timestamp: now,
          iteration,
        });
        break;
      }
      case 'orchestrator_replan_start': {
        const intent = str(d.intent);
        phases.push({
          id: nextId('orch-start'),
          type: 'orchestrator_replan_start',
          label: intent ? `Orchestrator notified — ${intent} failure` : 'Orchestrator notified of failure',
          timestamp: now,
          iteration,
        });
        break;
      }
      case 'orchestrator_replan_done': {
        const confidence = Number(d.confidence ?? 0) || 0;
        const intent = str(d.intent);
        phases.push({
          id: nextId('orch-done'),
          type: 'orchestrator_replan_done',
          label: intent
            ? `Orchestrator replanned — ${intent}, confidence ${confidence.toFixed(2)}`
            : `Orchestrator replanned — confidence ${confidence.toFixed(2)}`,
          timestamp: now,
        });
        break;
      }
      case 'orchestrator_replan_failed': {
        const error = str(d.error);
        phases.push({
          id: nextId('orch-fail'),
          type: 'orchestrator_replan_failed',
          label: 'Orchestrator replan failed (non-fatal — using fallback)',
          detail: error ? `Error: ${error.slice(0, 120)}` : undefined,
          timestamp: now,
        });
        break;
      }
      case 'agent_loop_failure': {
        const reason = str(d.reason) || str(d.failure_type);
        phases.push({
          id: nextId('fail'),
          type: 'agent_loop_failure',
          label: 'Agent loop terminated',
          detail: reason ? `Reason: ${reason.slice(0, 120)}` : undefined,
          timestamp: now,
        });
        break;
      }
      case 'agent_loop_degraded': {
        const code = str(d.provider_error_code);
        const provider = str(d.provider);
        const terminal = Boolean(d.terminal);
        const preserved = Boolean(d.evidence_preserved);
        const label = terminal
          ? 'Provider died — evidence delivered as gathered'
          : preserved
            ? 'Provider interrupted — partial evidence delivered'
            : 'Provider interrupted the run';
        const parts: string[] = [];
        if (provider) parts.push(`provider: ${provider}`);
        if (code) parts.push(`code: ${code}`);
        phases.push({
          id: nextId('degraded'),
          type: 'agent_loop_degraded',
          label,
          detail: parts.length ? parts.join('; ') : undefined,
          timestamp: now,
        });
        break;
      }
      default:
        break;
    }
  }
  return phases;
}

/** The injected-context ledger. Mirrors agent_workspace.collect_injected_items. */
function collectInjectedItems(events: ProjectionEvent[]): InjectedItem[] | undefined {
  const items: InjectedItem[] = [];
  for (const evt of events) {
    if (evt.type !== 'context_injected') continue;
    const d = evt.data ?? {};
    const surface = str(d.surface);
    const list = Array.isArray(d.items) ? d.items : [];
    for (const raw of list) {
      if (!raw || typeof raw !== 'object') continue;
      const it = raw as Record<string, unknown>;
      const text = str(it.text);
      if (!text) continue;
      items.push({
        kind: str(it.kind) || 'unknown',
        source: str(it.source),
        text,
        chars: toInt(it.chars) ?? text.length,
        surface,
      });
    }
  }
  return items.length ? items : undefined;
}

/** The acknowledgement line — the agent's opening words. */
function extractAck(events: ProjectionEvent[]): string | undefined {
  for (const evt of events) {
    if (evt.type !== 'agent_initialization_ack') continue;
    const text = str((evt.data ?? {}).acknowledgement).slice(0, 180);
    if (text) return text;
  }
  return undefined;
}

/**
 * Project the recorded obs-event stream into the turn's trajectory. The single
 * source of truth for the trajectory view, live and on reload.
 *
 * @param events - the turn's recorded obs events, in emission order.
 * @param opts.task - the user's request (heads the parent run node).
 * @param opts.rootId - the parent run id (default "parent").
 * @param opts.now - wall-clock ms for the timestamps (default Date.now()).
 * @param opts.rootError - the turn's terminal error, if it failed.
 */
export function projectTrajectory(
  events: ProjectionEvent[],
  opts: { task?: string; rootId?: string; now?: number; rootError?: string | null; settled?: boolean } = {},
): TrajectoryProjection {
  const now = opts.now ?? Date.now();
  const rootId = opts.rootId ?? 'parent';
  const task = opts.task ?? '';
  // Default true = the backend's persist-time semantics (parent completed/failed),
  // which the reload path and the contract fixtures use. The live stream passes
  // false while the turn is open so the parent reads "running".
  const settled = opts.settled ?? true;
  const runs = buildRunTree(events, { task, rootId, now, rootError: opts.rootError ?? null, settled });
  const root = runs[0];
  const phaseStrip = buildPhaseStrip(events, now);
  // The turn is worth restoring only when it did real work — a tool, evidence,
  // a child, a decision-strip phase, or an error. Lifecycle-only narration (a
  // direct chat answer) is NOT content: the backend's direct-answer persist
  // paths store no tree, so keeping one here would show a run node a reload
  // can't. Mirrors build_workspace_artifacts' has_content guard exactly.
  const hasContent = Boolean(
    opts.rootError || root.tools.length || (root.evidence && root.evidence.length) ||
    phaseStrip.length || runs.length > 1,
  );
  return {
    toolCalls: collectToolCalls(events),
    // Live (!settled) always keeps the parent so the Agents tab shows the
    // working run from the first event. Settled applies the backend's
    // has_content guard so a bare chat turn does not override the last
    // interesting turn's tree — matching what the server persists on reload.
    agentRuns: !settled || hasContent ? runs : [],
    agentPhases: phaseStrip,
    acknowledgement: extractAck(events),
    injectedItems: collectInjectedItems(events),
  };
}
