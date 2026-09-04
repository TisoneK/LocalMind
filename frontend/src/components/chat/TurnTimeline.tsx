/**
 * TurnTimeline — a glanceable "where did this turn's time go?" strip.
 *
 * LocalMind already streams rich per-turn timing (thinking duration + each
 * tool's duration), but it was scattered across the thinking block, the tool
 * cards, and the stats corner — so understanding a slow turn meant summing
 * numbers by hand (the owner literally did "47.6 + 12 + 12 + 2.1 = 73.7s" to
 * find a bug). This turns that mental math into one proportional bar: thinking
 * vs each tool, colored and labeled, with exact ms on hover.
 *
 * It is the visible payoff of the thinking-timer fix (B-2026-09-04-4): the bar
 * is only honest because thinking time no longer overlaps tool time, so the
 * segments compose without double-counting.
 *
 * Fed entirely by existing message data (thinkMs + toolCalls[].duration) — no
 * new backend plumbing. Renders live (segments appear as tools complete) and
 * on the finished turn alike; renders nothing until at least one measured
 * segment exists.
 */
import { useMemo } from 'react';

import type { ToolCall } from '@/types';

interface Segment {
  key: string;
  kind: 'thinking' | 'tool';
  label: string;
  ms: number;
  failed: boolean;
}

function fmtDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 10000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms / 1000)}s`;
}

interface TurnTimelineProps {
  thinkMs?: number;
  toolCalls?: ToolCall[];
  className?: string;
}

export function TurnTimeline({ thinkMs, toolCalls, className }: TurnTimelineProps) {
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
        });
      }
    }
    return out;
  }, [thinkMs, toolCalls]);

  const total = segments.reduce((sum, s) => sum + s.ms, 0);

  // Nothing measured yet, or a trivial single-segment turn (e.g. a plain chat
  // reply with no tools) — the bar would just be one block, so skip it.
  if (segments.length < 2 || total <= 0) return null;

  const colorFor = (s: Segment) =>
    s.kind === 'thinking' ? 'bg-brand-purple' : s.failed ? 'bg-brand-red' : 'bg-brand-green';

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
          return (
            <div
              key={s.key}
              className={`h-full ${colorFor(s)} ${s.failed ? 'opacity-90' : ''} transition-[width] duration-300`}
              style={{ width: `${Math.max(pct, 2)}%` }}
              title={`${s.label} — ${fmtDuration(s.ms)} (${pct.toFixed(0)}%)`}
            />
          );
        })}
      </div>

      {/* Legend — dot + label + duration for each segment */}
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5">
        {segments.map((s) => (
          <span
            key={s.key}
            className="inline-flex items-center gap-1 font-mono text-[10px] text-brand-green-soft"
          >
            <span className={`inline-block h-1.5 w-1.5 rounded-full ${colorFor(s)}`} />
            <span className="max-w-[140px] truncate">{s.label}</span>
            <span className="text-brand-green-faint">{fmtDuration(s.ms)}</span>
          </span>
        ))}
      </div>
    </div>
  );
}
