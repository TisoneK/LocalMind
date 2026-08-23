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
  Zap,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { useState, useEffect, useMemo } from 'react';
import { ToolCall } from '@/types';
import { useEnterMotion } from '@/lib/localmind/motion';

interface ToolStepsProps {
  toolCalls: ToolCall[];
  /** v0.7: Compact mode — renders tool steps as a minimal inline row
   *  (icon + label + status) instead of full expandable blocks.
   *  Used in chat messages where full details belong in Actions tab. */
  compact?: boolean;
  /** Whether the parent message is still streaming. When true, the group
   *  auto-expands and the running step pulses so the user watches the
   *  agent work in realtime (Session 118; timeline redesign Session 210). */
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

const statusConfig: Record<string, { icon: React.ReactNode; color: string; bg: string; dot: string }> = {
  running: {
    icon: <Loader2 className="h-3 w-3 animate-spin" />,
    color: 'text-brand-amber',
    bg: 'bg-brand-amber/5 border-brand-amber/20',
    dot: 'bg-brand-amber',
  },
  done: {
    icon: <CheckCircle2 className="h-3 w-3" />,
    color: 'text-brand-green',
    bg: 'bg-brand-green/5 border-brand-green/20',
    dot: 'bg-brand-green',
  },
  failed: {
    icon: <XCircle className="h-3 w-3" />,
    color: 'text-brand-red',
    bg: 'bg-brand-red/5 border-brand-red/20',
    dot: 'bg-brand-red',
  },
  pending: {
    icon: <Clock className="h-3 w-3" />,
    color: 'text-brand-green-muted',
    bg: 'bg-brand-green-muted/5 border-brand-green-muted/20',
    dot: 'bg-brand-green-line',
  },
};

// ── Live summary ────────────────────────────────────────────────────────────
// Groups tool calls into natural-language phrases matching the reference
// agent's Actions header ("Wrote 1 file, Ran 2 commands"). Only completed
// (done/failed) calls count toward the phrase; running/pending drive the
// active state instead.

type SummaryBucket = 'write' | 'edit' | 'read' | 'command' | 'search' | 'memory' | 'info';

const BUCKET_OF: Record<string, SummaryBucket> = {
  file_write: 'write',
  edit_file: 'edit',
  file_read: 'read',
  file_task: 'read',
  shell: 'command',
  code_exec: 'command',
  web_search: 'search',
  grep: 'search',
  memory_op: 'memory',
  sysinfo: 'info',
};

const BUCKET_ORDER: SummaryBucket[] = ['write', 'edit', 'read', 'command', 'search', 'memory', 'info'];

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

function bucketPhrase(bucket: SummaryBucket, n: number): string {
  switch (bucket) {
    case 'write': return `Wrote ${plural(n, 'file', 'files')}`;
    case 'edit': return `Edited ${plural(n, 'file', 'files')}`;
    case 'read': return `Read ${plural(n, 'file', 'files')}`;
    case 'command': return `Ran ${plural(n, 'command', 'commands')}`;
    case 'search': return `Ran ${plural(n, 'search', 'searches')}`;
    case 'memory': return `${plural(n, 'memory update', 'memory updates')}`;
    case 'info': return 'Checked system info';
  }
}

function summarizeCalls(toolCalls: ToolCall[]): string {
  const counts = new Map<SummaryBucket, number>();
  for (const tc of toolCalls) {
    if (tc.status !== 'done' && tc.status !== 'failed') continue;
    const bucket = BUCKET_OF[tc.name] || 'command';
    counts.set(bucket, (counts.get(bucket) || 0) + 1);
  }
  const phrases: string[] = [];
  for (const bucket of BUCKET_ORDER) {
    const n = counts.get(bucket);
    if (n && n > 0) phrases.push(bucketPhrase(bucket, n));
  }
  return phrases.join(', ');
}

// ── Per-step detail (why / input / output / code / file) ────────────────────
function StepDetail({ toolCall }: { toolCall: ToolCall }) {
  const isCodeTool = toolCall.name === 'code_exec';
  const isFileWrite = toolCall.name === 'file_write';
  const filePath = isFileWrite ? toolCall.input : null;
  return (
    <div className="mt-1 rounded-md border border-brand-border/50 bg-brand-bg-dark px-2.5 py-2">
      {/* Session 265: only render the Why block when the reasoning has real
          content — a whitespace-only plan-step label would otherwise show an
          empty "Why" section that wastes space. */}
      {toolCall.reasoning?.trim() && (
        <div className="mb-1.5">
          <div className="text-[10px] text-brand-amber mb-0.5">Why</div>
          <p className="text-[10px] italic text-brand-green-soft leading-snug whitespace-pre-wrap break-words max-h-24 overflow-y-auto">
            {toolCall.reasoning}
          </p>
        </div>
      )}
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
  );
}

// ── Timeline row — one tool step, connected by a vertical rail ──────────────
function TimelineRow({
  toolCall,
  isLast,
}: {
  toolCall: ToolCall;
  isLast: boolean;
}) {
  const { reduce: reduceMotion, enter } = useEnterMotion();
  const [expanded, setExpanded] = useState(false);
  const status = statusConfig[toolCall.status] || statusConfig.pending;
  const icon = toolIcons[toolCall.name] || <Terminal className="h-3 w-3" />;
  const isRunning = toolCall.status === 'running';

  const label =
    toolCall.label ||
    toolLabels[toolCall.name] ||
    toolCall.name.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase());
  const stepMatch = toolCall.todoId?.match(/^plan-(\d+)$/);
  const inputStr = toolCall.input || '';
  const isCodeTool = toolCall.name === 'code_exec';
  // Session 265: whitespace-only reasoning (empty plan step) is not detail —
  // it must not make the row expandable to an empty Why block.
  const hasDetail = !!(toolCall.reasoning?.trim() || toolCall.input || toolCall.output);

