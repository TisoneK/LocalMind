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

// ── B-2026-08-25-6: Accept collapses the diff card to the normal view ──────

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

describe('ChatMessage diff accept flow (B-2026-08-25-6)', () => {
  it('renders the full diff with an Accept bar while pending', () => {
    render(<ChatMessage message={makeMessage({ diffData: makeDiffData() })} onRetry={() => {}} />);
    expect(screen.getByRole('button', { name: /accept/i })).toBeTruthy();
    // A removed diff line is visible in the colored diff view.
    expect(screen.getByText('- milk')).toBeTruthy();
  });

  it('collapses to the compact applied card after Accept — no colored diff, no Accept bar', () => {
    render(<ChatMessage message={makeMessage({ diffData: makeDiffData() })} onRetry={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: /accept/i }));
    // Accept bar gone.
    expect(screen.queryByRole('button', { name: /accept/i })).toBeNull();
    // Colored diff lines gone (the normal view replaces them).
    expect(screen.queryByText('- milk')).toBeNull();
    // Compact applied card shows the file name and +/− stats.
    expect(screen.getByText('todo.md')).toBeTruthy();
    expect(screen.getByText(/\+2/)).toBeTruthy();
    expect(screen.getByTestId('diff-applied-toggle')).toBeTruthy();
  });

  it('re-opens the diff read-only via View diff, and hides it again', () => {
    render(<ChatMessage message={makeMessage({ diffData: makeDiffData() })} onRetry={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: /accept/i }));
    // Re-open.
    fireEvent.click(screen.getByTestId('diff-applied-toggle'));
    expect(screen.getByText('- milk')).toBeTruthy();
    // Read-only: no second Accept bar in the re-opened diff.
    expect(screen.queryByRole('button', { name: /^accept$/i })).toBeNull();
    // Hide again — back to the compact card only.
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
