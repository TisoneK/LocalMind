import { describe, expect, it } from 'vitest';
import type { PerformanceMetrics, SessionStats } from '@/types';
import {
  buildSessionReading,
  formatCompactTokens,
  formatDiveDuration,
} from './sessionReading';

const stats = (overrides: Partial<SessionStats> = {}): SessionStats => ({
  promptTokens: 0,
  completionTokens: 0,
  latencyMs: 0,
  genTimeMs: 0,
  turnCount: 0,
  cachedTokens: 0,
  llmCalls: 0,
  ...overrides,
});

const live = (overrides: Partial<PerformanceMetrics> = {}): PerformanceMetrics => ({
  tokensPerSecond: 0,
  latency: 0,
  totalTokens: 0,
  promptTokens: 0,
  completionTokens: 0,
  ...overrides,
});

describe('buildSessionReading', () => {
  it('counts user requests as turns and model iterations as steps', () => {
    const reading = buildSessionReading(stats({ turnCount: 4, llmCalls: 190 }), null, false);
    expect(reading.turns).toBe(4);
    expect(reading.steps).toBe(190);
  });

  it('counts the open turn while streaming and adds its live steps', () => {
    const reading = buildSessionReading(
      stats({ turnCount: 3, llmCalls: 120 }),
      live({ llmCalls: 7 }),
      true,
    );
    expect(reading.turns).toBe(4);
    expect(reading.steps).toBe(127);
  });

  it('does not add live figures once the turn settled', () => {
    const reading = buildSessionReading(stats({ turnCount: 1, llmCalls: 12 }), live({ llmCalls: 12 }), false);
    expect(reading.turns).toBe(1);
    expect(reading.steps).toBe(12);
  });

  it('sums prompt and output tokens and computes the cache-hit share', () => {
    const reading = buildSessionReading(
      stats({ promptTokens: 900_000, completionTokens: 100_000, cachedTokens: 891_000 }),
      null,
      false,
    );
    expect(reading.totalTokens).toBe(1_000_000);
    expect(reading.cacheHitPct).toBe(99);
  });

  it('reports no cache hit and no speed before anything is billed', () => {
    const reading = buildSessionReading(stats(), null, false);
    expect(reading.cacheHitPct).toBeNull();
    expect(reading.tokensPerSecond).toBeNull();
    expect(reading.totalTokens).toBe(0);
  });

  it('derives session speed from weighted generation time', () => {
    const reading = buildSessionReading(
      stats({ completionTokens: 400, genTimeMs: 2_000 }),
      null,
      false,
    );
    expect(reading.tokensPerSecond).toBe(200);
  });

  it('falls back to the open turn speed until the first turn settles', () => {
    const reading = buildSessionReading(stats(), live({ tokensPerSecond: 64.4 }), true);
    expect(reading.tokensPerSecond).toBe(64);
  });
});

describe('formatCompactTokens', () => {
  it('uses the Harness compact units', () => {
    expect(formatCompactTokens(0)).toBe('0');
    expect(formatCompactTokens(831)).toBe('831');
    expect(formatCompactTokens(831_000)).toBe('831K');
    expect(formatCompactTokens(9_400_000)).toBe('9.4M');
    expect(formatCompactTokens(19_400_000)).toBe('19M');
    expect(formatCompactTokens(2_000_000_000)).toBe('2B');
  });
});

describe('formatDiveDuration', () => {
  it('reads seconds under a minute and minutes after', () => {
    expect(formatDiveDuration(45_200)).toBe('45.2s');
    expect(formatDiveDuration(256_000)).toBe('4m16s');
  });
});
