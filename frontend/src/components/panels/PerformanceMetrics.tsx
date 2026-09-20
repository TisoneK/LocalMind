'use client';

import { Activity, Clock, Hash } from 'lucide-react';
import { formatLatency, formatTokens } from '@/lib/localmind/progress';
import { TONE_CLASS, cacheTone, latencyTone, median, speedTone } from '@/lib/localmind/metricTone';
import type { SessionStats } from '@/types';

interface PerformanceMetricsType {
  tokensPerSecond?: number;
  latency?: number;
  totalTokens?: number;
  promptTokens?: number;
  completionTokens?: number;
  /** Provider-reported cache-hit input tokens (P0 Context Engineering Step 1). */
  cachedTokens?: number;
  /** LLM calls that reported usage this turn. */
  llmCalls?: number;
}

interface PerformanceMetricsProps {
  metrics: PerformanceMetricsType;
  /** SSE-driven lastMetrics — used to detect whether we have real data */
  lastMetrics?: PerformanceMetricsType | null;
  /** Wall-clock duration of the current/most recent request */
  elapsedMs?: number;
  /** Whether a request is in flight (drives live vs. session display) */
  isStreaming?: boolean;
  /** Cumulative per-chat totals (stats split): the corner answers \"how is\n   *  this session doing overall\" — summed tokens, throughput weighted by\n   *  output tokens, average turn latency. Per-message stats stay under each\n   *  bubble. When absent (no turns yet), falls back to the last-turn shape. */
  sessionStats?: SessionStats | null;
}

