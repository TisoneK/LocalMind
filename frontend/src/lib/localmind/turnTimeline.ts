/**
 * Turn model — one chronological, nestable view of everything the agent did
 * (or is doing) in a single reply.
 *
 * The chat message carries this as separate fields — acknowledgement, thinking,
 * phase strip, tool chips, sub-agent runs. Rendering each as its own block makes
 * a working agent look like a stack of unrelated widgets. This module folds
 * them into one ordered step list so the UI can present a single live activity:
 * narration and tools interleaved, parallel tools grouped, sub-agent work nested.
 *
 * Pure and synchronous — no React, no clock. Elapsed time is supplied by the
 * caller so the view can tick it live.
 */

import type { AgentPhase, AgentRun, ChatMessage, TodoItem, ToolCall } from '@/types';
import { isActiveToolStatus } from '@/lib/localmind/progress';

export type StepState = 'running' | 'done' | 'failed' | 'pending';
export type StepKind = 'narration' | 'thought' | 'checkpoint' | 'tool' | 'agent' | 'parallel';

export interface TurnStep {
  id: string;
  kind: StepKind;
  label: string;
  detail?: string;
  state: StepState;
  /** `warn` = a recovery, not a failure (e.g. a replan) — shown amber, never red. */
  tone?: 'warn';
  durationMs?: number;
  /** Set on `tool` steps — the underlying call, for the expanded detail. */
  tool?: ToolCall;
  /** Nested steps: a sub-agent's own work, or the tools of a parallel batch. */
  children?: TurnStep[];
}

export interface PlanItem {
  id: string;
  label: string;
  state: StepState;
  /** Ordered sub-steps of this goal — shown indented, never counted in the totals. */
  children?: PlanItem[];
}

export interface TurnPlan {
  items: PlanItem[];
  done: number;
  total: number;
  /** First item that is running, else first pending — what the agent is on. */
  currentIndex: number;
}

export interface TurnModel {
  steps: TurnStep[];
  state: StepState;
  counts: { tools: number; failed: number; running: number; agents: number };
  /** One-line "what is it doing right now", empty when idle. */
  activeLabel: string;
  /** Collapsed-header text once finished, e.g. "Ran 7 tools · 2 agents". */
  summary: string;
  plan: TurnPlan | null;
}

// Phases worth surfacing as a line in the feed. The rest are lifecycle noise
// (init/working/turn_done) or already shown elsewhere (plan → pill, ack → narration).
const CHECKPOINT_PHASES: ReadonlySet<AgentPhase['type']> = new Set([
  'planned',
  'gate_passed',
  'gate_failed_replan',
  'orchestrator_replan_start',
  'orchestrator_replan_done',
  'orchestrator_replan_failed',
  'agent_loop_failure',
]);

const FAILED_PHASES: ReadonlySet<AgentPhase['type']> = new Set([
  'orchestrator_replan_failed',
  'agent_loop_failure',
]);

const WARN_PHASES: ReadonlySet<AgentPhase['type']> = new Set([
  'gate_failed_replan',
  'orchestrator_replan_start',
]);

// [while running, once finished] — a finished row must not read "Running…".
const TOOL_LABELS: Record<string, [string, string]> = {
  file_write: ['Creating file', 'Created file'],
  file_read: ['Reading file', 'Read file'],
  file_task: ['Reading file', 'Read file'],
  dir_explorer: ['Exploring', 'Explored'],
  edit_file: ['Editing file', 'Edited file'],
  code_exec: ['Running code', 'Ran code'],
  shell: ['Running command', 'Ran command'],
  memory_op: ['Using memory', 'Used memory'],
  web_search: ['Searching the web', 'Searched the web'],
  sysinfo: ['Checking system', 'Checked system'],
};

/** `settled` = the turn is over: a tool still marked running never finished
 *  (aborted / dropped stream), so show it hollow instead of spinning forever. */
export function toolState(status: ToolCall['status'], settled: boolean): StepState {
  if (status === 'failed') return 'failed';
  if (status === 'done') return 'done';
  if (status === 'pending') return 'pending';
  if (isActiveToolStatus(status)) return settled ? 'pending' : 'running';
  return 'done';
}

