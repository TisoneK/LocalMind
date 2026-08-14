'use client';

import { useMemo, useState } from 'react';
import {
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Circle,
  Clock,
  FileInput,
  Lightbulb,
  Loader2,
  MessageSquareText,
  Wrench,
  XCircle,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import type { AgentRun, AgentRunStatus, ToolCall } from '@/types';
import { formatLatency, isActiveToolStatus } from '@/lib/localmind/progress';
import { useEnterMotion } from '@/lib/localmind/motion';

interface AgentWorkspaceProps {
  runs: AgentRun[];
  isStreaming?: boolean;
}

const statusLabels: Record<AgentRunStatus, string> = {
  running: 'working',
  completed: 'completed',
  failed: 'failed',
  timed_out: 'timed out',
  canceled: 'canceled',
};

function statusIcon(status: AgentRunStatus) {
  if (status === 'running') return <Loader2 className="h-3 w-3 animate-spin" />;
  if (status === 'completed') return <CheckCircle2 className="h-3 w-3" />;
  if (status === 'failed' || status === 'timed_out') return <XCircle className="h-3 w-3" />;
  return <Circle className="h-3 w-3" />;
}

function statusClass(status: AgentRunStatus): string {
  if (status === 'running') return 'text-brand-amber';
  if (status === 'completed') return 'text-brand-green';
  if (status === 'failed' || status === 'timed_out') return 'text-brand-red';
  return 'text-brand-green-muted';
}

function toolLabel(tool: ToolCall): string {
  return tool.label || tool.name.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase());
}

function RunNode({
  run,
  children,
  childMap,
  depth,
}: {
  run: AgentRun;
  children: AgentRun[];
  childMap: Map<string, AgentRun[]>;
  depth: number;
}) {
  const { reduce: reduceMotion, enter } = useEnterMotion();
  const [expanded, setExpanded] = useState(run.status === 'running' || depth === 0);
  const runningTools = run.tools.filter((tool) => isActiveToolStatus(tool.status)).length;
  const completedTools = run.tools.filter((tool) => tool.status === 'done').length;
  // ADR-34 B-7/B-9: expand the node when initialization events or evidence
  // arrive, so the user sees the live thinker + evidence without clicking.
  const hasInitEvents = Boolean(run.acknowledgement || run.understanding);
  const hasEvidence = Boolean(run.evidence && run.evidence.length > 0);
  const hasDetails = children.length > 0 || run.tools.length > 0 || Boolean(run.error) || hasInitEvents || hasEvidence;
  const elapsed = run.completedAt !== undefined ? run.completedAt - run.startedAt : undefined;
  const running = run.status === 'running';

  return (
    <motion.div
      layout={!reduceMotion}
      {...enter({ x: depth > 0 ? -8 : 0, y: depth > 0 ? 0 : 4, duration: 0.24 })}
      className={depth > 0 ? 'ml-3 border-l border-brand-border pl-2' : ''}
    >
      <div
        className={`rounded-md border bg-brand-bg-code/70 overflow-hidden ${
          running
            ? 'border-brand-amber/40 shadow-[0_0_0_1px_rgba(240,180,60,0.08)]'
            : 'border-brand-border'
        }`}
      >
        <button
          type="button"
          onClick={() => hasDetails && setExpanded((value) => !value)}
          className="flex items-start gap-2 w-full px-2.5 py-2 text-left hover:bg-brand-border/40 transition-colors"
          aria-expanded={hasDetails ? expanded : undefined}
        >
          {hasDetails ? (
            expanded ? <ChevronDown className="h-3 w-3 mt-0.5 text-brand-green-muted shrink-0" />
              : <ChevronRight className="h-3 w-3 mt-0.5 text-brand-green-muted shrink-0" />
          ) : <span className="w-3 shrink-0" />}
          <Bot className={`h-3.5 w-3.5 mt-0.5 shrink-0 ${run.role === 'parent' ? 'text-brand-green' : 'text-brand-amber'}`} />
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-1.5">
              <span className="text-[11px] font-medium text-brand-green-soft truncate">
                {run.role === 'parent' ? 'Parent Agent' : run.name}
              </span>
              <span className={`inline-flex items-center gap-1 text-[9px] ${statusClass(run.status)}`}>
                {statusIcon(run.status)}
                {statusLabels[run.status]}
              </span>
            </span>
            {run.task && (
              <span className="block mt-0.5 text-[9px] text-brand-green-muted truncate" title={run.task}>
                {run.task}
              </span>
            )}
          </span>
          <span className="text-[9px] text-brand-green-faint font-mono shrink-0">
            {elapsed !== undefined ? formatLatency(elapsed) : 'live'}
          </span>
        </button>

        {expanded && hasDetails && (
          <div className="border-t border-brand-border/70 px-2.5 py-2 space-y-2">
            <div className="flex items-center gap-3 text-[9px] text-brand-green-muted font-mono">
              <span className="inline-flex items-center gap-1"><Wrench className="h-2.5 w-2.5" /> {run.tools.length} tools</span>
              {runningTools > 0 && <span className="text-brand-amber">{runningTools} running</span>}
              {completedTools > 0 && <span className="text-brand-green">{completedTools} done</span>}
            </div>

            {/* ADR-34 B-7: model-owned acknowledgement streamed during init */}
            {run.acknowledgement && (
              <div className="flex items-start gap-1.5 rounded bg-brand-green/5 border border-brand-green/20 px-2 py-1">
                <MessageSquareText className="h-2.5 w-2.5 mt-0.5 text-brand-green shrink-0" />
                <span className="text-[9px] text-brand-green-soft break-words">{run.acknowledgement}</span>
              </div>
            )}

            {/* ADR-34 B-7: bounded thinker line streamed during init */}
            {run.understanding && (
              <div className="flex items-start gap-1.5 rounded bg-brand-amber/5 border border-brand-amber/20 px-2 py-1">
                <Lightbulb className="h-2.5 w-2.5 mt-0.5 text-brand-amber shrink-0" />
                <span className="text-[9px] text-brand-green-soft break-words">{run.understanding}</span>
              </div>
            )}

            {/* ADR-34 B-8: evidence entries handed to the parent model */}
            {run.evidence && run.evidence.length > 0 && (
              <div className="space-y-0.5">
                {run.evidence.map((entry, idx) => (
                  <div key={`${entry.tool}-${entry.iteration}-${idx}`} className="flex items-center gap-1.5 text-[8px] text-brand-green-muted font-mono">
                    <FileInput className={`h-2 w-2 shrink-0 ${entry.failed ? 'text-brand-red' : 'text-brand-green-faint'}`} />
                    <span className="truncate">evidence ← {entry.tool}</span>
                    <span className="text-brand-green-faint">({entry.evidenceChars} chars)</span>
                    {entry.failed && <span className="text-brand-red">failed</span>}
                  </div>
                ))}
              </div>
            )}

            {run.tools.length > 0 && (
              <div className="space-y-1">
                <AnimatePresence initial={false}>
                {run.tools.map((tool) => (
                  <motion.div
                    key={tool.id}
                    layout={!reduceMotion}
                    {...enter({ x: -6, duration: 0.18 })}
                    className="flex items-center gap-1.5 min-w-0 rounded bg-brand-bg-base px-2 py-1"
                  >
                    <span className={`shrink-0 ${tool.status === 'failed' ? 'text-brand-red' : isActiveToolStatus(tool.status) ? 'text-brand-amber' : 'text-brand-green'}`}>
                      {isActiveToolStatus(tool.status) ? <Loader2 className="h-2.5 w-2.5 animate-spin" /> : tool.status === 'failed' ? <XCircle className="h-2.5 w-2.5" /> : <CheckCircle2 className="h-2.5 w-2.5" />}
                    </span>
                    <span className="text-[9px] text-brand-green-soft truncate" title={tool.input}>
                      {toolLabel(tool)}
                    </span>
                    {tool.duration !== undefined && <span className="ml-auto text-[8px] text-brand-green-faint font-mono shrink-0">{formatLatency(tool.duration)}</span>}
                  </motion.div>
                ))}
                </AnimatePresence>
              </div>
            )}

            {run.error && <p className="text-[9px] text-brand-red break-words">{run.error}</p>}

            {children.length > 0 && (
              <div className="space-y-1.5">
                <AnimatePresence initial={false}>
                  {children.map((child) => <RunNode key={child.id} run={child} children={childMap.get(child.id) ?? []} childMap={childMap} depth={depth + 1} />)}
                </AnimatePresence>
              </div>
            )}
          </div>
        )}
      </div>
    </motion.div>
  );
}

