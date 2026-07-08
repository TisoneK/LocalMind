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
  file_write: 'text-[#39d353]',
  file_read: 'text-[#8ab08a]',
  file_task: 'text-[#8ab08a]',
  grep: 'text-[#e8a420]',
  code_exec: 'text-[#39d353]',
  shell: 'text-[#39d353]',
  memory_op: 'text-[#8ab08a]',
  web_search: 'text-[#e8a420]',
  sysinfo: 'text-[#8ab08a]',
};

const statusConfig: Record<string, { icon: React.ReactNode; color: string }> = {
  running: {
    icon: <Loader2 className="h-2.5 w-2.5 animate-spin" />,
    color: 'text-[#e8a420]',
  },
  done: {
    icon: <CheckCircle2 className="h-2.5 w-2.5" />,
    color: 'text-[#39d353]',
  },
  failed: {
    icon: <XCircle className="h-2.5 w-2.5" />,
    color: 'text-[#e05555]',
  },
  pending: {
    icon: <Clock className="h-2.5 w-2.5" />,
    color: 'text-[#8ab08a]',
  },
};

export function ActionHistory({ actions }: ActionHistoryProps) {
  return (
    <div className="space-y-0.5">
      {actions.map((action) => {
        const status = statusConfig[action.status] ?? statusConfig.pending;
        return (
          <div
            key={action.id}
            className="group flex items-start gap-2 px-2 py-1.5 rounded hover:bg-[#1a2a1a]/50 cursor-pointer transition-colors"
          >
            <div className="flex items-center gap-1.5 shrink-0 pt-0.5">
              <span className={actionColors[action.type]}>
                {actionIcons[action.type]}
              </span>
              <span className={status.color}>{status.icon}</span>
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="text-[11px] text-[#d4e8d4] truncate font-medium">
                  {action.label}
                </span>
                {action.duration && (
                  <span className="text-[9px] text-[#8ab08a] shrink-0">
                    {action.duration}s
                  </span>
                )}
                {action.timestamp && (
                  <span className="text-[9px] text-[#5a7a5a] shrink-0 ml-auto">
                    {action.timestamp}
                  </span>
                )}
              </div>
              <div className="text-[10px] text-[#8ab08a] truncate">
                {action.detail}
              </div>
            </div>
            <ChevronRight className="h-3 w-3 text-[#8ab08a] shrink-0 opacity-0 group-hover:opacity-100 transition-opacity mt-1" />
          </div>
        );
      })}
    </div>
  );
}
