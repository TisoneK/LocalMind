import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import { TranscriptContextMenu } from './TranscriptContextMenu';

function stubSelection(text: string) {
  vi.spyOn(window, 'getSelection').mockReturnValue({
    toString: () => text,
  } as unknown as Selection);
}

function stubClipboard() {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText },
    configurable: true,
    writable: true,
  });
  return writeText;
}

const messages = [
  { id: 'u1', content: 'first user prompt text' },
  { id: 'a1', content: 'assistant reply text' },
];

function renderMenu({
  getMessageText,
}: { getMessageText?: (id: string) => string | undefined } = {}) {
  return render(
    <TranscriptContextMenu getMessageText={getMessageText} onSelectAll={() => {}}>
      <div data-testid="transcript">
        {messages.map((m) => (
          <div key={m.id} data-message-content-id={m.id}>
            {m.content}
          </div>
        ))}
      </div>
    </TranscriptContextMenu>,
  );
}

async function openContextMenu() {
  await act(async () => {
    fireEvent.contextMenu(screen.getByTestId('transcript'));
  });
}

describe('TranscriptContextMenu', () => {
  beforeEach(() => {
    stubSelection('');
    stubClipboard();
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('renders its children as the right-click surface', () => {
    renderMenu();
    expect(screen.getByTestId('transcript')).toBeInTheDocument();
    expect(screen.queryByTestId('ctx-copy-selection')).not.toBeInTheDocument();
  });

  it('opens on right-click with Copy enabled when text is selected', async () => {
    stubSelection('selected words');
    renderMenu();
    await openContextMenu();
    const copy = screen.getByTestId('ctx-copy-selection');
    expect(copy).toBeInTheDocument();
    expect(copy).not.toHaveAttribute('aria-disabled');
  });

  it('shows Copy disabled when nothing is selected', async () => {
    stubSelection('');
    renderMenu();
    await openContextMenu();
    expect(screen.getByTestId('ctx-copy-selection')).toHaveAttribute('aria-disabled', 'true');
  });

  it('copies the captured selection to the clipboard', async () => {
    const writeText = stubClipboard();
    stubSelection('captured text');
    renderMenu();
    await openContextMenu();
    await act(async () => {
      fireEvent.click(screen.getByTestId('ctx-copy-selection'));
    });
    await act(async () => {});
    expect(writeText).toHaveBeenCalledWith('captured text');
  });

  it('does not copy when the selection is empty', async () => {
    const writeText = stubClipboard();
    stubSelection('');
    renderMenu();
    await openContextMenu();
    // Disabled item — the click is a no-op.
    expect(screen.getByTestId('ctx-copy-selection')).toHaveAttribute('aria-disabled', 'true');
    expect(writeText).not.toHaveBeenCalled();
  });

  it('offers Copy message when right-clicking inside a message and copies its full text', async () => {
    const writeText = stubClipboard();
    stubSelection('');
    const getMessageText = (id: string) => messages.find((m) => m.id === id)?.content;
    const { container } = renderMenu({ getMessageText });
    // Right-click on the user message's text node.
    await act(async () => {
      fireEvent.contextMenu(container.querySelector('[data-message-content-id="u1"]')!);
    });
    expect(screen.getByTestId('ctx-copy-message')).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByTestId('ctx-copy-message'));
    });
    await act(async () => {});
    expect(writeText).toHaveBeenCalledWith('first user prompt text');
  });

  it('resolves the right-clicked message via the closest marked ancestor', async () => {
    const writeText = stubClipboard();
    stubSelection('');
    const getMessageText = (id: string) => messages.find((m) => m.id === id)?.content;
    const { container } = renderMenu({ getMessageText });
    // Right-click directly on the assistant message's text node.
    await act(async () => {
      fireEvent.contextMenu(container.querySelector('[data-message-content-id="a1"]')!);
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId('ctx-copy-message'));
    });
    await act(async () => {});
    expect(writeText).toHaveBeenCalledWith('assistant reply text');
  });

  it('hides Copy message when the right-click is outside any message', async () => {
    stubSelection('');
    const getMessageText = () => undefined;
    renderMenu({ getMessageText });
    await openContextMenu();
    expect(screen.queryByTestId('ctx-copy-message')).not.toBeInTheDocument();
  });

  it('shows Select all when a handler is provided', async () => {
    const onSelectAll = vi.fn();
    stubSelection('');
    render(
      <TranscriptContextMenu onSelectAll={onSelectAll}>
        <div data-testid="transcript">content</div>
      </TranscriptContextMenu>,
    );
    await openContextMenu();
    await act(async () => {
      fireEvent.click(screen.getByTestId('ctx-select-all'));
    });
    expect(onSelectAll).toHaveBeenCalledTimes(1);
  });

  it('hides Select all when no handler is provided', async () => {
    stubSelection('');
    render(
      <TranscriptContextMenu>
        <div data-testid="transcript">content</div>
      </TranscriptContextMenu>,
    );
    await openContextMenu();
    expect(screen.queryByTestId('ctx-select-all')).not.toBeInTheDocument();
  });
});
