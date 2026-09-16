/**
 * TurnTimeline — a glanceable "where did this turn's time go?" strip.
 *
 * LocalMind already streams rich per-turn timing (thinking duration, each
 * tool's duration, and the answer-stream span) but it was scattered across the
 * thinking block, the tool cards, and the stats corner — so understanding a
 * slow turn meant summing numbers by hand (the owner literally did "47.6 + 12 +
 * 12 + 2.1 = 73.7s" to find a bug). This turns that mental math into one
 * proportional bar: thinking vs each tool vs the answer, colored and labeled,
 * exact ms on hover.
 *
 * It is the visible payoff of the thinking-timer fix: the bar
 * is only honest because thinking time no longer overlaps tool time, so the
 * segments compose without double-counting.
 *
 * Each TOOL segment is clickable — it jumps to (and flashes) that tool's chip
 * below, so the bar doubles as a table of contents for the turn.
 *
 * Fed entirely by existing message data (thinkMs + toolCalls[].duration +
 * answerMs) — no new backend plumbing. Renders nothing until at least two
 * measured segments exist.
 */
import { useMemo } from 'react';

import type { ToolCall } from '@/types';

interface Segment {
  key: string;
  kind: 'thinking' | 'tool' | 'answer';
  label: string;
  ms: number;
  failed: boolean;
  toolId?: string;
}

function fmtDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 10000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms / 1000)}s`;
}

interface TurnTimelineProps {
  thinkMs?: number;
  answerMs?: number;
  toolCalls?: ToolCall[];
  /** Jump to a tool's card below when its segment is clicked. */
  onFocusTool?: (toolId: string) => void;
  className?: string;
}

export function TurnTimeline({ thinkMs, answerMs, toolCalls, onFocusTool, className }: TurnTimelineProps) {
  const segments = useMemo<Segment[]>(() => {
    const out: Segment[] = [];
    if (typeof thinkMs === 'number' && thinkMs > 0) {
      out.push({ key: 'thinking', kind: 'thinking', label: 'Thinking', ms: thinkMs, failed: false });
    }
    for (const tc of toolCalls ?? []) {
      if (typeof tc.duration === 'number' && tc.duration > 0) {
        out.push({
          key: tc.id,
          kind: 'tool',
          label: tc.label || tc.name || 'tool',
          ms: tc.duration,
          failed: tc.status === 'failed',
          toolId: tc.id,
        });
      }
    }
    if (typeof answerMs === 'number' && answerMs > 0) {
      out.push({ key: 'answer', kind: 'answer', label: 'Answer', ms: answerMs, failed: false });
    }
    return out;
  }, [thinkMs, answerMs, toolCalls]);

  const total = segments.reduce((sum, s) => sum + s.ms, 0);

  // Nothing measured, or a trivial single-segment turn — the bar would be one
  // block, so skip it.
  if (segments.length < 2 || total <= 0) return null;

  const colorFor = (s: Segment) =>
    s.kind === 'thinking'
      ? 'bg-brand-purple'
      : s.kind === 'answer'
        ? 'bg-brand-blue'
        : s.failed
          ? 'bg-brand-red'
          : 'bg-brand-green';

  const clickable = (s: Segment): boolean => !!(s.kind === 'tool' && s.toolId && onFocusTool);

  return (
    <div className={`my-1.5 select-none ${className ?? ''}`} data-testid="turn-timeline">
      <div className="mb-1 flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-wider text-brand-green-faint">
          Where the time went
        </span>
        <span className="font-mono text-[10px] text-brand-green-muted">{fmtDuration(total)}</span>
      </div>

      {/* Proportional segmented bar */}
      <div
        className="flex h-2 w-full overflow-hidden rounded-full border border-brand-border/50 bg-brand-bg-dark"
        role="img"
        aria-label={`Turn timeline: ${segments.map((s) => `${s.label} ${fmtDuration(s.ms)}`).join(', ')}`}
      >
        {segments.map((s) => {
          const pct = (s.ms / total) * 100;
          const base = `h-full ${colorFor(s)} transition-[width,filter] duration-300`;
          const style = { width: `${Math.max(pct, 2)}%` };
          const title = `${s.label} — ${fmtDuration(s.ms)} (${pct.toFixed(0)}%)${clickable(s) ? ' · click to jump' : ''}`;
          return clickable(s) ? (
            <button
              key={s.key}
              type="button"
              className={`${base} cursor-pointer hover:brightness-125 focus:outline-none focus-visible:brightness-150`}
              style={style}
              title={title}
              aria-label={title}
              onClick={() => onFocusTool!(s.toolId!)}
            />
          ) : (
            <div key={s.key} className={base} style={style} title={title} />
          );
        })}
      </div>

      {/* Legend — dot + label + duration; tool entries jump to the card */}
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5">
        {segments.map((s) => {
          const content = (
            <>
              <span className={`inline-block h-1.5 w-1.5 rounded-full ${colorFor(s)}`} />
              <span className="max-w-[140px] truncate">{s.label}</span>
              <span className="text-brand-green-faint">{fmtDuration(s.ms)}</span>
            </>
          );
          return clickable(s) ? (
            <button
              key={s.key}
              type="button"
              className="inline-flex items-center gap-1 font-mono text-[10px] text-brand-green-soft hover:text-brand-green-bright focus:outline-none focus-visible:underline"
              onClick={() => onFocusTool!(s.toolId!)}
              title="Jump to this tool below"
            >
              {content}
            </button>
          ) : (
            <span key={s.key} className="inline-flex items-center gap-1 font-mono text-[10px] text-brand-green-soft">
              {content}
            </span>
          );
        })}
      </div>
    </div>
  );
}
