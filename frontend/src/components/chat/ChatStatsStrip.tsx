/**
 * The Harness-style conversation reading under the composer.
 *
 * Left: what the agent is doing right now ("Deep diving for 4m 16s…" while a
 * turn is open; the keyboard hint at rest). Right: the durable turn/step
 * count with speed, token total and cache hit — the same reading the Harness
 * app's stats strip carries. Turns are requests; steps are model iterations.
 */

import type { PerformanceMetrics, SessionStats } from '@/types';
import {
  buildSessionReading,
  formatCompactTokens,
  formatDiveDuration,
} from '@/lib/localmind/sessionReading';

interface ChatStatsStripProps {
  stats?: SessionStats | null;
  /** The open turn's provider metrics while streaming. */
  live?: PerformanceMetrics | null;
  isStreaming: boolean;
  /** Wall time of the open turn (ms). */
  elapsedMs?: number;
}

function plural(count: number, one: string): string {
  return count === 1 ? one : `${one}s`;
}

export function ChatStatsStrip({ stats, live, isStreaming, elapsedMs = 0 }: ChatStatsStripProps) {
  const reading = buildSessionReading(stats, live, isStreaming);

  return (
    <div
      className="mx-auto flex w-full max-w-3xl items-center justify-between gap-4 px-4 pb-2 text-[10.5px] text-brand-green-muted"
      data-testid="chat-stats-strip"
    >
      <div className="min-w-0 truncate" aria-live={isStreaming ? 'polite' : undefined}>
        {isStreaming ? (
          <span className="inline-flex items-center gap-1.5 text-brand-green-soft" data-testid="deep-diving">
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand-green opacity-60" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-brand-green" />
            </span>
            Deep diving for {formatDiveDuration(elapsedMs)}…
          </span>
        ) : (
          <span>
            <kbd className="rounded bg-brand-border px-1 py-0.5">Enter</kbd> to send
            <span className="px-1.5">·</span>
            <kbd className="rounded bg-brand-border px-1 py-0.5">Shift</kbd>
            {' '}new line
          </span>
        )}
      </div>

      <div className="flex shrink-0 items-center gap-3 tabular-nums" data-testid="chat-stats-reading">
        {reading.turns > 0 && (
          <span
            title="Turns are your requests. Steps are the model/tool iterations inside them — a plan checklist is not a step."
          >
            {reading.turns} {plural(reading.turns, 'turn')}
            <span className="px-1.5 text-brand-green-faint">·</span>
            {reading.steps} {plural(reading.steps, 'step')}
          </span>
        )}
        {reading.tokensPerSecond !== null && (
          <span title="Provider output tokens per second of decode time">
            {reading.tokensPerSecond} tok/s
          </span>
        )}
        {reading.totalTokens > 0 && (
          <span title="Billed input + output tokens across this conversation">
            {formatCompactTokens(reading.totalTokens)} tok
          </span>
        )}
        {reading.cacheHitPct !== null && reading.cacheHitPct > 0 && (
          <span title="Share of prompt-side input served from the provider's prompt cache">
            Cache hit {reading.cacheHitPct}%
          </span>
        )}
      </div>
    </div>
  );
}
