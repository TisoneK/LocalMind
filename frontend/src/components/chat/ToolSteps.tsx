'use client';

import {
  FileEdit,
  FileSearch,
  Search,
  Terminal,
  Brain,
  Globe,
  CheckCircle2,
  XCircle,
  Clock,
  Loader2,
  ChevronDown,
  ChevronRight,
} from 'lucide-react';
import { useState, useEffect } from 'react';
import { ToolCall } from '@/types';

interface ToolStepsProps {
  toolCalls: ToolCall[];
  /** v0.7: Compact mode — renders tool steps as a minimal inline row
   *  (icon + label + status) instead of full expandable blocks.
   *  Used in chat messages where full details belong in Actions tab. */
  compact?: boolean;
  /** Whether the parent message is still streaming. When true, the step
   *  currently in a running state auto-expands so the user watches it work
   *  in realtime (Session 118). */
  isStreaming?: boolean;
}

const toolIcons: Record<string, React.ReactNode> = {
  file_write: <FileEdit className="h-3 w-3" />,
  file_read: <FileSearch className="h-3 w-3" />,
  file_task: <FileSearch className="h-3 w-3" />,
  edit_file: <FileEdit className="h-3 w-3 text-brand-amber" />,
  grep: <Search className="h-3 w-3" />,
  code_exec: <Terminal className="h-3 w-3" />,
  shell: <Terminal className="h-3 w-3" />,
  memory_op: <Brain className="h-3 w-3" />,
  web_search: <Globe className="h-3 w-3" />,
  sysinfo: <Search className="h-3 w-3" />,
};

// Human-readable labels for tool names shown in the UI
const toolLabels: Record<string, string> = {
  file_write: 'Creating file',
  file_read: 'Reading file',
  file_task: 'Reading file',
  edit_file: 'Editing file',
  code_exec: 'Running code',
  shell: 'Running command',
  memory_op: 'Memory',
  web_search: 'Searching web',
  sysinfo: 'System info',
};

const statusConfig: Record<string, { icon: React.ReactNode; color: string; bg: string }> = {
  running: {
    icon: <Loader2 className="h-3 w-3 animate-spin" />,
    color: 'text-brand-amber',
    bg: 'bg-brand-amber/5 border-brand-amber/20',
  },
  done: {
    icon: <CheckCircle2 className="h-3 w-3" />,
    color: 'text-brand-green',
    bg: 'bg-brand-green/5 border-brand-green/20',
  },
  failed: {
    icon: <XCircle className="h-3 w-3" />,
    color: 'text-brand-red',
    bg: 'bg-brand-red/5 border-brand-red/20',
  },
  pending: {
    icon: <Clock className="h-3 w-3" />,
    color: 'text-brand-green-muted',
    bg: 'bg-brand-green-muted/5 border-brand-green-muted/20',
  },
};

