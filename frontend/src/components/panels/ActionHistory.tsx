'use client';

import {
  FileEdit,
  FileSearch,
  Search,
  Terminal,
  Brain,
  Globe,
  ChevronRight,
  ChevronDown,
  Loader2,
  CheckCircle2,
  XCircle,
  Clock,
  Zap,
  ListChecks,
} from 'lucide-react';
import { useState } from 'react';
import { ActionItem } from '@/types';

interface ActionHistoryProps {
  actions: ActionItem[];
}

const actionIcons: Record<ActionItem['type'], React.ReactNode> = {
  file_write: <FileEdit className="h-3 w-3" />,
  file_read: <FileSearch className="h-3 w-3" />,
  file_task: <FileSearch className="h-3 w-3" />,
  grep: <Search className="h-3 w-3" />,
  code_exec: <Terminal className="h-3 w-3" />,
  shell: <Terminal className="h-3 w-3" />,
  memory_op: <Brain className="h-3 w-3" />,
  web_search: <Globe className="h-3 w-3" />,
  sysinfo: <Search className="h-3 w-3" />,
};

const actionColors: Record<ActionItem['type'], string> = {
  file_write: 'text-brand-green',
  file_read: 'text-brand-green-muted',
  file_task: 'text-brand-green-muted',
  grep: 'text-brand-amber',
  code_exec: 'text-brand-green',
  shell: 'text-brand-green',
  memory_op: 'text-brand-green-muted',
  web_search: 'text-brand-amber',
  sysinfo: 'text-brand-green-muted',
};

const statusConfig: Record<string, { icon: React.ReactNode; color: string; label: string }> = {
  running: {
    icon: <Loader2 className="h-2.5 w-2.5 animate-spin" />,
    color: 'text-brand-amber',
    label: 'running',
  },
  done: {
    icon: <CheckCircle2 className="h-2.5 w-2.5" />,
    color: 'text-brand-green',
    label: 'done',
  },
  failed: {
    icon: <XCircle className="h-2.5 w-2.5" />,
    color: 'text-brand-red',
    label: 'failed',
  },
  pending: {
    icon: <Clock className="h-2.5 w-2.5" />,
    color: 'text-brand-green-muted',
    label: 'pending',
  },
};

/**
 * Group actions into "chains" (one chain = one turn's step sequence).
 * The agent loop numbers steps with `iteration` (1, 2, 3…). A chain
 * continues while iteration is non-decreasing (parallel calls share an
 * iteration); a reset or a missing iteration starts a new chain. Order is
 * by iteration so the persisted (newest-first) history renders chronologically.
 */
function groupChains(actions: ActionItem[]): ActionItem[][] {
  const ordered = [...actions].sort((a, b) => {
    const ai = a.iteration ?? Number.MAX_SAFE_INTEGER;
    const bi = b.iteration ?? Number.MAX_SAFE_INTEGER;
    return ai - bi;
  });
  const chains: ActionItem[][] = [];
  let cur: ActionItem[] = [];
  let prevIter: number | null = null;
  for (const act of ordered) {
    const iter = act.iteration ?? null;
    const continues = prevIter !== null && iter !== null && iter >= prevIter;
    if (!continues && cur.length > 0) {
      chains.push(cur);
      cur = [];
    }
    cur.push(act);
    prevIter = iter;
  }
  if (cur.length > 0) chains.push(cur);
  return chains;
}

/**
 * Session 121: group chains under the plan todo they serve (one todo owns
 * many actions). Chains without a todo_id (legacy data) stay ungrouped.
 */
function groupChainsByTodo(chains: ActionItem[][]): { todoId: string | null; chains: ActionItem[][] }[] {
  const groups: { todoId: string | null; chains: ActionItem[][] }[] = [];
  for (const chain of chains) {
    const todoId = chain[0]?.todoId ?? null;
    const last = groups[groups.length - 1];
    if (last && last.todoId === todoId) {
      last.chains.push(chain);
    } else {
      groups.push({ todoId, chains: [chain] });
    }
  }
  return groups;
}

