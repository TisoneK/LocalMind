/**
 * TurnView — the agent's whole turn as one live activity.
 *
 * Replaces the stacked thinking block, phase strip, timeline bar and tool chips
 * with a single group: while the agent works it reads "Working · 23s" with a
 * row per step (tools, checkpoints, sub-agents, parallel batches); when it
 * finishes it folds to a one-line summary the user can reopen.
 */

import { memo, useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import {
  AlertTriangle,
  Bot,
  Brain,
  Check,
  ChevronRight,
  Circle,
  FileEdit,
  FileSearch,
  Globe,
  Loader2,
  Search,
  Terminal,
  X,
} from 'lucide-react';
import { buildTurn, type StepState, type TurnStep } from '@/lib/localmind/turnTimeline';
import { useEnterMotion } from '@/lib/localmind/motion';
import { formatLatency } from '@/lib/localmind/progress';
import type { ChatMessage, TodoItem } from '@/types';
import { MarkdownContent } from '@/components/shared/MarkdownContent';

const TOOL_ICONS: Record<string, typeof Terminal> = {
  file_write: FileEdit,
  edit_file: FileEdit,
  file_read: FileSearch,
  file_task: FileSearch,
  dir_explorer: FileSearch,
  grep: Search,
  web_search: Globe,
  memory_op: Brain,
};

function StateIcon({ state, className = 'h-3.5 w-3.5' }: { state: StepState; className?: string }) {
  if (state === 'running') return <Loader2 className={`${className} animate-spin text-brand-amber`} aria-label="running" />;
  if (state === 'failed') return <X className={`${className} text-red-400`} aria-label="failed" />;
  if (state === 'pending') return <Circle className={`${className} text-brand-green-muted`} aria-label="pending" />;
  return <Check className={`${className} text-brand-green`} aria-label="done" />;
}

/** Whole seconds since `active` became true; freezes when it turns false. */
function useElapsedSeconds(active: boolean): number {
  const [start] = useState(() => Date.now());
  const [now, setNow] = useState(start);
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [active]);
  return Math.max(0, Math.round((now - start) / 1000));
}

/** A running row ticks its own seconds; a finished row shows the recorded duration. */
function RowClock({ step }: { step: TurnStep }) {
  const live = useElapsedSeconds(step.state === 'running' && !step.durationMs);
  if (step.durationMs) return <>{formatLatency(step.durationMs)}</>;
  return step.state === 'running' ? <>{live}s</> : null;
}

function StepRow({ step, depth = 0 }: { step: TurnStep; depth?: number }) {
  const { enter } = useEnterMotion();
  // A failed step opens itself: the error is the thing the user needs to see.
  const [pinned, setPinned] = useState<boolean | null>(null);
  const open = pinned ?? step.state === 'failed';
  const setOpen = (fn: (o: boolean) => boolean) => setPinned(fn(open));

  if (step.kind === 'narration') {
    return (
      <motion.div {...enter({ y: 4 })} className="text-[12px] leading-relaxed text-brand-green-soft py-1">
        <MarkdownContent text={step.label} />
      </motion.div>
    );
  }

  if (step.kind === 'checkpoint') {
    const warn = step.tone === 'warn';
    const color = step.state === 'failed' ? 'text-red-300' : warn ? 'text-brand-amber' : 'text-brand-green-soft';
    return (
      <motion.div {...enter({ x: -4 })} className="flex items-start gap-2 px-1 py-1 text-[11.5px]">
        {step.state === 'failed' ? (
          <X className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-400" aria-label="failed" />
        ) : warn ? (
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand-amber" aria-label="replanning" />
        ) : (
          <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand-green" aria-label="verified" />
        )}
        <div className="min-w-0">
          <div className={color}>{step.label}</div>
          {step.detail && <div className="text-[10.5px] leading-snug text-brand-green-muted">{step.detail}</div>}
        </div>
      </motion.div>
    );
  }

  const nested = step.kind === 'agent' || step.kind === 'parallel';
  const expandable = nested || !!step.detail || !!step.tool?.output || !!step.tool?.error;
  const Icon =
    step.kind === 'agent' ? Bot : step.kind === 'thought' ? Brain : TOOL_ICONS[step.tool?.name ?? ''] ?? Terminal;
  // Nested groups start open while running so parallel work is visible without a click.
  const isOpen = nested ? open || step.state === 'running' : open;

  return (
    <motion.div {...enter({ x: -4 })} className="min-w-0">
      <button
        type="button"
        disabled={!expandable}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={expandable ? isOpen : undefined}
        className={`flex w-full items-center gap-2 py-1 text-left text-[11.5px] hover:bg-white/[0.03] rounded px-1 disabled:cursor-default ${
          step.state === 'running' ? 'bg-brand-amber/[0.04]' : ''
        }`}
      >
        <StateIcon state={step.state} />
        <Icon className="h-3 w-3 shrink-0 text-brand-green-muted" aria-hidden />
        <span className={`min-w-0 truncate ${step.state === 'failed' ? 'text-red-300' : 'text-brand-green'}`} title={step.label}>
          {step.label}
        </span>
        {step.kind === 'tool' && step.detail && (
          <span className="min-w-0 shrink-[4] truncate font-mono text-[10.5px] text-brand-green-muted">{step.detail}</span>
        )}
        <span className="ml-auto flex shrink-0 items-center gap-1.5 text-[10px] text-brand-green-muted">
          <RowClock step={step} />
          {expandable && (
            <ChevronRight className={`h-3 w-3 transition-transform ${isOpen ? 'rotate-90' : ''}`} aria-hidden />
          )}
        </span>
      </button>

      {isOpen && (
        <div className="ml-[7px] border-l border-white/10 pl-3">
          {nested ? (
            <>
              {step.detail && <div className="py-0.5 text-[10.5px] text-brand-green-muted">{step.detail}</div>}
              {step.children?.map((c) => <StepRow key={c.id} step={c} depth={depth + 1} />)}
            </>
          ) : (
            <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words py-1 font-mono text-[10.5px] text-brand-green-soft">
              {step.tool?.error || step.tool?.output || step.detail}
            </pre>
          )}
        </div>
      )}
    </motion.div>
  );
}

