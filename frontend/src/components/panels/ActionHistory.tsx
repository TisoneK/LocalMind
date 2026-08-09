'use client';

import {
  FileEdit,
  FileSearch,
  Search,
  Terminal,
  Brain,
  Globe,
  ChevronRight,
  Loader2,
  CheckCircle2,
  XCircle,
  Clock,
} from 'lucide-react';
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

const statusConfig: Record<string, { icon: React.ReactNode; color: string }> = {
  running: {
    icon: <Loader2 className="h-2.5 w-2.5 animate-spin" />,
    color: 'text-brand-amber',
  },
  done: {
    icon: <CheckCircle2 className="h-2.5 w-2.5" />,
    color: 'text-brand-green',
  },
  failed: {
    icon: <XCircle className="h-2.5 w-2.5" />,
    color: 'text-brand-red',
  },
  pending: {
    icon: <Clock className="h-2.5 w-2.5" />,
    color: 'text-brand-green-muted',
  },
};

export function ActionHistory({ actions }: ActionHistoryProps) {
  if (actions.length === 0) {
    return (
      <div className="px-2.5 py-4 text-center text-[10px] text-brand-green-muted">
        No actions yet.
      </div>
    );
  }
  return (
    <div className="space-y-0.5">
      {actions.map((action) => {
        const status = statusConfig[action.status] ?? statusConfig.pending;
        return (
          <div
            key={action.id}
            className="group flex items-start gap-2 px-2 py-1.5 rounded hover:bg-brand-border/50 cursor-pointer transition-colors"
          >
            <div className="flex items-center gap-1.5 shrink-0 pt-0.5">
              <span className={actionColors[action.type]}>
                {actionIcons[action.type]}
              </span>
              <span className={status.color}>{status.icon}</span>
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="text-[11px] text-brand-green-soft truncate font-medium">
                  {action.label}
                </span>
                {action.duration && (
                  <span className="text-[9px] text-brand-green-muted shrink-0">
                    {action.duration}s
                  </span>
                )}
                {action.timestamp && (
                  <span className="text-[9px] text-brand-green-faint shrink-0 ml-auto">
                    {action.timestamp}
                  </span>
                )}
              </div>
              <div className="text-[10px] text-brand-green-muted truncate">
                {action.detail}
              </div>
            </div>
            <ChevronRight className="h-3 w-3 text-brand-green-muted shrink-0 opacity-0 group-hover:opacity-100 transition-opacity mt-1" />
          </div>
        );
      })}
    </div>
  );
}
