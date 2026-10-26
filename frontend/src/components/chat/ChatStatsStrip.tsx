/**
 * The conversation reading under the composer.
 *
 * Left: what the agent is doing right now ("Deep diving for 4m 16s…" while a
 * turn is open; the keyboard hint at rest) plus the durable goal's round
 * meter when one is current. Right: the durable turn/step count with speed,
 * token total and cache hit. Turns are requests; steps are model iterations.
 */

import type { GoalState, PerformanceMetrics, SessionStats } from '@/types';
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
  /** The chat's durable goal — drives the round meter while one is current. */
  goal?: GoalState | null;
}

function plural(count: number, one: string): string {
  return count === 1 ? one : `${one}s`;
}

export function ChatStatsStrip({
  stats,
  live,
  isStreaming,
  elapsedMs = 0,
  goal,
}: ChatStatsStripProps) {
  const reading = buildSessionReading(stats, live, isStreaming);
  // `complete` settles back to the resting strip: the meter is for work that
  // is still current, not an achievement badge.
  const showGoal = Boolean(goal && goal.phase !== 'complete');
  const goalTitle = goal
    ? goal.phase === 'blocked' && goal.blockedReason
      ? `${goal.objective} — ${goal.blockedReason}`
      : goal.armed
        ? goal.objective
        : `${goal.objective} — continuation is disarmed until the goal is resumed`
    : '';

  return (
    <div
      className="mx-auto flex w-full max-w-3xl items-center justify-between gap-4 px-4 pb-2 text-[10.5px] text-brand-green-muted"
      data-testid="chat-stats-strip"
    >
      <div className="flex min-w-0 items-center gap-2" aria-live={isStreaming ? 'polite' : undefined}>
        {showGoal && goal && (
          <span
            className="inline-flex shrink-0 items-center rounded bg-brand-green/10 px-1.5 py-0.5 text-brand-green-soft"
            title={goalTitle}
            data-testid="goal-round-meter"
          >
            {goal.phase === 'active' && (
              <>
                Goal {goal.roundsStarted}/{goal.maxGoalRounds}
                {!goal.armed && <span className="pl-1 text-brand-green-faint">· stopped</span>}
              </>
            )}
            {goal.phase === 'paused' && 'Goal paused'}
            {goal.phase === 'blocked' && 'Goal blocked'}
          </span>
        )}
        <div className="min-w-0 truncate">
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
