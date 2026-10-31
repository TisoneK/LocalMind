import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ChatStatsStrip } from './ChatStatsStrip';
import type { GoalState, SessionStats } from '@/types';

const stats: SessionStats = {
  promptTokens: 18_000_000,
  completionTokens: 1_000_000,
  latencyMs: 0,
  genTimeMs: 5_000_000,
  turnCount: 4,
  cachedTokens: 17_820_000,
  llmCalls: 190,
};

const goal: GoalState = {
  id: 'goal-1',
  objective: 'Ship the goal slice',
  phase: 'active',
  revision: 3,
  roundsStarted: 2,
  maxGoalRounds: 8,
  armed: true,
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

  it('says the answer is ready while the turn finishes up', () => {
    render(
      <ChatStatsStrip
        stats={stats}
        live={{ tokensPerSecond: 0, latency: 0, totalTokens: 0, promptTokens: 0, completionTokens: 0 }}
        isStreaming
        responseReady
        elapsedMs={256_000}
      />,
    );
    // The reply is final: the strip names the state instead of letting the
    // deep-dive timer keep counting over a finished answer.
    expect(screen.getByTestId('answer-finishing')).toHaveTextContent('Answer ready · finishing up…');
    expect(screen.queryByTestId('deep-diving')).toBeNull();
  });

  it('hides the counts before the first turn reports', () => {
    render(<ChatStatsStrip stats={null} isStreaming={false} />);
    expect(screen.getByTestId('chat-stats-reading')).toBeEmptyDOMElement();
  });

  it('shows the goal round meter while a goal is active', () => {
    render(<ChatStatsStrip stats={stats} isStreaming={false} goal={goal} />);
    expect(screen.getByTestId('goal-round-meter')).toHaveTextContent('Goal 2/8');
    expect(screen.getByTestId('goal-round-meter')).not.toHaveTextContent('stopped');
  });

  it('marks an active goal as stopped when continuation is disarmed', () => {
    render(<ChatStatsStrip stats={stats} isStreaming={false} goal={{ ...goal, armed: false }} />);
    expect(screen.getByTestId('goal-round-meter')).toHaveTextContent(/Goal 2\/8\s*·\s*stopped/);
  });

  it('summarizes paused and blocked goals', () => {
    const { rerender } = render(
      <ChatStatsStrip stats={stats} isStreaming={false} goal={{ ...goal, phase: 'paused' }} />,
    );
    expect(screen.getByTestId('goal-round-meter')).toHaveTextContent('Goal paused');

    rerender(
      <ChatStatsStrip
        stats={stats}
        isStreaming={false}
        goal={{ ...goal, phase: 'blocked', blockedReason: 'round-limit', armed: false }}
      />,
    );
    expect(screen.getByTestId('goal-round-meter')).toHaveTextContent('Goal blocked');
  });

  it('hides a completed goal', () => {
    render(<ChatStatsStrip stats={stats} isStreaming={false} goal={{ ...goal, phase: 'complete' }} />);
    expect(screen.queryByTestId('goal-round-meter')).not.toBeInTheDocument();
  });
});
