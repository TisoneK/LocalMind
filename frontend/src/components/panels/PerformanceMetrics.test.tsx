/**
 * Tests for PerformanceMetrics prompt-cache telemetry (P0 Context
 * Engineering Step 1). The corner must show the cached share of prompt
 * tokens (with hit %) when the provider reports it, hide the cached chip
 * when it doesn't, and always show the LLM-calls count that reported usage.
 */

import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { PerformanceMetrics } from './PerformanceMetrics';
import type { SessionStats } from '../../types';

const baseMetrics = {
  tokensPerSecond: 12.5,
  latency: 4200,
  totalTokens: 1330,
  promptTokens: 1250,
  completionTokens: 80,
};

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

describe('PerformanceMetrics cache telemetry', () => {
  it('hides the cached chip when the provider reports no caching', () => {
    render(<PerformanceMetrics metrics={baseMetrics} sessionStats={stats({ promptTokens: 1250, turnCount: 1 })} />);
    expect(screen.queryByText(/cached:/)).not.toBeInTheDocument();
    expect(screen.getByText(/prompt:/)).toBeInTheDocument();
  });

  it('shows the cached share with hit percentage from session stats', () => {
    render(
      <PerformanceMetrics
        metrics={baseMetrics}
        sessionStats={stats({ promptTokens: 1250, cachedTokens: 1024, turnCount: 2 })}
      />,
    );
    expect(screen.getByText(/cached:/)).toBeInTheDocument();
    // 1024/1250 = 82%
    expect(screen.getByText(/82%/)).toBeInTheDocument();
  });

  it('shows the LLM-calls count when usage was reported', () => {
    render(<PerformanceMetrics metrics={baseMetrics} sessionStats={stats({ llmCalls: 4, promptTokens: 500, turnCount: 1 })} />);
    expect(screen.getByText(/calls:/)).toBeInTheDocument();
    expect(screen.getByText('4')).toBeInTheDocument();
  });

  it('hides the calls chip when no calls reported usage', () => {
    render(<PerformanceMetrics metrics={baseMetrics} sessionStats={stats({ promptTokens: 500, turnCount: 1 })} />);
    expect(screen.queryByText(/calls:/)).not.toBeInTheDocument();
  });

  it('adds the live turn cache on top of session totals while streaming', () => {
    render(
      <PerformanceMetrics
        metrics={baseMetrics}
        lastMetrics={{ ...baseMetrics, promptTokens: 300, cachedTokens: 200, llmCalls: 1 }}
        isStreaming
        elapsedMs={1500}
        sessionStats={stats({ promptTokens: 1250, cachedTokens: 1024, llmCalls: 3, turnCount: 2 })}
      />,
    );
    // (1024+200) / (1250+300) = 1224/1550 = 79%
    expect(screen.getByText(/79%/)).toBeInTheDocument();
    expect(screen.getByText('4')).toBeInTheDocument(); // 3 + 1
  });
});
