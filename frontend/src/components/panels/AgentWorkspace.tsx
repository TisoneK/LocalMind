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
  Loader2,
  Wrench,
  XCircle,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import type { AgentRun, AgentRunStatus, ToolCall } from '@/types';
import { formatLatency, isActiveToolStatus } from '@/lib/localmind/progress';
import { useEnterMotion } from '@/lib/localmind/motion';
import { PHASE_META } from '@/components/chat/AgentPhases';

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
  turnIndex,
  isLast,
}: {
  run: AgentRun;
  children: AgentRun[];
  childMap: Map<string, AgentRun[]>;
  depth: number;
  turnIndex?: number;
  isLast?: boolean;
}) {
  const { reduce: reduceMotion, enter } = useEnterMotion();
  // The MOST-RECENT card stays expanded — while running AND after it completes —
  // and only collapses once a NEWER card pushes it down (a lone card stays open).
  // Derived every render (a one-time useState initializer left completed turns
  // stuck open). `isLast` marks the newest root turn; child nodes fall back to
  // "expanded while running". A manual click pins an explicit state that
  // overrides the auto behavior for that one run.
  const [manualExpanded, setManualExpanded] = useState<boolean | null>(null);
  const defaultExpanded = isLast !== undefined ? isLast : run.status === 'running';
  const expanded = manualExpanded ?? defaultExpanded;
  const runningTools = run.tools.filter((tool) => isActiveToolStatus(tool.status)).length;
  const completedTools = run.tools.filter((tool) => tool.status === 'done').length;
  // ADR-34 B-9: expand the node when evidence arrives so the user sees
  // evidence flowing in without clicking.
  const hasEvidence = Boolean(run.evidence && run.evidence.length > 0);
  const hasPhases = Boolean(run.phases && run.phases.length > 0);
  const hasDetails = children.length > 0 || run.tools.length > 0 || Boolean(run.error) || hasEvidence || hasPhases;
  const elapsed = run.completedAt !== undefined ? run.completedAt - run.startedAt : undefined;
  const running = run.status === 'running';
  // Action-oriented turn heading (e.g. "Fetch Weather") named by the parent's
  // classify call, replacing a bare "Turn N". Falls back to "Turn N" until the
  // classify result arrives or when the model omitted a title. Ordinal stays
  // in the badge.
  const turnLabel = run.role === 'parent' ? (run.title || '').trim() : '';
  const headingLabel =
    run.role === 'parent'
      ? turnLabel || (turnIndex !== undefined ? `Turn ${turnIndex}` : 'Parent Agent')
      : run.name;

  return (
    <motion.div
      {...enter({ x: depth > 0 ? -8 : 0, y: depth > 0 ? 0 : 4, duration: 0.24 })}
      className={depth > 0 ? 'ml-3 border-l border-brand-border pl-2' : ''}
    >
      <div
        className={`relative rounded-lg border overflow-hidden transition-colors ${
          running
            ? 'border-brand-amber/50 bg-gradient-to-br from-brand-amber/[0.07] to-brand-bg-code/70'
            : run.status === 'failed' || run.status === 'timed_out'
              ? 'border-brand-red/30 bg-brand-bg-code/70'
              : 'border-brand-border bg-brand-bg-code/70'
        }`}
      >
        {/* Status accent bar — a gradient rail down the left edge; it breathes
            while the run is active (motion-safe). */}
        <motion.span
          aria-hidden
          className={`absolute left-0 top-0 bottom-0 w-[3px] ${
            running
              ? 'bg-gradient-to-b from-brand-amber to-brand-amber/30'
              : run.status === 'completed'
                ? 'bg-gradient-to-b from-brand-green to-brand-green/20'
                : run.status === 'failed' || run.status === 'timed_out'
                  ? 'bg-brand-red/60'
                  : 'bg-brand-border'
          }`}
          animate={running && !reduceMotion ? { opacity: [0.55, 1, 0.55] } : { opacity: 1 }}
          transition={running && !reduceMotion ? { duration: 1.6, repeat: Infinity, ease: 'easeInOut' } : undefined}
        />
        <button
          type="button"
          onClick={() => hasDetails && setManualExpanded(!expanded)}
          className="flex items-start gap-2 w-full min-w-0 pl-3 pr-2.5 py-2 text-left hover:bg-brand-border/40 transition-colors"
          aria-expanded={hasDetails ? expanded : undefined}
        >
          {hasDetails ? (
            expanded ? <ChevronDown className="h-3 w-3 mt-0.5 text-brand-green-muted shrink-0" />
              : <ChevronRight className="h-3 w-3 mt-0.5 text-brand-green-muted shrink-0" />
          ) : <span className="w-3 shrink-0" />}
          {/* Turn badge on root nodes; agent glyph on children. */}
          {depth === 0 && turnIndex !== undefined ? (
            <span
              className={`grid h-4 w-4 mt-0.5 shrink-0 place-items-center rounded-full text-[8px] font-bold tabular-nums ${
                running
                  ? 'bg-brand-amber/20 text-brand-amber ring-1 ring-brand-amber/40'
                  : 'bg-brand-green/15 text-brand-green ring-1 ring-brand-green/25'
              }`}
              title={turnLabel ? `Turn ${turnIndex} — ${turnLabel}` : `Turn ${turnIndex}`}
            >
              {turnIndex}
            </span>
          ) : (
            <Bot className={`h-3.5 w-3.5 mt-0.5 shrink-0 ${run.role === 'parent' ? 'text-brand-green' : 'text-brand-amber'}`} />
          )}
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-1.5">
              <span className="text-[11px] font-medium text-brand-green-soft truncate" title={run.task || headingLabel}>
                {headingLabel}
              </span>
              <span className={`inline-flex items-center gap-1 shrink-0 whitespace-nowrap text-[9px] ${statusClass(run.status)}`}>
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
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 min-w-0 text-[9px] text-brand-green-muted font-mono">
              <span className="inline-flex items-center gap-1"><Wrench className="h-2.5 w-2.5" /> {run.tools.length} tools</span>
              {runningTools > 0 && <span className="text-brand-amber">{runningTools} running</span>}
              {completedTools > 0 && <span className="text-brand-green">{completedTools} done</span>}
            </div>

            {/* Active-agent lifecycle narration (bootup-telemetry session):
                the phases this run fired — getting started → understood →
                working → turn complete — so the workspace feels alive during
                the longest waits (init, thinking, tool phases). */}
            {run.phases && run.phases.length > 0 && (
              <div className="border-t border-brand-border/50 pt-1.5">
                <div className="text-[8px] uppercase tracking-wider text-brand-green-faint font-medium mb-1">
                  Lifecycle
                </div>
                {/* Connected timeline: a rail down the left with a dot per
                    phase; phases pop in as they arrive (motion-safe), so a
                    child or parent loop narrates itself live and fancily. */}
                <div className="relative pl-3.5">
                  <span aria-hidden className="absolute left-[5px] top-1 bottom-1 w-px bg-gradient-to-b from-brand-green/40 via-brand-border to-transparent" />
                  <AnimatePresence initial={false}>
                    {run.phases.map((phase, pIdx) => {
                      const meta = PHASE_META[phase.type] || PHASE_META.plan_created;
                      const isLast = pIdx === run.phases!.length - 1;
                      return (
                        <motion.div
                          key={phase.id}
                          {...enter({ x: -6, duration: 0.2 })}
                          className="relative flex items-start gap-2 min-w-0 pb-1"
                          data-testid={`run-phase-${phase.type}`}
                        >
                          {/* timeline dot — the newest one glows while running */}
                          <span
                            className={`absolute -left-3.5 top-[3px] grid h-[11px] w-[11px] place-items-center rounded-full bg-brand-bg-code ring-1 ${
                              running && isLast ? 'ring-brand-amber/60' : 'ring-brand-border'
                            }`}
                          >
                            <motion.span
                              className={`h-[5px] w-[5px] rounded-full ${meta.color.replace('text-', 'bg-')}`}
                              animate={running && isLast && !reduceMotion ? { scale: [1, 1.5, 1], opacity: [0.7, 1, 0.7] } : { scale: 1, opacity: 1 }}
                              transition={running && isLast && !reduceMotion ? { duration: 1.2, repeat: Infinity, ease: 'easeInOut' } : undefined}
                            />
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="flex items-center gap-1">
                              <span className={`${meta.color} font-mono text-[9px] shrink-0`}>{meta.icon}</span>
                              <span className="block text-[9px] text-brand-green-soft truncate" title={phase.label}>
                                {phase.label}
                              </span>
                            </span>
                            {phase.detail && (
                              <span className="block text-[8px] text-brand-green-faint truncate pl-3.5" title={phase.detail}>
                                {phase.detail}
                              </span>
                            )}
                          </span>
                        </motion.div>
                      );
                    })}
                  </AnimatePresence>
                </div>
              </div>
            )}

            {/* ADR-34 B-8: evidence entries handed to the parent model */}
            {run.evidence && run.evidence.length > 0 && (
              <div className="space-y-0.5">
                {run.evidence.map((entry, idx) => (
                  <div key={`${entry.tool}-${entry.iteration}-${idx}`} className="flex items-center gap-1.5 min-w-0 text-[8px] text-brand-green-muted font-mono">
                    <FileInput className={`h-2 w-2 shrink-0 ${entry.failed ? 'text-brand-red' : 'text-brand-green-faint'}`} />
                    <span className="truncate min-w-0">evidence ← {entry.tool}</span>
                    <span className="text-brand-green-faint shrink-0">({entry.evidenceChars} chars)</span>
                    {entry.failed && <span className="text-brand-red shrink-0">failed</span>}
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
                    {...enter({ x: -6, duration: 0.18 })}
                    className="flex items-center gap-1.5 min-w-0 rounded bg-brand-bg-base px-2 py-1"
                  >
                    <span className={`shrink-0 ${tool.status === 'failed' ? 'text-brand-red' : isActiveToolStatus(tool.status) ? 'text-brand-amber' : 'text-brand-green'}`}>
                      {isActiveToolStatus(tool.status) ? <Loader2 className="h-2.5 w-2.5 animate-spin" /> : tool.status === 'failed' ? <XCircle className="h-2.5 w-2.5" /> : <CheckCircle2 className="h-2.5 w-2.5" />}
                    </span>
                    <span className="text-[9px] text-brand-green-soft truncate min-w-0 flex-1" title={tool.input}>
                      {toolLabel(tool)}
                    </span>
                    {tool.duration !== undefined && <span className="ml-auto text-[8px] text-brand-green-faint font-mono shrink-0 whitespace-nowrap">{formatLatency(tool.duration)}</span>}
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
          <div className="text-[9px] text-brand-green-muted">Turns</div>
          <div className="text-[13px] text-brand-green-soft font-mono">{roots.length}</div>
        </div>
        <div className="rounded border border-brand-border bg-brand-bg-code px-2 py-1.5">
          <div className="text-[9px] text-brand-green-muted">Tool steps</div>
          <div className="text-[13px] text-brand-green-soft font-mono">{totalTools}</div>
        </div>
      </div>

      <div className="space-y-2">
        <AnimatePresence initial={false}>
          {roots.map((root, i) => (
            <RunNode key={root.id} run={root} children={childMap.get(root.id) ?? []} childMap={childMap} depth={0} turnIndex={i + 1} isLast={i === roots.length - 1} />
          ))}
        </AnimatePresence>
      </div>

      <div className="flex items-center gap-2 text-[9px] text-brand-green-faint border-t border-brand-border pt-2">
        <Clock className="h-2.5 w-2.5" /> Child agents receive an isolated task and report back to the parent.
      </div>
    </div>
  );
}
