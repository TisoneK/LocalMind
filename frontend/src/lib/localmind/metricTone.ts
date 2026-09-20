/**
 * Colour for a performance number, so the stats read at a glance: green is good, amber is
 * worth noticing, red is slow. Thresholds are for interactive use of an agent, where a turn
 * that runs tools is expected to take several seconds.
 */

export type Tone = 'good' | 'warn' | 'bad' | 'neutral';

export const TONE_CLASS: Record<Tone, string> = {
  good: 'text-brand-green',
  warn: 'text-brand-amber',
  bad: 'text-brand-red',
  neutral: 'text-brand-green-soft',
};

export function latencyTone(ms: number): Tone {
  if (!(ms > 0)) return 'neutral';
  if (ms < 5000) return 'good';
  if (ms < 15000) return 'warn';
  return 'bad';
}

export function speedTone(tokensPerSecond: number): Tone {
  if (!(tokensPerSecond > 0)) return 'neutral';
  if (tokensPerSecond >= 30) return 'good';
  if (tokensPerSecond >= 10) return 'warn';
  return 'bad';
}

/** Share of the prompt served from the provider's cache: more is cheaper and faster. */
export function cacheTone(pct: number): Tone {
  if (!(pct > 0)) return 'neutral';
  if (pct >= 70) return 'good';
  if (pct >= 30) return 'warn';
  return 'neutral';
}

/** The middle value of the turn latencies, or 0 when there are none. */
export function median(values: number[]): number {
  const v = values.filter((n) => n > 0).sort((a, b) => a - b);
  if (v.length === 0) return 0;
  const mid = Math.floor(v.length / 2);
  return v.length % 2 ? v[mid] : (v[mid - 1] + v[mid]) / 2;
}