export function PerformanceMetrics({
  metrics,
  lastMetrics,
  elapsedMs = 0,
  isStreaming = false,
  sessionStats,
}: PerformanceMetricsProps) {
  // Live per-turn source (SSE-driven, instant) — used only while a request
  // is actually running. At rest the corner shows the session aggregates.
  const live = (lastMetrics && ((lastMetrics.totalTokens || 0) > 0 || (lastMetrics.latency || 0) > 0))
    ? lastMetrics
    : metrics;

  // ── Session aggregates ────────────────
  const sessionPrompt = sessionStats?.promptTokens ?? 0;
  const sessionCompletion = sessionStats?.completionTokens ?? 0;
  const sessionTurnCount = sessionStats?.turnCount ?? 0;
  // Weighted speed: total output tokens ÷ total generation time — a fast
  // 5-token reply and a slow 2,000-token reply are weighted by what they
  // actually produced, not averaged equally.
  const sessionSpeed = sessionStats && sessionStats.genTimeMs > 0
    ? Math.round((sessionStats.completionTokens / sessionStats.genTimeMs) * 1000 * 100) / 100
    : 0;
  const sessionTotalLatency = sessionStats?.latencyMs ?? 0;
  const sessionAvgLatency = sessionTurnCount > 0 && sessionTotalLatency > 0
    ? sessionTotalLatency / sessionTurnCount
    : 0;
  // The middle turn, not the mean: one 60 s agent run among quick replies makes an average that
  // describes none of them. Falls back to the mean when per-turn values are not known.
  const turnLatencies = sessionStats?.turnLatencies ?? [];
  const sessionTypicalLatency = median(turnLatencies) || sessionAvgLatency;
  const slowestTurn = turnLatencies.length ? Math.max(...turnLatencies) : 0;

  const isActive = isStreaming && elapsedMs > 0;
  // While a request is in flight the corner stays live (wall-clock latency,
  // real-time speed, current turn's token estimate on top of the session
  // totals); at rest it reports the session summary.
  const liveTps = live.tokensPerSecond ?? 0;
  const tokensPerSecond = isActive && liveTps > 0 ? liveTps : sessionSpeed;
  const latency = isActive ? elapsedMs : sessionTypicalLatency;
  const completionTokens = sessionCompletion + (isStreaming ? (live.completionTokens || 0) : 0);
  const promptTokens = sessionPrompt + (isStreaming ? (live.promptTokens || 0) : 0);
  const totalTokens = promptTokens + completionTokens;

  // ── Prompt-cache telemetry (P0 Context Engineering Step 1) ────────────
  // The "prompt" number above is what the model READ; much of it was served
  // from the provider's prompt cache at ~10% of the price. cachedTokens is
  // the cache-hit share (last-turn while live, summed across turns at rest).
  const cachedTokens = (sessionStats?.cachedTokens ?? 0) + (isStreaming ? (live.cachedTokens || 0) : 0);
  const llmCalls = (sessionStats?.llmCalls || 0) + (isStreaming ? (live.llmCalls || 0) : 0);
  const cacheHitPct = cachedTokens > 0 && promptTokens > 0
    ? Math.min(100, Math.round((cachedTokens / promptTokens) * 100))
    : 0;
  // Fresh input is billed full price; cached input at ~10% (0.1×). This is
  // the honest "equivalent work" number the single prompt count obscured.
  const equivalentInputTokens = Math.round(promptTokens - cachedTokens * 0.9);

  const hasTokenBreakdown = totalTokens > 0 || sessionTurnCount > 0;

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3 py-1.5 bg-brand-bg-dark border-t border-brand-border min-w-0">
      <div className="flex items-center gap-1.5">
        <Activity className="h-3 w-3 text-brand-green shrink-0" />
        <span
          className="text-[9px] text-brand-green-muted uppercase tracking-wider shrink-0"
          title={'Output speed\nTokens generated per second across this chat.'}
        >
          Speed
        </span>
        <span className={`text-[11px] ${TONE_CLASS[speedTone(tokensPerSecond)]} font-mono font-medium whitespace-nowrap`}>
          {tokensPerSecond > 0 ? `${tokensPerSecond} tok/s` : '—'}
        </span>
      </div>

      <div className="flex items-center gap-1.5">
        <Clock className="h-3 w-3 text-brand-amber shrink-0" />
        <span
          className="text-[9px] text-brand-green-muted uppercase tracking-wider shrink-0"
          title={
            sessionTurnCount > 0
              ? `Typical time per turn (median of ${sessionTurnCount})\nAverage ${formatLatency(sessionAvgLatency)}${slowestTurn > 0 ? ` · slowest ${formatLatency(slowestTurn)}` : ''}\nWhile a reply runs this shows the live clock.`
              : 'Time per turn\nShows once you have a reply.'
          }
        >
          Typical latency
        </span>
        <span className={`text-[11px] ${TONE_CLASS[latencyTone(latency)]} font-mono font-medium whitespace-nowrap`}>
          {latency > 0 ? formatLatency(latency) : '—'}
        </span>
      </div>

      <div className="flex items-center gap-1.5">
        <Hash className="h-3 w-3 text-brand-green-muted shrink-0" />
        <span
          className="text-[9px] text-brand-green-muted uppercase tracking-wider shrink-0"
          title={'Tokens used in this chat\nPrompt + completion, all turns.'}
        >
          Tokens
        </span>
        <span className="text-[11px] text-brand-green-soft font-mono font-medium whitespace-nowrap">
          {totalTokens > 0 ? formatTokens(totalTokens) : '—'}
        </span>
      </div>

      {hasTokenBreakdown && (
        <div className="flex items-center gap-2 shrink-0">
          <div className="flex items-center gap-1">
            <span className="text-[9px] text-brand-green-muted">prompt:</span>
            <span className="text-[10px] text-brand-blue font-mono">{formatTokens(promptTokens)}</span>
          </div>
          {cachedTokens > 0 && (
            <div
              className="flex items-center gap-1"
              title={`Prompt cache\n${cacheHitPct}% of input was served from the provider's cache, at about 10% of the price.`}
                        >
              <span className="text-[9px] text-brand-green-muted">cached:</span>
              <span className={`text-[10px] ${TONE_CLASS[cacheTone(cacheHitPct)]} font-mono`}>
                {formatTokens(cachedTokens)} ({cacheHitPct}%)
              </span>
            </div>
          )}
          <div className="flex items-center gap-1">
            <span className="text-[9px] text-brand-green-muted">completion:</span>
            <span className="text-[10px] text-brand-purple font-mono">{formatTokens(completionTokens)}</span>
          </div>
          {llmCalls > 0 && (
            <div
              className="flex items-center gap-1"
              title={`${llmCalls} model call${llmCalls === 1 ? '' : 's'}\nEach agent step re-sends the conversation, so real input is larger than the prompt count.`}
            >
              <span className="text-[9px] text-brand-green-muted">calls:</span>
              <span className="text-[10px] text-brand-green-soft font-mono">{llmCalls}</span>
            </div>
          )}
        </div>
      )}

      {/* Turns chip — makes the session-scope of the corner explicit and
          distinguishes it from the per-message lines under each bubble. */}
      {sessionTurnCount > 0 && (
        <span
          className="shrink-0 text-[9px] text-brand-green-faint font-mono border border-brand-border rounded px-1 py-px"
          title={`${sessionTurnCount} assistant turn${sessionTurnCount === 1 ? '' : 's'} this session`}
        >
          {sessionTurnCount} turn{sessionTurnCount === 1 ? '' : 's'}
        </span>
      )}
    </div>
  );
}