  const durationLabel =
    toolCall.duration !== undefined
      ? toolCall.duration >= 1000
        ? `${(toolCall.duration / 1000).toFixed(1)}s`
        : `${toolCall.duration}ms`
      : toolCall.status === 'done'
        ? '0ms'
        : '';

  return (
    <motion.div
      layout={!reduceMotion}
      {...enter({ x: -6, duration: 0.22 })}
      className="flex items-stretch gap-2"
    >
      {/* Rail: connector line + status dot */}
      <div className="relative w-4 shrink-0" aria-hidden="true">
        {/* top half — hidden on the first row via parent padding */}
        <span className="absolute left-[7px] top-0 h-[11px] w-px bg-brand-border" />
        {!isLast && <span className="absolute left-[7px] top-[11px] bottom-0 w-px bg-brand-border" />}
        <span
          className={`absolute left-[3.5px] top-[8px] h-[7px] w-[7px] rounded-full ring-2 ring-brand-bg-code ${status.dot} ${isRunning ? 'animate-pulse' : ''}`}
        />
        {isRunning && (
          <span className={`absolute left-[3.5px] top-[8px] h-[7px] w-[7px] rounded-full ${status.dot} opacity-60 ${reduceMotion ? '' : 'animate-ping'}`} />
        )}
      </div>

      {/* Content */}
      <div className="min-w-0 flex-1 pb-1.5">
        <button
          onClick={() => hasDetail && setExpanded((e) => !e)}
          className={`group/row flex w-full items-center gap-2 rounded px-1.5 py-1 text-left transition-colors ${hasDetail ? 'hover:bg-brand-border/50' : 'cursor-default'}`}
        >
          <span className={`${status.color} shrink-0 ${isRunning ? 'animate-pulse' : ''}`}>{icon}</span>
          <span className="shrink-0 font-mono text-[11px] text-brand-green-soft">{label}</span>
          {stepMatch && (
            <span
              className="shrink-0 rounded border border-brand-amber/20 bg-brand-amber/10 px-1 py-px text-[8px] text-brand-amber"
              title={`Serves plan step ${Number(stepMatch[1]) + 1} in the Tasks panel`}
            >
              Step {Number(stepMatch[1]) + 1}
            </span>
          )}
          {inputStr && !isCodeTool && (
            <span
              className="min-w-0 flex-1 truncate break-all font-mono text-[11px] text-brand-green-muted"
              title={inputStr}
            >
              {inputStr}
            </span>
          )}
          <span className={`ml-auto shrink-0 ${status.color}`}>{status.icon}</span>
          {durationLabel && (
            <span className="shrink-0 text-[9px] text-brand-green-muted">{durationLabel}</span>
          )}
          {hasDetail && (
            <span className="shrink-0 text-brand-green-faint">
              {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            </span>
          )}
        </button>
        {/* Inline reasoning peek (visible without expanding) — Session 265:
            hide when the reasoning is whitespace-only (blank "why:" line). */}
        {toolCall.reasoning?.trim() && !expanded && (
          <div className="px-1.5">
            <span
              className="block truncate text-[9px] italic leading-snug text-brand-green-faint"
              title={toolCall.reasoning}
            >
              why: {toolCall.reasoning}
            </span>
          </div>
        )}
        <AnimatePresence initial={false}>
          {expanded && (
            <motion.div
              initial={reduceMotion ? false : { opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={reduceMotion ? undefined : { opacity: 0, height: 0 }}
              transition={{ duration: 0.18, ease: 'easeOut' }}
              className="overflow-hidden px-1.5"
            >
              <StepDetail toolCall={toolCall} />
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}

// ── Grouped Action timeline (full mode) ─────────────────────────────────────
function ActionTimeline({ toolCalls, isStreaming }: { toolCalls: ToolCall[]; isStreaming?: boolean }) {
  const { reduce: reduceMotion, enter } = useEnterMotion();
  const [collapsed, setCollapsed] = useState(false);

  const active = toolCalls.some((tc) => tc.status === 'running' || tc.status === 'pending');
  const failed = toolCalls.some((tc) => tc.status === 'failed');
  const runningCall = toolCalls.find((tc) => tc.status === 'running');
  const summary = useMemo(() => summarizeCalls(toolCalls), [toolCalls]);

  // Auto-expand while the agent is actively working; collapse shortly after
  // it finishes so the transcript stays tidy (the user can re-open it).
  useEffect(() => {
    if (active && isStreaming) {
      setCollapsed(false);
    } else if (!active && !isStreaming) {
      const t = setTimeout(() => setCollapsed(true), 2500);
      return () => clearTimeout(t);
    }
  }, [active, isStreaming]);

  const totalMs = toolCalls.reduce((sum, tc) => sum + (tc.duration || 0), 0);
  const totalLabel = totalMs >= 1000 ? `${(totalMs / 1000).toFixed(1)}s` : totalMs > 0 ? `${totalMs}ms` : '';

  const headerColor = active ? 'text-brand-amber' : failed ? 'text-brand-red' : 'text-brand-green-soft';
  const runningLabel =
    runningCall?.label ||
    (runningCall && toolLabels[runningCall.name]) ||
    'Working';
  const headerText = active ? (summary ? `${summary} · ${runningLabel}…` : `${runningLabel}…`) : summary || 'Actions';

  return (
    <motion.div
      {...enter({ y: 4, duration: 0.25 })}
      className={`mb-2 overflow-hidden rounded-lg border bg-brand-bg-code/60 ${
        active ? 'border-brand-amber/30 shadow-[0_0_0_1px_rgba(240,180,60,0.08)]' : 'border-brand-border'
      }`}
      data-testid="action-timeline"
    >
      <button
        onClick={() => setCollapsed((c) => !c)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-brand-border/40"
      >
        <Zap className={`h-3.5 w-3.5 shrink-0 ${headerColor} ${active ? 'animate-pulse' : ''}`} />
        <span className={`truncate text-[11px] font-medium ${headerColor}`}>{headerText}</span>
        {active && (
          <span className="inline-flex shrink-0 items-center gap-1 text-[9px] text-brand-amber">
            <span className={`h-1.5 w-1.5 rounded-full bg-brand-amber ${reduceMotion ? '' : 'animate-ping'}`} />
          </span>
        )}
        {!active && totalLabel && (
          <span className="shrink-0 text-[9px] text-brand-green-muted">{totalLabel}</span>
        )}
        <span className="ml-auto shrink-0 text-brand-green-muted">
          {collapsed ? <ChevronRight className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        </span>
      </button>

      <AnimatePresence initial={false}>
        {!collapsed && (
          <motion.div
            initial={reduceMotion ? false : { opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={reduceMotion ? undefined : { opacity: 0, height: 0 }}
            transition={{ duration: 0.2, ease: 'easeOut' }}
            className="overflow-hidden border-t border-brand-border/60"
          >
            <div className="px-2.5 pt-2 pb-1">
              <AnimatePresence initial={false}>
                {toolCalls.map((tc) => (
                  <TimelineRow
                    key={tc.id}
                    toolCall={tc}
                    isLast={false}
                  />
                ))}
              </AnimatePresence>

              {/* Terminal row: Done when finished, live pulse while working */}
              <div className="flex items-stretch gap-2">
                <div className="relative w-4 shrink-0" aria-hidden="true">
                  <span className="absolute left-[7px] top-0 h-[11px] w-px bg-brand-border" />
                  <span
                    className={`absolute left-[3.5px] top-[8px] h-[7px] w-[7px] rounded-full ring-2 ring-brand-bg-code ${
                      active ? `bg-brand-amber ${reduceMotion ? '' : 'animate-pulse'}` : failed ? 'bg-brand-red' : 'bg-brand-green'
                    }`}
                  />
                </div>
                <div className="min-w-0 flex-1 pb-1.5">
                  <div className="flex items-center gap-2 px-1.5 py-1">
                    {active ? (
                      <span className="inline-flex items-center gap-1.5 text-[11px] text-brand-amber">
                        <Loader2 className="h-3 w-3 animate-spin" />
                        working…
                      </span>
                    ) : failed ? (
                      <span className="inline-flex items-center gap-1.5 text-[11px] text-brand-red">
                        <XCircle className="h-3 w-3" />
                        Done with errors
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 text-[11px] text-brand-green">
                        <CheckCircle2 className="h-3 w-3" />
                        Done
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

// B-2026-08-23-4: detect a blocked shell call (the shell tool's own guard
// returns "Shell tool is disabled…" when LOCALMIND_SHELL_ENABLED=false).
function isShellBlocked(tc: ToolCall): boolean {
  if (tc.name !== 'shell' || tc.status !== 'failed') return false;
  const hay = `${tc.output || ''} ${tc.error || ''}`.toLowerCase();
  return hay.includes('shell tool is disabled') || hay.includes('shell tool disabled');
}

/**
 * B-2026-08-23-4: when a shell call was blocked, show the user WHY and how to
 * fix it — a one-line guide with an "Open Settings" button. The user asked for
 * a UI guide that helps them open settings and toggle Shell on/off; this
 * surfaces exactly when it's relevant (a shell call was just rejected).
 */
function ShellDisabledTip() {
  return (
    <div
      className="mt-1.5 flex flex-wrap items-center gap-2 rounded-md border border-brand-amber/30 bg-brand-amber/10 px-2.5 py-1.5 text-[11px] text-brand-amber"
      data-testid="shell-disabled-tip"
    >
      <span>💡 The Shell tool is off. Open Settings → Shell tool → toggle it on to run system commands.</span>
      <button
        type="button"
        onClick={() => window.dispatchEvent(new Event('localmind:open-settings'))}
        className="rounded border border-brand-amber/40 bg-brand-amber/10 px-1.5 py-0.5 text-[10px] font-medium text-brand-amber hover:bg-brand-amber/20 transition-colors"
      >
        Open Settings
      </button>
    </div>
  );
}

export function ToolSteps({ toolCalls, compact, isStreaming }: ToolStepsProps) {
  const blocked = toolCalls?.some(isShellBlocked);
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
        {blocked && <ShellDisabledTip />}
      </div>
    );
  }

  if (!toolCalls || toolCalls.length === 0) return null;

  return (
    <>
      <ActionTimeline toolCalls={toolCalls} isStreaming={isStreaming} />
      {blocked && <ShellDisabledTip />}
    </>
  );
}