/** A shell call the shell tool's own guard rejected (it is switched off in Settings). */
export function isShellBlocked(tool: ToolCall): boolean {
  if (tool.name !== 'shell' || tool.status !== 'failed') return false;
  const hay = `${tool.output || ''} ${tool.error || ''}`.toLowerCase();
  return hay.includes('shell tool is disabled') || hay.includes('shell tool disabled');
}

export function toolLabel(tool: ToolCall, state: StepState = 'running'): string {
  const pair = TOOL_LABELS[tool.name];
  return tool.label || (pair ? pair[state === 'done' || state === 'failed' ? 1 : 0] : tool.name);
}

function toolStep(tool: ToolCall, settled: boolean): TurnStep {
  const state = toolState(tool.status, settled);
  const label = toolLabel(tool, state);
  // Backend labels often already carry the target ("Exploring (list): /path") —
  // don't print it a second time as the detail.
  const target = tool.input?.trim().split(/\s+/).pop();
  const repeated = !!target && target.length >= 4 && label.includes(target);
  const detail = tool.input && !repeated ? tool.input : undefined;
  return {
    id: `tool:${tool.id}`,
    kind: 'tool',
    label,
    detail,
    state,
    durationMs: tool.duration,
    tool,
  };
}

/** Roll a set of child states up into one state for the parent row. */
function rollUp(children: TurnStep[]): StepState {
  if (children.some((c) => c.state === 'running')) return 'running';
  if (children.some((c) => c.state === 'pending')) return 'pending';
  if (children.length > 0 && children.every((c) => c.state === 'failed')) return 'failed';
  return 'done';
}

/** Tools that ran in the same loop iteration were issued together — show them as one batch. */
function batchByIteration(tools: ToolCall[], settled: boolean): TurnStep[] {
  const out: TurnStep[] = [];
  let i = 0;
  while (i < tools.length) {
    const iter = tools[i].iteration;
    let j = i + 1;
    if (iter !== undefined) {
      while (j < tools.length && tools[j].iteration === iter) j++;
    }
    const group = tools.slice(i, j);
    if (group.length === 1) {
      out.push(toolStep(group[0], settled));
    } else {
      const children = group.map((g) => toolStep(g, settled));
      out.push({
        id: `batch:${group[0].id}`,
        kind: 'parallel',
        label: `${group.length} tools in parallel`,
        state: rollUp(children),
        durationMs: Math.max(...group.map((t) => t.duration ?? 0)) || undefined,
        children,
      });
    }
    i = j;
  }
  return out;
}

function agentStep(run: AgentRun, settled: boolean): TurnStep {
  const children = batchByIteration(run.tools, settled);
  const state: StepState =
    run.status === 'running'
      ? settled
        ? 'pending'
        : 'running'
      : run.status === 'completed'
        ? 'done'
        : 'failed';
  return {
    id: `agent:${run.id}`,
    kind: 'agent',
    label: run.title || run.name,
    detail: run.task || run.error,
    state,
    durationMs: run.completedAt ? run.completedAt - run.startedAt : undefined,
    children,
  };
}

/** Sub-goal rows (`plan-{i}-sub-{j}`) are guidance nested under their goal, not goals. */
const isSubRow = (id: string) => /^plan-\d+-sub-\d+$/.test(id);

function planItem(t: TodoItem): PlanItem {
  return {
    id: t.id,
    label: t.title || t.text,
    state: t.completed
      ? 'done'
      : t.status === 'failed'
        ? 'failed'
        : t.status && isActiveToolStatus(t.status) && t.status !== 'pending'
          ? 'running'
          : 'pending',
  };
}

export function buildPlan(todos: TodoItem[] | undefined): TurnPlan | null {
  if (!todos || todos.length === 0) return null;
  const sorted = [...todos].sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
  const goals = sorted.filter((t) => !isSubRow(t.id));
  if (goals.length === 0) return null;
  const items: PlanItem[] = goals.map((g) => {
    const subs = sorted.filter((t) => isSubRow(t.id) && t.id.startsWith(`${g.id}-`)).map(planItem);
    return { ...planItem(g), ...(subs.length > 0 ? { children: subs } : {}) };
  });
  const done = items.filter((i) => i.state === 'done').length;
  const running = items.findIndex((i) => i.state === 'running');
  const pending = items.findIndex((i) => i.state === 'pending');
  const currentIndex = running >= 0 ? running : pending >= 0 ? pending : items.length - 1;
  return { items, done, total: items.length, currentIndex };
}

