import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { findRetryPrompt, CenterPanel } from './CenterPanel';
import { ChatMessage as ChatMessageType, ModelOption, ReflectionLesson, PassiveMemory } from '@/types';
import { localmindClient as client } from '@/lib/localmind/client';

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

describe('CenterPanel parent-degraded indicator', () => {
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

describe('CenterPanel reflection-lesson badge (B-2026-09-15-14)', () => {
  const lesson: ReflectionLesson = {
    id: 'l1',
    text: 'Check locale before assuming a region.',
    intent: 'analyze',
    score: 4,
    confidence: 'medium',
    ts: 1,
  };

  it('does NOT render the badge when no lesson has been noted', () => {
    render(<CenterPanel {...baseProps} health={{ status: 'online' }} reflectionLessons={[]} />);
    expect(screen.queryByTestId('reflection-lesson-badge')).not.toBeInTheDocument();
  });

  it('does NOT render the badge when reflectionLessons is omitted', () => {
    render(<CenterPanel {...baseProps} health={{ status: 'online' }} />);
    expect(screen.queryByTestId('reflection-lesson-badge')).not.toBeInTheDocument();
  });

  it('renders the badge with a count once a lesson is noted, closed by default', () => {
    render(
      <CenterPanel {...baseProps} health={{ status: 'online' }} reflectionLessons={[lesson]} />,
    );
    const badge = screen.getByTestId('reflection-lesson-badge');
    expect(badge.textContent).toContain('1');
    expect(screen.queryByTestId('reflection-lesson-panel')).not.toBeInTheDocument();
  });

  it('clicking the badge opens a panel showing the lesson text — the visible-write surface', () => {
    render(
      <CenterPanel {...baseProps} health={{ status: 'online' }} reflectionLessons={[lesson]} />,
    );
    fireEvent.click(screen.getByTestId('reflection-lesson-badge'));
    const panel = screen.getByTestId('reflection-lesson-panel');
    expect(panel.textContent).toContain('Check locale before assuming a region.');
  });

  it('closing the panel via the X button hides it again', () => {
    render(
      <CenterPanel {...baseProps} health={{ status: 'online' }} reflectionLessons={[lesson]} />,
    );
    fireEvent.click(screen.getByTestId('reflection-lesson-badge'));
    fireEvent.click(screen.getByLabelText('Close reflection lessons'));
    expect(screen.queryByTestId('reflection-lesson-panel')).not.toBeInTheDocument();
  });

  it('shows newest lessons first', () => {
    const older: ReflectionLesson = { ...lesson, id: 'l0', text: 'Older lesson text.' };
    const newer: ReflectionLesson = { ...lesson, id: 'l1', text: 'Newer lesson text.' };
    render(
      <CenterPanel
        {...baseProps}
        health={{ status: 'online' }}
        reflectionLessons={[older, newer]}
      />,
    );
    fireEvent.click(screen.getByTestId('reflection-lesson-badge'));
    const panel = screen.getByTestId('reflection-lesson-panel');
    const olderIdx = panel.textContent!.indexOf('Older lesson text.');
    const newerIdx = panel.textContent!.indexOf('Newer lesson text.');
    expect(newerIdx).toBeGreaterThanOrEqual(0);
    expect(olderIdx).toBeGreaterThan(newerIdx);
  });
});

describe('CenterPanel embed-model guide', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    sessionStorage.clear();
  });

  it('shows the guide when the configured embed model is missing and an alternative exists', async () => {
    vi.spyOn(client, 'getEmbeddingModels').mockResolvedValue({
      models: [{ id: 'nomic-embed-text', name: 'nomic-embed-text', provider: 'ollama' }],
      current: 'nomic-embed-text',
      configured_available: false,
      suggested: 'mxbai-embed-large',
    });
    render(<CenterPanel {...baseProps} health={{ status: 'online' }} />);
    const guide = await screen.findByTestId('embed-guide');
    expect(guide.textContent).toContain('nomic-embed-text');
    expect(guide.textContent).toContain('mxbai-embed-large');
  });

  it('does not show the guide when the configured model is available', async () => {
    vi.spyOn(client, 'getEmbeddingModels').mockResolvedValue({
      models: [{ id: 'mxbai-embed-large', name: 'mxbai-embed-large', provider: 'ollama' }],
      current: 'mxbai-embed-large',
      configured_available: true,
      suggested: null,
    });
    render(<CenterPanel {...baseProps} health={{ status: 'online' }} />);
    await waitFor(() => expect(client.getEmbeddingModels).toHaveBeenCalled());
    expect(screen.queryByTestId('embed-guide')).not.toBeInTheDocument();
  });

  it('does not show the guide when there is no alternative to suggest', async () => {
    vi.spyOn(client, 'getEmbeddingModels').mockResolvedValue({
      models: [],
      current: 'nomic-embed-text',
      configured_available: false,
      suggested: null,
    });
    render(<CenterPanel {...baseProps} health={{ status: 'online' }} />);
    await waitFor(() => expect(client.getEmbeddingModels).toHaveBeenCalled());
    expect(screen.queryByTestId('embed-guide')).not.toBeInTheDocument();
  });

  it('one-click fix applies the suggested model via setLocalSettings and confirms', async () => {
    vi.spyOn(client, 'getEmbeddingModels').mockResolvedValue({
      models: [],
      current: 'nomic-embed-text',
      configured_available: false,
      suggested: 'mxbai-embed-large',
    });
    const setLocal = vi.spyOn(client, 'setLocalSettings').mockResolvedValue({
      embed_model: 'mxbai-embed-large', num_ctx: 0, updated: ['embed_model'], message: 'ok',
    });
    render(<CenterPanel {...baseProps} health={{ status: 'online' }} />);
    fireEvent.click(await screen.findByTestId('embed-guide-fix'));
    await waitFor(() => expect(setLocal).toHaveBeenCalledWith({ embedModel: 'mxbai-embed-large' }));
    // Confirmation text appears and the session is marked fixed.
    await screen.findByText(/Embedding model switched to/);
    expect(sessionStorage.getItem('localmind:embed-guide-dismissed')).toBe('1');
  });

  it('one-click fix shows an error and keeps the banner when it fails', async () => {
    vi.spyOn(client, 'getEmbeddingModels').mockResolvedValue({
      models: [],
      current: 'nomic-embed-text',
      configured_available: false,
      suggested: 'mxbai-embed-large',
    });
    vi.spyOn(client, 'setLocalSettings').mockRejectedValue(new Error('boom'));
    render(<CenterPanel {...baseProps} health={{ status: 'online' }} />);
    fireEvent.click(await screen.findByTestId('embed-guide-fix'));
    expect(await screen.findByText(/Failed to update the embedding model/)).toBeInTheDocument();
    expect(screen.getByTestId('embed-guide')).toBeInTheDocument();
    expect(sessionStorage.getItem('localmind:embed-guide-dismissed')).not.toBe('1');
  });

  it('dismiss hides the guide and remembers for the session', async () => {
    vi.spyOn(client, 'getEmbeddingModels').mockResolvedValue({
      models: [],
      current: 'nomic-embed-text',
      configured_available: false,
      suggested: 'mxbai-embed-large',
    });
    render(<CenterPanel {...baseProps} health={{ status: 'online' }} />);
    fireEvent.click(await screen.findByTestId('embed-guide-dismiss'));
    expect(screen.queryByTestId('embed-guide')).not.toBeInTheDocument();
    expect(sessionStorage.getItem('localmind:embed-guide-dismissed')).toBe('1');
  });
});
