'use client';

import { Activity, Clock, Hash } from 'lucide-react';

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
}

/** Display "—" for zero/undefined, otherwise format the number */
function fmtTok(v: number | undefined): string {
  if (v === undefined || v === null || v === 0) return '—';
  return v.toLocaleString();
}

export function PerformanceMetrics({ metrics, lastMetrics }: PerformanceMetricsProps) {
  // Prefer lastMetrics (SSE-driven, instant) when it has real data,
  // otherwise fall back to the polled metrics.
  const source = (lastMetrics && ((lastMetrics.totalTokens || 0) > 0 || (lastMetrics.latency || 0) > 0))
    ? lastMetrics
    : metrics;

  const tokensPerSecond = source.tokensPerSecond ?? 0;
  const latency = source.latency ?? 0;
  const totalTokens = source.totalTokens ?? 0;
  const promptTokens = source.promptTokens ?? 0;
  const completionTokens = source.completionTokens ?? 0;

  // Show prompt/completion breakdown when ANY token data exists
  const hasTokenBreakdown = totalTokens > 0 || promptTokens > 0 || completionTokens > 0;

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3 py-1.5 bg-[#080d08] border-t border-[#1a2a1a] min-w-0">
      <div className="flex items-center gap-1.5">
        <Activity className="h-3 w-3 text-[#39d353] shrink-0" />
        <span className="text-[9px] text-[#8ab08a] uppercase tracking-wider shrink-0" title="Tokens per second">Speed</span>
        <span className="text-[11px] text-[#d4e8d4] font-mono font-medium whitespace-nowrap">
          {tokensPerSecond > 0 ? `${tokensPerSecond} tok/s` : '—'}
        </span>
      </div>

      <div className="flex items-center gap-1.5">
        <Clock className="h-3 w-3 text-[#e8a420] shrink-0" />
        <span className="text-[9px] text-[#8ab08a] uppercase tracking-wider shrink-0" title="Response latency">Latency</span>
        <span className="text-[11px] text-[#d4e8d4] font-mono font-medium whitespace-nowrap">
          {latency > 0 ? (latency >= 1000 ? `${(latency / 1000).toFixed(1)}s` : `${Math.round(latency)}ms`) : '—'}
        </span>
      </div>

      <div className="flex items-center gap-1.5">
        <Hash className="h-3 w-3 text-[#8ab08a] shrink-0" />
        <span className="text-[9px] text-[#8ab08a] uppercase tracking-wider shrink-0" title="Total tokens used">Tokens</span>
        <span className="text-[11px] text-[#d4e8d4] font-mono font-medium whitespace-nowrap">
          {totalTokens > 0 ? totalTokens.toLocaleString() : '—'}
        </span>
      </div>

      {hasTokenBreakdown && (
        <div className="flex items-center gap-2 shrink-0">
          <div className="flex items-center gap-1">
            <span className="text-[9px] text-[#8ab08a]">prompt:</span>
            <span className="text-[10px] text-[#d4e8d4] font-mono">{fmtTok(promptTokens)}</span>
          </div>
          <div className="flex items-center gap-1">
            <span className="text-[9px] text-[#8ab08a]">completion:</span>
            <span className="text-[10px] text-[#d4e8d4] font-mono">{fmtTok(completionTokens)}</span>
          </div>
        </div>
      )}
    </div>
  );
}
