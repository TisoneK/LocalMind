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

describe('ChatMessage acknowledgement', () => {
  it('renders the opening acknowledgement as the first line of an assistant reply', () => {
    render(<ChatMessage message={makeMessage({ acknowledgement: "I'll list all projects." })} />);

    expect(screen.getByText("I'll list all projects.")).toBeInTheDocument();
  });

  it('does not render an acknowledgement for user messages', () => {
    render(<ChatMessage message={makeMessage({ role: 'user', content: 'hi', acknowledgement: 'nope' })} />);

    expect(screen.queryByText('nope')).not.toBeInTheDocument();
  });
});

describe('ChatMessage markdown table <br> handling', () => {
  it('renders <br> inside a table cell as a line break, not literal text', () => {
    const content = [
      '| Metric | Value |',
      '|---|---|',
      '| Temperature | 16-18°C<br>High: 23°C |',
    ].join('\n');
    render(<ChatMessage message={makeMessage({ content })} onRetry={() => {}} />);
    // The literal "<br>" must NOT appear as text …
    expect(screen.queryByText(/<br\s*\/?>/i)).not.toBeInTheDocument();
    // … and both values render (split across a real line break).
    expect(screen.getByText(/16-18°C/)).toBeInTheDocument();
    expect(screen.getByText(/High: 23°C/)).toBeInTheDocument();
  });
});

// ── Accept collapses the diff card to the normal view ──────

/** A minimal single-hunk diff payload shaped like the live `diff` SSE event. */
function makeDiffData() {
  return {
    hunks: [
      {
        filePath: '/home/z/notes/todo.md',
        oldStart: 1,
        oldLines: 1,
        newStart: 1,
        newLines: 2,
        lines: [
          { type: 'context' as const, content: 'shopping list' },
          { type: 'removed' as const, oldLine: 2, content: '- milk' },
          { type: 'added' as const, newLine: 2, content: '- oat milk' },
          { type: 'added' as const, newLine: 3, content: '- bread' },
        ],
      },
    ],
    language: 'markdown',
  };
}

describe('ChatMessage file diff', () => {
  it('opens as the compact applied card — the change is already on disk, so no Accept/Reject', () => {
    render(<ChatMessage message={makeMessage({ diffData: makeDiffData() })} onRetry={() => {}} />);
    expect(screen.queryByRole('button', { name: /accept/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /reject/i })).toBeNull();
    expect(screen.queryByText('- milk')).toBeNull();
    expect(screen.getByText('todo.md')).toBeTruthy();
    expect(screen.getByText(/\+2/)).toBeTruthy();
    expect(screen.getByTestId('diff-applied-toggle')).toBeTruthy();
  });

  it('re-opens the diff read-only via View diff, and hides it again', () => {
    render(<ChatMessage message={makeMessage({ diffData: makeDiffData() })} onRetry={() => {}} />);
    fireEvent.click(screen.getByTestId('diff-applied-toggle'));
    expect(screen.getByText('- milk')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /^accept$/i })).toBeNull();
    fireEvent.click(screen.getByTestId('diff-applied-toggle'));
    expect(screen.queryByText('- milk')).toBeNull();
    expect(screen.getByTestId('diff-applied-toggle')).toBeTruthy();
  });

  it('renders no diff UI when the message has no diffData', () => {
    render(<ChatMessage message={makeMessage()} onRetry={() => {}} />);
    expect(screen.queryByTestId('diff-applied-toggle')).toBeNull();
    expect(screen.queryByRole('button', { name: /apply these changes/i })).toBeNull();
  });
});

describe('ChatMessage edit', () => {
  it('offers Edit on your message only when an edit handler is given', () => {
    const onEdit = vi.fn();
    const user = makeMessage({ role: 'user', content: 'hello there' });
    const { unmount } = render(<ChatMessage message={user} onEdit={onEdit} />);
    fireEvent.click(screen.getByRole('button', { name: /edit/i }));
    expect(onEdit).toHaveBeenCalledTimes(1);
    unmount();
    render(<ChatMessage message={user} />);
    expect(screen.queryByRole('button', { name: /edit/i })).toBeNull();
  });
});

describe('ChatMessage failed reply', () => {
  const error = { status: 'error' as const, source: 'model_provider' as const, code: 'rate_limit', message: 'The model provider has temporarily reached its usage limit.', retryable: true };

  it('shows the error card once, without repeating it as answer text', () => {
    render(
      <ChatMessage
        message={makeMessage({
          error,
          content: '⚠️ The model ran into an issue. Please try again, or switch to a larger model for this task.',
        })}
      />,
    );
    expect(screen.getByText(/usage limit/)).toBeInTheDocument();
    expect(screen.queryByText(/ran into an issue/)).toBeNull();
  });

  it('keeps a real partial answer beside the card', () => {
    render(<ChatMessage message={makeMessage({ error, content: 'The file has 3 rows.' })} />);
    expect(screen.getByText('The file has 3 rows.')).toBeInTheDocument();
  });
});

describe('ChatMessage undo', () => {
  it('shows Undo only when the write can be undone, and reports the result', async () => {
    const { localmindClient } = await import('@/lib/localmind/client');
    const spy = vi.spyOn(localmindClient, 'undoFileChange').mockResolvedValue({ message: 'Restored the previous version.' });
    const withUndo = makeMessage({ diffData: { ...makeDiffData(), undoId: 'abc' } });
    const { unmount } = render(<ChatMessage message={withUndo} />);
    fireEvent.click(screen.getByTestId('diff-undo'));
    expect(await screen.findByText('Restored the previous version.')).toBeInTheDocument();
    expect(spy).toHaveBeenCalledWith('abc');
    expect(screen.queryByTestId('diff-undo')).toBeNull();
    unmount();
    render(<ChatMessage message={makeMessage({ diffData: makeDiffData() })} />);
    expect(screen.queryByTestId('diff-undo')).toBeNull();
  });
});