interface TurnViewProps {
  message: Pick<
    ChatMessage,
    'acknowledgement' | 'thinking' | 'thinkMs' | 'toolCalls' | 'agentPhases' | 'agentRuns' | 'statusText'
  >;
  todos?: TodoItem[];
  isStreaming?: boolean;
}

/** Indeterminate sweep along the top edge — the "something is happening" heartbeat. */
function Shimmer() {
  const { reduce } = useEnterMotion();
  if (reduce) return <div className="h-px bg-brand-amber/40" aria-hidden />;
  return (
    <div className="relative h-px overflow-hidden bg-white/5" aria-hidden>
      <motion.div
        className="absolute inset-y-0 w-1/3 bg-gradient-to-r from-transparent via-brand-amber to-transparent"
        initial={{ x: '-100%' }}
        animate={{ x: '300%' }}
        transition={{ duration: 1.6, ease: 'easeInOut', repeat: Infinity }}
      />
    </div>
  );
}

/** One segment per plan item — done / running / pending at a glance. */
function PlanTrack({ items }: { items: { id: string; label: string; state: StepState }[] }) {
  const tone: Record<StepState, string> = {
    done: 'bg-brand-green',
    running: 'bg-brand-amber animate-pulse',
    failed: 'bg-red-400',
    pending: 'bg-white/10',
  };
  return (
    <div className="flex gap-1 px-2.5 pb-2" role="list" aria-label="Plan progress">
      {items.map((i) => (
        <div key={i.id} role="listitem" title={i.label} aria-label={`${i.label}: ${i.state}`} className={`h-1 flex-1 rounded-full ${tone[i.state]}`} />
      ))}
    </div>
  );
}

export const TurnView = memo(function TurnView({ message, todos, isStreaming }: TurnViewProps) {
  const turn = buildTurn(message, { todos, isStreaming });
  const running = turn.state === 'running';
  const elapsed = useElapsedSeconds(running);
  // null = follow the turn (open while running, folded when done); a click pins it.
  const [pinned, setPinned] = useState<boolean | null>(null);
  const open = pinned ?? running;

  // Narration is the agent talking to the user — it stays in view whether or not
  // the work underneath is folded. Everything else is work and can fold.
  const narration = turn.steps.filter((s) => s.kind === 'narration');
  const work = turn.steps.filter((s) => s.kind !== 'narration');

  if (turn.steps.length === 0 && !running) return null;

  const title = running ? `Working · ${elapsed}s` : turn.summary || 'Done';
  const sub = running ? turn.activeLabel : '';
  const failed = !running && turn.counts.failed > 0;

  return (
    <div data-testid="turn-view" data-state={turn.state}>
      {narration.map((s) => (
        <StepRow key={s.id} step={s} />
      ))}
      {(work.length > 0 || running) && (
        <div
          className={`my-1.5 overflow-hidden rounded-lg border bg-white/[0.02] ${
            running ? 'border-brand-amber/25' : failed ? 'border-red-400/25' : 'border-white/10'
          }`}
        >
          {running && <Shimmer />}
          <button
            type="button"
            onClick={() => setPinned(!open)}
            aria-expanded={open}
            className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[12px]"
          >
            <ChevronRight className={`h-3.5 w-3.5 text-brand-green-muted transition-transform ${open ? 'rotate-90' : ''}`} aria-hidden />
            <StateIcon state={failed ? 'failed' : turn.state} />
            <span className="shrink-0 whitespace-nowrap font-medium text-brand-green">{title}</span>
            {sub && <span className="min-w-0 truncate text-brand-green-muted">· {sub}</span>}
            {turn.plan && turn.plan.total > 1 && (
              <span
                className="ml-auto shrink-0 whitespace-nowrap rounded-full bg-white/[0.06] px-2 py-0.5 text-[10px] text-brand-green-soft"
                title={turn.plan.items[turn.plan.currentIndex]?.label}
              >
                {turn.plan.done === turn.plan.total
                  ? `${turn.plan.total}/${turn.plan.total} steps`
                  : `Step ${turn.plan.currentIndex + 1}/${turn.plan.total}`}
              </span>
            )}
          </button>
          {turn.plan && turn.plan.total > 1 && <PlanTrack items={turn.plan.items} />}
          {open && (
            <div className="px-2.5 pb-2" role="list" aria-label="Agent activity">
              {work.map((s) => (
                <StepRow key={s.id} step={s} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
});