export function AgentWorkspace({ runs, isStreaming = false }: AgentWorkspaceProps) {
  const roots = useMemo(() => runs.filter((run) => !run.parentId), [runs]);
  const childMap = useMemo(() => {
    const map = new Map<string, AgentRun[]>();
    for (const run of runs) {
      if (!run.parentId) continue;
      const children = map.get(run.parentId) ?? [];
      children.push(run);
      map.set(run.parentId, children);
    }
    return map;
  }, [runs]);
  const totalTools = runs.reduce((count, run) => count + run.tools.length, 0);
  const activeRuns = runs.filter((run) => run.status === 'running').length;

  if (runs.length === 0) {
    return (
      <div className="p-3 text-center text-[10px] text-brand-green-muted">
        The parent agent workspace will appear when a turn starts.
      </div>
    );
  }

  return (
    <div className="space-y-3 p-3" data-testid="agent-workspace">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-brand-green-muted font-medium">Agent Workspace</div>
          <div className="text-[9px] text-brand-green-faint mt-0.5">Parent loop and delegated work</div>
        </div>
        <div className={`inline-flex items-center gap-1 text-[9px] font-mono ${activeRuns > 0 || isStreaming ? 'text-brand-amber' : 'text-brand-green'}`}>
          {activeRuns > 0 || isStreaming ? <Loader2 className="h-2.5 w-2.5 animate-spin" /> : <CheckCircle2 className="h-2.5 w-2.5" />}
          {activeRuns > 0 ? `${activeRuns} active` : 'idle'}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="rounded border border-brand-border bg-brand-bg-code px-2 py-1.5">
          <div className="text-[9px] text-brand-green-muted">Runs</div>
          <div className="text-[13px] text-brand-green-soft font-mono">{runs.length}</div>
        </div>
        <div className="rounded border border-brand-border bg-brand-bg-code px-2 py-1.5">
          <div className="text-[9px] text-brand-green-muted">Tool steps</div>
          <div className="text-[13px] text-brand-green-soft font-mono">{totalTools}</div>
        </div>
      </div>

      <div className="space-y-2">
        <AnimatePresence initial={false}>
          {roots.map((root) => (
            <RunNode key={root.id} run={root} children={childMap.get(root.id) ?? []} childMap={childMap} depth={0} />
          ))}
        </AnimatePresence>
      </div>

      <div className="flex items-center gap-2 text-[9px] text-brand-green-faint border-t border-brand-border pt-2">
        <Clock className="h-2.5 w-2.5" /> Child agents receive an isolated task and report back to the parent.
      </div>
    </div>
  );
}
