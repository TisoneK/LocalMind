/**
 * The conversation's turn/step reading — the numbers under the composer.
 *
 * The turn/step contract: a TURN is one user request; a STEP is one entered
 * model iteration inside it (tool calls happen inside a step, they do not add
 * steps). The session totals are durable
 * (SessionStats); the open turn's live figures come from the streaming
 * metrics, so the strip keeps counting while the agent works.
 *
 * Plan checklist items are deliberately NOT steps. The plan is a prior the
 * agent may rewrite; showing its item count as "steps" made a turn look
 * finished when its fixed checklist was done.
 */

import type { PerformanceMetrics, SessionStats } from '@/types';

export interface SessionReading {
  /** User requests so far (the open request counts while it streams). */
  turns: number;
  /** Entered model iterations across the session. */
  steps: number;
  /** Billed input + output tokens, session + open turn. */
  totalTokens: number;
  /** Cache-hit share of prompt-side input, or null when nothing was billed. */
  cacheHitPct: number | null;
  /** Provider output tokens per second of decode time, or null without timing. */
  tokensPerSecond: number | null;
}

/** Sum a durable total with the open turn's live share. */
function sum(total: number | undefined, live: number | undefined, includeLive: boolean): number {
  return Math.max(0, (total ?? 0) + (includeLive ? (live ?? 0) : 0));
}

/**
 * Build the strip's reading.
 * @param stats - durable session totals (null before the first settled turn).
 * @param live - the open turn's provider metrics while streaming.
 * @param isStreaming - whether a turn is open (counts it and adds `live`).
 * @returns display-ready counts and rates, never negative.
 */
export function buildSessionReading(
  stats: SessionStats | null | undefined,
  live: PerformanceMetrics | null | undefined,
  isStreaming: boolean,
): SessionReading {
  const turns = Math.max(0, (stats?.turnCount ?? 0) + (isStreaming ? 1 : 0));
  const promptTokens = sum(stats?.promptTokens, live?.promptTokens, isStreaming);
  const completionTokens = sum(stats?.completionTokens, live?.completionTokens, isStreaming);
  const steps = sum(stats?.llmCalls, live?.llmCalls, isStreaming);
  const cachedTokens = sum(stats?.cachedTokens, live?.cachedTokens, isStreaming);
  const genTimeMs = Math.max(0, stats?.genTimeMs ?? 0);
  const settledCompletion = Math.max(0, stats?.completionTokens ?? 0);

  const cacheHitPct = promptTokens > 0
    ? Math.min(100, Math.round((cachedTokens / promptTokens) * 100))
    : null;
  // Session-wide weighted speed; the open turn's own provider reading is the
  // fallback until the first turn settles into the durable totals.
  const tokensPerSecond = genTimeMs > 0 && settledCompletion > 0
    ? Math.round((settledCompletion / genTimeMs) * 1000)
    : isStreaming && (live?.tokensPerSecond ?? 0) > 0
      ? Math.round(live!.tokensPerSecond)
      : null;

  return {
    turns,
    steps,
    totalTokens: promptTokens + completionTokens,
    cacheHitPct,
    tokensPerSecond,
  };
}

/**
 * Compact token count: 831K, 19.4M, 1.2B.
 * @param value - token count.
 * @returns short human reading.
 */
export function formatCompactTokens(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '0';
  if (value < 1_000) return String(Math.round(value));
  if (value < 1_000_000) return `${Math.round(value / 1_000)}K`;
  if (value < 1_000_000_000) {
    const millions = value / 1_000_000;
    return `${millions < 10 ? millions.toFixed(1).replace(/\.0$/, '') : Math.round(millions)}M`;
  }
  const billions = value / 1_000_000_000;
  return `${billions < 10 ? billions.toFixed(1).replace(/\.0$/, '') : Math.round(billions)}B`;
}

/**
 * Compact duration: 45.2s under a minute, 4m16s from there on.
 * @param ms - duration in milliseconds.
 * @returns display string.
 */
export function formatDiveDuration(ms: number): string {
  const seconds = Math.max(0, ms) / 1_000;
  if (seconds < 60) return `${Math.round(seconds * 10) / 10}s`;
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)}m${String(whole % 60).padStart(2, '0')}s`;
}