function ActionCard({ action }: { action: ActionItem }) {
  const [expanded, setExpanded] = useState(false);
  const status = statusConfig[action.status] ?? statusConfig.pending;
  const hasBody = Boolean(action.output || action.error);
  const verbatim = action.input || action.detail || '';

  return (
    <div
      className="rounded border border-brand-border/60 overflow-hidden hover:border-brand-border transition-colors"
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 w-full px-2 py-1.5 hover:bg-white/[0.02] transition-colors text-left"
      >
        {verbatim || hasBody ? (
          expanded ? (
            <ChevronDown className="h-3 w-3 text-brand-green-muted shrink-0" />
          ) : (
            <ChevronRight className="h-3 w-3 text-brand-green-muted shrink-0" />
          )
        ) : (
          <span className="w-3 shrink-0" />
        )}
        <span className={actionColors[action.type]}>{actionIcons[action.type]}</span>
        <span className="flex-1 min-w-0">
          {/* Title — the real action label (e.g. "Running: git status") */}
          <span className="block text-[11px] text-brand-green-soft font-medium truncate">
            {action.label}
          </span>
          {/* Verbatim command/args — visible without expanding */}
          {verbatim && (
            <span
              className="block text-[9px] text-brand-green-muted font-mono truncate"
              title={verbatim}
            >
              {verbatim}
            </span>
          )}
        </span>
        <span className={status.color} title={status.label}>
          {status.icon}
        </span>
        {action.duration !== undefined && (
          <span className="text-[9px] text-brand-green-muted shrink-0">
            {action.duration >= 60
              ? `${(action.duration / 60).toFixed(1)}m`
              : `${action.duration.toFixed(1)}s`}
          </span>
        )}
        {action.timestamp && (
          <span className="text-[9px] text-brand-green-faint shrink-0">{action.timestamp}</span>
        )}
      </button>

      {expanded && (
        <div className="px-2.5 py-2 border-t border-brand-border/50 bg-brand-bg-dark space-y-1.5">
          {action.input && (
            <div>
              <div className="text-[9px] text-brand-green-muted uppercase mb-0.5">
                {action.type === 'shell' ? 'Command' : 'Input'}
              </div>
              <pre className="text-[10px] font-mono text-brand-green-soft bg-brand-bg-base rounded px-2 py-1 whitespace-pre-wrap break-all max-h-24 overflow-y-auto">
                {action.input}
              </pre>
            </div>
          )}
          {action.error && (
            <div>
              <div className="text-[9px] text-brand-red uppercase mb-0.5">Error</div>
              <pre className="text-[10px] font-mono text-brand-red bg-brand-bg-base rounded px-2 py-1 whitespace-pre-wrap break-all max-h-24 overflow-y-auto">
                {action.error}
              </pre>
            </div>
          )}
          {action.output && (
            <div>
              <div className="text-[9px] text-brand-green-muted uppercase mb-0.5">Output</div>
              <pre className={`text-[10px] font-mono ${action.status === 'failed' ? 'text-brand-red' : 'text-brand-green'} bg-brand-bg-base rounded px-2 py-1 whitespace-pre-wrap break-all max-h-40 overflow-y-auto`}>
                {action.output}
              </pre>
            </div>
          )}
          {!hasBody && (
            <div className="text-[10px] text-brand-green-faint">
              {action.status === 'running' ? 'Waiting for tool to complete…' : 'No output returned.'}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function ActionHistory({ actions }: ActionHistoryProps) {
  if (actions.length === 0) {
    return (
      <div className="px-2.5 py-4 text-center text-[10px] text-brand-green-muted">
        No actions yet.
      </div>
    );
  }

  const groups = groupChainsByTodo(groupChains(actions));

  const stepLabel = (todoId: string) => {
    const m = todoId.match(/^plan-(\d+)$/);
    return m ? `Step ${Number(m[1]) + 1}` : todoId;
  };

  return (
    <div className="space-y-2 px-1">
      {groups.map((group, gi) => (
        <div key={gi} className="space-y-2">
          {/* Todo header — the plan step this group of actions serves */}
          {group.todoId && (
            <div className="flex items-center gap-1.5 px-0.5 pt-0.5">
              <ListChecks className="h-2.5 w-2.5 text-brand-green" />
              <span className="text-[9px] text-brand-green uppercase tracking-wide font-medium">
                {stepLabel(group.todoId)}
              </span>
              <span className="text-[9px] text-brand-green-faint">
                {group.chains.reduce((n, c) => n + c.length, 0)} action
                {group.chains.reduce((n, c) => n + c.length, 0) === 1 ? '' : 's'}
              </span>
              <span className="h-px flex-1 bg-brand-border/50" />
            </div>
          )}
        {group.chains.map((chain, ci) => (
        <div key={ci}>
          {/* Chain header — the turn's step count + when it ran */}
          <div className="flex items-center gap-1.5 px-0.5 pb-1 pt-0.5">
            <Zap className="h-2.5 w-2.5 text-brand-amber" />
            <span className="text-[9px] text-brand-green-muted uppercase tracking-wide font-medium">
              {chain.length} step{chain.length > 1 ? 's' : ''}
            </span>
            <span className="text-[9px] text-brand-green-faint">
              {chain[0]?.timestamp ?? ''}
            </span>
            <span className="h-px flex-1 bg-brand-border/50" />
          </div>

          {/* Numbered chain — connector line + step badges */}
          <div className="relative">
            {chain.map((action, i) => (
              <div key={action.id} className="relative pl-6 pb-1.5">
                <span className="absolute left-0 top-1.5 h-4 w-4 rounded-full border border-brand-border bg-brand-bg-base flex items-center justify-center text-[8px] font-mono text-brand-green-muted">
                  {i + 1}
                </span>
                {i < chain.length - 1 && (
                  <span className="absolute left-[7px] top-5 bottom-0 w-px bg-brand-border/70" />
                )}
                <ActionCard action={action} />
              </div>
            ))}
          </div>
        </div>
        ))}
        </div>
      ))}
    </div>
  );
}
