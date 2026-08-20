import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { findRetryPrompt, CenterPanel } from './CenterPanel';
import { ChatMessage as ChatMessageType, ModelOption } from '@/types';

function msg(role: 'user' | 'assistant', content: string, id: string): ChatMessageType {
  return { id, role, content, timestamp: '12:00' } as ChatMessageType;
}

const baseModel: ModelOption = { id: 'test-model', name: 'Test Model', provider: 'test' };

const baseProps = {
  messages: [],
  selectedModel: baseModel,
  isStreaming: false,
  onSend: () => {},
  onAbort: () => {},
  memoryCount: 0,
};

describe('findRetryPrompt', () => {
  it('returns the user prompt preceding an assistant message', () => {
    const messages = [
      msg('user', 'what is my disk space?', 'u1'),
      msg('assistant', 'Here is the answer', 'a1'),
    ];
    expect(findRetryPrompt(messages, 1)).toBe('what is my disk space?');
  });

  it('walks back past intermediate messages to find the last user prompt', () => {
    const messages = [
      msg('user', 'first prompt', 'u1'),
      msg('assistant', 'first answer', 'a1'),
      msg('user', 'second prompt', 'u2'),
      msg('assistant', 'second answer', 'a2'),
    ];
    expect(findRetryPrompt(messages, 3)).toBe('second prompt');
  });

  it('returns undefined for user messages', () => {
    const messages = [msg('user', 'hi', 'u1')];
    expect(findRetryPrompt(messages, 0)).toBeUndefined();
  });

  it('returns undefined for an assistant message with no preceding user content', () => {
    const messages = [msg('assistant', 'standalone', 'a0')];
    expect(findRetryPrompt(messages, 0)).toBeUndefined();
  });

  it('skips empty user content', () => {
    const messages = [msg('user', '', 'u0'), msg('assistant', 'answer', 'a1')];
    expect(findRetryPrompt(messages, 1)).toBeUndefined();
  });
});

describe('CenterPanel parent-degraded indicator (ADR-52 phase 2 / B-2026-08-20-4)', () => {
  it('does NOT render the degraded indicator when parent is ready', () => {
    render(
      <CenterPanel
        {...baseProps}
        health={{ status: 'online', parentReady: true, parentDegradedReason: '' }}
      />,
    );
    expect(screen.queryByTestId('parent-degraded-indicator')).not.toBeInTheDocument();
  });

  it('renders the degraded indicator when parentReady is false', () => {
    render(
      <CenterPanel
        {...baseProps}
        health={{ status: 'online', parentReady: false, parentDegradedReason: 'provider warmup failed' }}
      />,
    );
    const indicator = screen.getByTestId('parent-degraded-indicator');
    expect(indicator).toBeInTheDocument();
    // The tooltip should carry the degraded reason.
    const container = indicator.closest('div[title]') as HTMLElement;
    expect(container?.title).toContain('provider warmup failed');
  });

  it('does NOT render the degraded indicator when health is offline', () => {
    render(
      <CenterPanel
        {...baseProps}
        health={{ status: 'offline', parentReady: false, parentDegradedReason: 'down' }}
      />,
    );
    expect(screen.queryByTestId('parent-degraded-indicator')).not.toBeInTheDocument();
  });

  it('does NOT render the degraded indicator when parentReady is undefined (checking state)', () => {
    render(
      <CenterPanel
        {...baseProps}
        health={{ status: 'checking' }}
      />,
    );
    expect(screen.queryByTestId('parent-degraded-indicator')).not.toBeInTheDocument();
  });

  it('renders the degraded indicator without a reason string in the tooltip', () => {
    render(
      <CenterPanel
        {...baseProps}
        health={{ status: 'online', parentReady: false, parentDegradedReason: '' }}
      />,
    );
    const indicator = screen.getByTestId('parent-degraded-indicator');
    const container = indicator.closest('div[title]') as HTMLElement;
    // The tooltip should still render with the generic degraded message.
    expect(container?.title).toContain('Parent kernel degraded');
  });
});
