import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { ChatMessage } from './ChatMessage';
import { ChatMessage as ChatMessageType } from '@/types';

// jsdom does not provide navigator.clipboard — stub it so Copy works.
const writeText = vi.fn().mockResolvedValue(undefined);
Object.defineProperty(navigator, 'clipboard', {
  value: { writeText },
  configurable: true,
});

function makeMessage(overrides: Partial<ChatMessageType> = {}): ChatMessageType {
  return {
    id: 'm1',
    role: 'assistant',
    content: 'Hello from LocalMind',
    timestamp: '12:11',
    ...overrides,
  } as ChatMessageType;
}

describe('ChatMessage hover action row', () => {
  beforeEach(() => {
    writeText.mockClear();
  });

  it('renders Copy + Retry for assistant messages, hidden until hover', () => {
    render(<ChatMessage message={makeMessage()} onRetry={() => {}} />);

    const actions = screen.getByTestId('message-actions');
    // Hidden by default; revealed only on group hover.
    expect(actions.className).toContain('opacity-0');
    expect(actions.className).toContain('group-hover:opacity-100');

    expect(screen.getByRole('button', { name: /copy/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });

  it('copies the message content to the clipboard', async () => {
    render(<ChatMessage message={makeMessage()} onRetry={() => {}} />);

    fireEvent.click(screen.getByRole('button', { name: /copy/i }));

    expect(writeText).toHaveBeenCalledWith('Hello from LocalMind');
    // Flush the async handler's microtask so setCopied(true) renders.
    await act(async () => {});
    // Button flips to a "Copied" confirmation state.
    expect(screen.getByRole('button', { name: /copied/i })).toBeInTheDocument();
  });

  it('invokes onRetry when Retry is clicked', () => {
    const onRetry = vi.fn();
    render(<ChatMessage message={makeMessage()} isStreaming={false} onRetry={onRetry} />);

    fireEvent.click(screen.getByRole('button', { name: /retry/i }));

    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('disables Retry while streaming', () => {
    render(<ChatMessage message={makeMessage()} isStreaming onRetry={() => {}} />);

    expect(screen.getByRole('button', { name: /retry/i })).toBeDisabled();
  });

  it('renders only Copy (no Retry) for user messages', () => {
    render(<ChatMessage message={makeMessage({ role: 'user', content: 'my prompt' })} />);

    expect(screen.getByRole('button', { name: /copy/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /retry/i })).not.toBeInTheDocument();
  });

  it('disables Copy when the message has no content yet (streaming placeholder)', () => {
    render(<ChatMessage message={makeMessage({ content: '' })} isStreaming />);

    expect(screen.getByRole('button', { name: /copy/i })).toBeDisabled();
  });
});

describe('ChatMessage acknowledgement (ADR-36)', () => {
  it('renders the opening acknowledgement as the first line of an assistant reply', () => {
    render(<ChatMessage message={makeMessage({ acknowledgement: "I'll list all projects." })} />);

    expect(screen.getByText("I'll list all projects.")).toBeInTheDocument();
  });

  it('does not render an acknowledgement for user messages', () => {
    render(<ChatMessage message={makeMessage({ role: 'user', content: 'hi', acknowledgement: 'nope' })} />);

    expect(screen.queryByText('nope')).not.toBeInTheDocument();
  });
});
