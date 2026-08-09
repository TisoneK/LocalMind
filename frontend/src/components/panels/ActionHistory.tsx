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

function ActionCard({ action }: { action: ActionItem }) {
  const [expanded, setExpanded] = useState(false);
  const status = statusConfig[action.status] ?? statusConfig.pending;
  const hasOutput = Boolean(action.output || action.error);
  const hasDetail = Boolean(action.input || action.detail);

  return (
    <div
      className="rounded border border-brand-border/60 overflow-hidden hover:border-brand-border transition-colors"
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 w-full px-2 py-1.5 hover:bg-white/[0.02] transition-colors text-left"
      >
        {hasDetail || hasOutput ? (
          expanded ? (
            <ChevronDown className="h-3 w-3 text-brand-green-muted shrink-0" />
          ) : (
            <ChevronRight className="h-3 w-3 text-brand-green-muted shrink-0" />
          )
        ) : (
          <span className="w-3 shrink-0" />
        )}
        <span className={actionColors[action.type]}>{actionIcons[action.type]}</span>
        <span className="text-[11px] text-brand-green-soft font-medium truncate flex-1 min-w-0">
          {action.label}
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
          {!hasOutput && !hasDetail && (
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
  return (
    <div className="space-y-1 px-1">
      {actions.map((action) => (
        <ActionCard key={action.id} action={action} />
      ))}
    </div>
  );
}
