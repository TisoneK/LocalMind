/**
 * Activity rail model — the "what is going on right now" panel that sits beside
 * the chat: what is running this second, which agents exist, and
 * which files the turn touched. Derived from the same run tree, todos and diffs
 * the rest of the app already holds, so there is no second source of truth.
 */

import type { AgentRun, DiffData, ToolCall } from '@/types';
import { toolLabel, toolState, type StepState } from '@/lib/localmind/turnTimeline';

export interface RailNow {
  id: string;
  label: string;
  /** Owning agent's name, so parallel work reads "explorer · Reading file". */
  agent: string;
  detail?: string;
}

export interface RailAgent {
  id: string;
  name: string;
  role: AgentRun['role'];
  state: StepState;
  toolsDone: number;
  toolsTotal: number;
  startedAt: number;
  completedAt?: number;
}

export interface RailFile {
  path: string;
  name: string;
  state: StepState;
  additions: number;
  deletions: number;
}

export interface RailModel {
  now: RailNow[];
  agents: RailAgent[];
  files: RailFile[];
  /** Nothing running and nothing to show — render the quiet empty state. */
  empty: boolean;
}

const FILE_TOOLS: ReadonlySet<string> = new Set(['file_write', 'edit_file']);

/** File tools carry the target as the first line of their input ("/path/x.txt:\n…"). */
export function filePathOf(tool: ToolCall): string | null {
  const first = (tool.input || '').split('\n')[0].trim().replace(/:$/, '');
  return first && /[/\\.]/.test(first) ? first : null;
}

/** Tool inputs are length-capped upstream, so a long path arrives cut mid-folder.
 *  The captured diffs carry the full path — resolve through them, and drop a
 *  fragment that has neither a match nor the look of a finished file name. */
function resolveFilePath(raw: string, diffs: Record<string, DiffData> | undefined): string | null {
  const keys = Object.keys(diffs ?? {});
  const hit = keys.find((k) => k === raw) ?? keys.find((k) => k.startsWith(raw));
  if (hit) return hit;
  return /\.[A-Za-z0-9]+$/.test(raw) ? raw : null;
}

function diffCounts(diff: DiffData | undefined): { additions: number; deletions: number } {
  let additions = 0;
  let deletions = 0;
  for (const h of diff?.hunks ?? []) {
    for (const l of h.lines) {
      if (l.type === 'added') additions += 1;
      else if (l.type === 'removed') deletions += 1;
    }
  }
  return { additions, deletions };
}

export function buildRail(input: {
  runs: AgentRun[];
  fileDiffs?: Record<string, DiffData>;
  isStreaming?: boolean;
}): RailModel {
  const settled = input.isStreaming === false;
  const now: RailNow[] = [];
  const files = new Map<string, RailFile>();
  const agents: RailAgent[] = [];

  for (const run of input.runs) {
    let done = 0;
    for (const tool of run.tools) {
      // A tool still "in flight" after the turn ended never reported back — it stays
      // hollow (unfinished) rather than being shown as done.
      const state = toolState(tool.status, settled);
      if (state === 'done' || state === 'failed') done += 1;
      if (state === 'running') {
        now.push({ id: `${run.id}:${tool.id}`, label: toolLabel(tool, state), agent: run.title || run.name, detail: tool.input || undefined });
      }
      if (FILE_TOOLS.has(tool.name)) {
        const raw = filePathOf(tool);
        const path = raw ? resolveFilePath(raw, input.fileDiffs) : null;
        if (path) {
          const counts = diffCounts(input.fileDiffs?.[path]);
          files.set(path, { path, name: path.split(/[/\\]/).pop() || path, state, ...counts });
        }
      }
    }
    agents.push({
      id: run.id,
      name: run.title || run.name,
      role: run.role,
      state: run.status === 'running' ? (settled ? 'pending' : 'running') : run.status === 'completed' ? 'done' : 'failed',
      toolsDone: done,
      toolsTotal: run.tools.length,
      startedAt: run.startedAt,
      completedAt: run.completedAt,
    });
  }

  return {
    now,
    agents,
    files: [...files.values()],
    empty: now.length === 0 && agents.length === 0 && files.size === 0,
  };
}
