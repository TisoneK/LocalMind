import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ChatStatsStrip } from './ChatStatsStrip';
import type { SessionStats } from '@/types';

const stats: SessionStats = {
  promptTokens: 18_000_000,
  completionTokens: 1_000_000,
  latencyMs: 0,
  genTimeMs: 5_000_000,
  turnCount: 4,
  cachedTokens: 17_820_000,
  llmCalls: 190,
};

describe('ChatStatsStrip', () => {
  it('reads turns, steps, speed, tokens and cache hit after a turn settles', () => {
    render(<ChatStatsStrip stats={stats} isStreaming={false} />);
    const reading = screen.getByTestId('chat-stats-reading');
    expect(reading).toHaveTextContent('4 turns');
    expect(reading).toHaveTextContent('190 steps');
    expect(reading).toHaveTextContent('200 tok/s');
    expect(reading).toHaveTextContent('19M tok');
    expect(reading).toHaveTextContent('Cache hit 99%');
  });

  it('shows the deep-dive clock while a turn is open', () => {
    render(
      <ChatStatsStrip
        stats={stats}
        live={{ tokensPerSecond: 0, latency: 0, totalTokens: 0, promptTokens: 0, completionTokens: 0 }}
        isStreaming
        elapsedMs={256_000}
      />,
    );
    expect(screen.getByTestId('deep-diving')).toHaveTextContent('Deep diving for 4m16s');
  });

  it('hides the counts before the first turn reports', () => {
    render(<ChatStatsStrip stats={null} isStreaming={false} />);
    expect(screen.getByTestId('chat-stats-reading')).toBeEmptyDOMElement();
  });
});