function ToolStep({ toolCall, isStreaming }: { toolCall: ToolCall; isStreaming?: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const status = statusConfig[toolCall.status] || statusConfig.pending;
  const icon = toolIcons[toolCall.name] || <Terminal className="h-3 w-3" />;
  const isRunning = toolCall.status === 'running';
  // Realtime: while the parent message streams, keep the running step
  // expanded so the user watches it execute. It stays expanded on
  // completion so the result remains visible (the user can collapse it).
  useEffect(() => {
    if (isRunning && isStreaming) setExpanded(true);
  }, [isRunning, isStreaming]);
   // FIX 2: Prefer the human-readable label from the LLM 'description' field.
  // Fall back to the toolLabels map, then to a cleaned-up tool name.
  const label = toolCall.label || toolLabels[toolCall.name] || toolCall.name.replace(/_/g, ' ').replace(/^\w/, c => c.toUpperCase());
  const inputStr = toolCall.input || '';
  // Show the full input — CSS truncate handles visual truncation.
  // Previously this had JS .slice(0, 60) + '...' which caused double truncation
  // (JS truncation + CSS truncation) leading to confusing display like "ating README.md".
  // Check if this tool produced code that should be shown in a code block
  const isCodeTool = toolCall.name === 'code_exec';
  const isFileWrite = toolCall.name === 'file_write';
  const filePath = isFileWrite ? toolCall.input : null;

  return (
    <div className={`border rounded-md overflow-hidden mb-1.5 ${status.bg} ${isRunning ? 'border-brand-amber/40 shadow-[0_0_0_1px_rgba(255,196,0,0.15)]' : ''}`}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 w-full px-2.5 py-1.5 hover:bg-white/[0.02] transition-colors text-left"
      >
        {expanded ? (
          <ChevronDown className="h-3 w-3 text-brand-green-muted shrink-0" />
        ) : (
          <ChevronRight className="h-3 w-3 text-brand-green-muted shrink-0" />
        )}
        <span className={`${status.color} ${isRunning ? 'animate-pulse' : ''}`}>{icon}</span>
        <span className="text-[11px] text-brand-green-soft font-mono shrink-0">
          {label}
        </span>
        {isRunning && (
          <span className="inline-flex items-center gap-1 text-[9px] text-brand-amber shrink-0">
            <span className="w-1.5 h-1.5 rounded-full bg-brand-amber animate-ping" />
            working…
          </span>
        )}
        {inputStr && !isCodeTool && (
          <span className="text-[11px] text-brand-green-muted font-mono truncate flex-1 min-w-0 break-all" title={inputStr}>
            {inputStr}
          </span>
        )}
        <span className={status.color}>{status.icon}</span>
        {(toolCall.status === 'done' || toolCall.status === 'failed' || toolCall.duration !== undefined) && (
          <span className="text-[9px] text-brand-green-muted shrink-0">
            {toolCall.duration !== undefined
              ? (toolCall.duration >= 1000 ? `${(toolCall.duration / 1000).toFixed(1)}s` : `${toolCall.duration}ms`)
              : (toolCall.status === 'done' ? '0ms' : '')}
          </span>
        )}
        {toolCall.timestamp && (
          <span className="text-[9px] text-brand-green-faint shrink-0 ml-auto">
            {toolCall.timestamp}
          </span>
        )}
      </button>
      {expanded && (
        <div className="px-2.5 py-2 border-t border-brand-border/50 bg-brand-bg-dark">
          {isCodeTool && toolCall.input && (
            <>
              <div className="text-[10px] text-brand-green-muted mb-1">Code:</div>
              <div className="rounded-md border border-brand-border overflow-hidden mb-1.5">
                <div className="flex items-center justify-between px-3 py-1 bg-brand-bg-code border-b border-brand-border">
                  <span className="text-[9px] font-mono text-brand-green uppercase">python</span>
                </div>
                <pre className="p-2.5 overflow-x-auto text-[11px] leading-relaxed font-mono text-brand-green-code bg-brand-bg-deep whitespace-pre max-h-60 max-w-full">
                  {toolCall.input}
                </pre>
              </div>
            </>
          )}
          {isFileWrite && filePath && (
            <>
              <div className="text-[10px] text-brand-green-muted mb-1">File:</div>
              <div className="text-[11px] text-brand-green font-mono bg-brand-bg-base rounded px-2 py-1 mb-1.5 break-all overflow-hidden">
                {filePath}
              </div>
            </>
          )}
          {!isCodeTool && !isFileWrite && toolCall.input && (
            <>
              <div className="text-[10px] text-brand-green-muted mb-1">Input:</div>
              <div className="text-[11px] text-brand-green-soft font-mono bg-brand-bg-base rounded px-2 py-1 mb-1.5 break-all overflow-hidden">
                {toolCall.input}
              </div>
            </>
          )}
          {toolCall.output && (
            <>
              <div className="text-[10px] text-brand-green-muted mb-1">Output:</div>
              <div className={`text-[11px] font-mono bg-brand-bg-base rounded px-2 py-1 ${toolCall.status === 'failed' ? 'text-brand-red' : 'text-brand-green'} max-h-40 overflow-y-auto overflow-x-auto max-w-full whitespace-pre-wrap break-all`}>
                {toolCall.output}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

export function ToolSteps({ toolCalls, compact, isStreaming }: ToolStepsProps) {
  // v0.7: Compact mode — minimal inline chips showing tool status
  if (compact) {
    return (
      <div className="flex flex-wrap gap-1.5 items-center">
        {toolCalls.map((tc) => {
          const status = statusConfig[tc.status] || statusConfig.pending;
          const icon = toolIcons[tc.name] || <Terminal className="h-3 w-3" />;
          const label = tc.label || toolLabels[tc.name] || tc.name.replace(/_/g, ' ').replace(/^\w/, c => c.toUpperCase());
          return (
            <div
              key={tc.id}
              className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md border text-[10px] font-mono ${status.bg} ${status.color}`}
            >
              {icon}
              <span className="truncate max-w-[120px]">{label}</span>
              {status.icon}
            </div>
          );
        })}
      </div>
    );
  }

  return (
    <div className="space-y-0">
      {toolCalls.map((tc) => (
        <ToolStep key={tc.id} toolCall={tc} isStreaming={isStreaming} />
      ))}
    </div>
  );
}
