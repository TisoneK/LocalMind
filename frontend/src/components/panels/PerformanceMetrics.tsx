'use client';

import { Activity, Clock, Hash } from 'lucide-react';
import { formatLatency } from '@/lib/localmind/progress';

interface PerformanceMetricsType {
  tokensPerSecond?: number;
  latency?: number;
  totalTokens?: number;
  promptTokens?: number;
  completionTokens?: number;
}

interface PerformanceMetricsProps {
  metrics: PerformanceMetricsType;
  /** SSE-driven lastMetrics — used to detect whether we have real data */
  lastMetrics?: PerformanceMetricsType | null;
  /** Wall-clock duration of the current/most recent request */
  elapsedMs?: number;
}

/** Display "—" for undefined/null, otherwise format the number (including 0) */
function fmtTok(v: number | undefined): string {
  if (v === undefined || v === null) return '—';
  return v.toLocaleString();
}

export function PerformanceMetrics({ metrics, lastMetrics, elapsedMs = 0 }: PerformanceMetricsProps) {
  // Prefer lastMetrics (SSE-driven, instant) when it has real data,
  // otherwise fall back to the polled metrics.
  const source = (lastMetrics && ((lastMetrics.totalTokens || 0) > 0 || (lastMetrics.latency || 0) > 0))
    ? lastMetrics
    : metrics;

  const tokensPerSecond = source.tokensPerSecond ?? 0;
  // The server only knows final latency after completion. While a request is
  // active, the hook's wall clock keeps this value moving through dispatcher,
  // tool execution, and generation instead of leaving the footer frozen.
  const latency = elapsedMs > 0 ? elapsedMs : (source.latency ?? 0);
  const totalTokens = source.totalTokens ?? 0;
  const promptTokens = source.promptTokens ?? 0;
  const completionTokens = source.completionTokens ?? 0;

  // Show prompt/completion breakdown when ANY token data exists
  const hasTokenBreakdown = totalTokens > 0 || promptTokens > 0 || completionTokens > 0;

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3 py-1.5 bg-brand-bg-dark border-t border-brand-border min-w-0">
      <div className="flex items-center gap-1.5">
        <Activity className="h-3 w-3 text-brand-green shrink-0" />
        <span className="text-[9px] text-brand-green-muted uppercase tracking-wider shrink-0" title="Tokens per second">Speed</span>
        <span className="text-[11px] text-brand-green-soft font-mono font-medium whitespace-nowrap">
          {tokensPerSecond > 0 ? `${tokensPerSecond} tok/s` : '—'}
        </span>
      </div>

      <div className="flex items-center gap-1.5">
        <Clock className="h-3 w-3 text-brand-amber shrink-0" />
        <span className="text-[9px] text-brand-green-muted uppercase tracking-wider shrink-0" title="Response latency">Latency</span>
        <span className="text-[11px] text-brand-green-soft font-mono font-medium whitespace-nowrap">
          {latency > 0 ? formatLatency(latency) : '—'}
        </span>
      </div>

      <div className="flex items-center gap-1.5">
        <Hash className="h-3 w-3 text-brand-green-muted shrink-0" />
        <span className="text-[9px] text-brand-green-muted uppercase tracking-wider shrink-0" title="Total tokens used">Tokens</span>
        <span className="text-[11px] text-brand-green-soft font-mono font-medium whitespace-nowrap">
          {totalTokens > 0 ? totalTokens.toLocaleString() : '—'}
        </span>
      </div>

      {hasTokenBreakdown && (
        <div className="flex items-center gap-2 shrink-0">
          <div className="flex items-center gap-1">
            <span className="text-[9px] text-brand-green-muted">prompt:</span>
            <span className="text-[10px] text-brand-green-soft font-mono">{fmtTok(promptTokens)}</span>
          </div>
          <div className="flex items-center gap-1">
            <span className="text-[9px] text-brand-green-muted">completion:</span>
            <span className="text-[10px] text-brand-green-soft font-mono">{fmtTok(completionTokens)}</span>
          </div>
        </div>
      )}
    </div>
  );
}