function flatTools(steps: TurnStep[]): TurnStep[] {
  return steps.flatMap((s) => (s.children ? flatTools(s.children) : s.kind === 'tool' ? [s] : []));
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? '' : 's'}`;
}

export function buildTurn(
  message: Pick<
    ChatMessage,
    'acknowledgement' | 'thinking' | 'thinkMs' | 'toolCalls' | 'agentPhases' | 'agentRuns' | 'statusText'
  >,
  opts: { todos?: TodoItem[]; isStreaming?: boolean } = {},
): TurnModel {
  const steps: TurnStep[] = [];
  const streaming = !!opts.isStreaming;
  // Explicit false = the reply is finished; nothing in it can still be running.
  const settled = opts.isStreaming === false;

  if (message.acknowledgement) {
    steps.push({ id: 'ack', kind: 'narration', label: message.acknowledgement, state: 'done' });
  }
  const understanding = message.agentPhases?.find((p) => p.type === 'understanding');
  if (understanding?.label) {
    steps.push({ id: 'understanding', kind: 'narration', label: understanding.label, state: 'done' });
  }
  if (message.thinking) {
    steps.push({
      id: 'thought',
      kind: 'thought',
      label: streaming && !(message.toolCalls?.length) ? 'Thinking' : 'Thought',
      detail: message.thinking,
      state: streaming && !(message.toolCalls?.length) ? 'running' : 'done',
      durationMs: message.thinkMs,
    });
  }

  // Sub-agent runs own their tools; keep those out of the top-level list.
  const childRuns = (message.agentRuns ?? []).filter((r) => r.role !== 'parent');
  const owned = new Set(childRuns.flatMap((r) => r.tools.map((t) => t.id)));
  const topTools = (message.toolCalls ?? []).filter((t) => !owned.has(t.id));

  // Interleave checkpoints between tool batches by iteration.
  const checkpoints = (message.agentPhases ?? []).filter((p) => CHECKPOINT_PHASES.has(p.type));
  const toolSteps = batchByIteration(topTools, settled);
  const iterOf = (s: TurnStep): number => s.tool?.iteration ?? s.children?.[0]?.tool?.iteration ?? 0;
  let ci = 0;
  for (const ts of toolSteps) {
    while (ci < checkpoints.length && (checkpoints[ci].iteration ?? 0) <= iterOf(ts)) {
      steps.push(checkpointStep(checkpoints[ci++]));
    }
    steps.push(ts);
  }
  while (ci < checkpoints.length) steps.push(checkpointStep(checkpoints[ci++]));

  for (const run of childRuns) steps.push(agentStep(run, settled));

  const leaves = flatTools(steps);
  const running = leaves.filter((s) => s.state === 'running');
  const failed = leaves.filter((s) => s.state === 'failed').length;
  const agents = childRuns.length;

  const anyRunning = running.length > 0 || steps.some((s) => s.state === 'running');
  const state: StepState = anyRunning || streaming ? 'running' : failed > 0 && failed === leaves.length ? 'failed' : 'done';

  const active = running[0];
  const activeLabel = active
    ? running.length > 1
      ? `${plural(running.length, 'tool')} running`
      : toolLabel(active.tool as ToolCall, 'running')
    : streaming
      ? // Between tools the model is reading the result; the backend's status text
        // at that point is the previous tool's "Done — …" line, which reads as stale.
        leaves.length > 0
        ? 'Thinking about the result'
        : message.statusText || ''
      : '';

  const parts: string[] = [];
  if (leaves.length > 0) parts.push(`${state === 'running' ? 'Running' : 'Ran'} ${plural(leaves.length, 'tool')}`);
  if (agents > 0) parts.push(plural(agents, 'agent'));
  if (failed > 0) parts.push(`${failed} failed`);

  return {
    steps,
    state,
    counts: { tools: leaves.length, failed, running: running.length, agents },
    activeLabel,
    summary: parts.join(' · '),
    plan: buildPlan(opts.todos),
  };
}

function checkpointStep(p: AgentPhase): TurnStep {
  return {
    id: `phase:${p.id}`,
    kind: 'checkpoint',
    label: p.label,
    detail: p.detail,
    state: FAILED_PHASES.has(p.type) ? 'failed' : 'done',
    ...(WARN_PHASES.has(p.type) ? { tone: 'warn' as const } : {}),
  };
}
