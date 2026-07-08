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
import { useState } from 'react';
import { ToolCall } from '@/types';

interface ToolStepsProps {
  toolCalls: ToolCall[];
  /** v0.7: Compact mode — renders tool steps as a minimal inline row
   *  (icon + label + status) instead of full expandable blocks.
   *  Used in chat messages where full details belong in Actions tab. */
  compact?: boolean;
}

const toolIcons: Record<string, React.ReactNode> = {
  file_write: <FileEdit className="h-3 w-3" />,
  file_read: <FileSearch className="h-3 w-3" />,
  file_task: <FileSearch className="h-3 w-3" />,
  edit_file: <FileEdit className="h-3 w-3 text-[#e8a420]" />,
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
    color: 'text-[#e8a420]',
    bg: 'bg-[#e8a420]/5 border-[#e8a420]/20',
  },
  done: {
    icon: <CheckCircle2 className="h-3 w-3" />,
    color: 'text-[#39d353]',
    bg: 'bg-[#39d353]/5 border-[#39d353]/20',
  },
  failed: {
    icon: <XCircle className="h-3 w-3" />,
    color: 'text-[#e05555]',
    bg: 'bg-[#e05555]/5 border-[#e05555]/20',
  },
  pending: {
    icon: <Clock className="h-3 w-3" />,
    color: 'text-[#8ab08a]',
    bg: 'bg-[#8ab08a]/5 border-[#8ab08a]/20',
  },
};

function ToolStep({ toolCall }: { toolCall: ToolCall }) {
  const [expanded, setExpanded] = useState(false);
  const status = statusConfig[toolCall.status] || statusConfig.pending;
  const icon = toolIcons[toolCall.name] || <Terminal className="h-3 w-3" />;
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
  // Extract code from output for display in code blocks
  const codeOutput = isCodeTool && toolCall.output ? toolCall.output : null;
  const filePath = isFileWrite ? toolCall.input : null;

  return (
    <div className={`border rounded-md overflow-hidden ${status.bg} mb-1.5`}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 w-full px-2.5 py-1.5 hover:bg-white/[0.02] transition-colors text-left"
      >
        {expanded ? (
          <ChevronDown className="h-3 w-3 text-[#8ab08a] shrink-0" />
        ) : (
          <ChevronRight className="h-3 w-3 text-[#8ab08a] shrink-0" />
        )}
        <span className={status.color}>{icon}</span>
        <span className="text-[11px] text-[#d4e8d4] font-mono shrink-0">
          {label}
        </span>
        {inputStr && !isCodeTool && (
          <span className="text-[11px] text-[#8ab08a] font-mono truncate flex-1 min-w-0 break-all" title={inputStr}>
            {inputStr}
          </span>
        )}
        <span className={status.color}>{status.icon}</span>
        {(toolCall.status === 'done' || toolCall.status === 'failed' || toolCall.duration !== undefined) && (
          <span className="text-[9px] text-[#8ab08a] shrink-0">
            {toolCall.duration !== undefined
              ? (toolCall.duration >= 1000 ? `${(toolCall.duration / 1000).toFixed(1)}s` : `${toolCall.duration}ms`)
              : (toolCall.status === 'done' ? '0ms' : '')}
          </span>
        )}
        {toolCall.timestamp && (
          <span className="text-[9px] text-[#5a7a5a] shrink-0 ml-auto">
            {toolCall.timestamp}
          </span>
        )}
      </button>
      {expanded && (
        <div className="px-2.5 py-2 border-t border-[#1a2a1a]/50 bg-[#080d08]">
          {isCodeTool && toolCall.input && (
            <>
              <div className="text-[10px] text-[#8ab08a] mb-1">Code:</div>
              <div className="rounded-md border border-[#1a2a1a] overflow-hidden mb-1.5">
                <div className="flex items-center justify-between px-3 py-1 bg-[#0a120a] border-b border-[#1a2a1a]">
                  <span className="text-[9px] font-mono text-[#39d353] uppercase">python</span>
                </div>
                <pre className="p-2.5 overflow-x-auto text-[11px] leading-relaxed font-mono text-[#a8d8a8] bg-[#040804] whitespace-pre max-h-60 max-w-full">
                  {toolCall.input}
                </pre>
              </div>
            </>
          )}
          {isFileWrite && filePath && (
            <>
              <div className="text-[10px] text-[#8ab08a] mb-1">File:</div>
              <div className="text-[11px] text-[#39d353] font-mono bg-[#0a0f0a] rounded px-2 py-1 mb-1.5 break-all overflow-hidden">
                {filePath}
              </div>
            </>
          )}
          {!isCodeTool && !isFileWrite && toolCall.input && (
            <>
              <div className="text-[10px] text-[#8ab08a] mb-1">Input:</div>
              <div className="text-[11px] text-[#d4e8d4] font-mono bg-[#0a0f0a] rounded px-2 py-1 mb-1.5 break-all overflow-hidden">
                {toolCall.input}
              </div>
            </>
          )}
          {toolCall.output && (
            <>
              <div className="text-[10px] text-[#8ab08a] mb-1">Output:</div>
              <div className={`text-[11px] font-mono bg-[#0a0f0a] rounded px-2 py-1 ${toolCall.status === 'failed' ? 'text-[#e05555]' : 'text-[#39d353]'} max-h-40 overflow-y-auto overflow-x-auto max-w-full whitespace-pre-wrap break-all`}>
                {toolCall.output}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

export function ToolSteps({ toolCalls, compact }: ToolStepsProps) {
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
        <ToolStep key={tc.id} toolCall={tc} />
      ))}
    </div>
  );
}
