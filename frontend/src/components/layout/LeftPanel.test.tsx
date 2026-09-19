/**
 * Tests for LeftPanel multi-select chat management: mark multiple chats →
 * bulk delete or export.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { LeftPanel } from './LeftPanel';
import { localmindClient as client } from '@/lib/localmind/client';
import type { Session } from '@/types';

const sessions: Session[] = [
  { id: 'a', title: 'Chat A', lastMessage: 'x', timestamp: '1', messageCount: 1, active: false },
  { id: 'b', title: 'Chat B', lastMessage: 'y', timestamp: '2', messageCount: 2, active: false },
  { id: 'c', title: 'Chat C', lastMessage: 'z', timestamp: '3', messageCount: 3, active: false },
];

function renderPanel(over: Partial<React.ComponentProps<typeof LeftPanel>> = {}) {
  const props = {
    sessions,
    files: [],
    models: [],
    selectedModel: 'm',
    onModelChange: vi.fn(),
    currentSessionId: null,
    onSelectSession: vi.fn(),
    onNewChat: vi.fn(),
    onDeleteSession: vi.fn(),
    onDeleteSessions: vi.fn(),
    onExportSessions: vi.fn(),
    onCopySessions: vi.fn(),
    ...over,
  };
  render(<LeftPanel {...props} />);
  return props;
}

describe('LeftPanel multi-select', () => {
  it('enters selection mode and does not switch session when a row is clicked', () => {
    const props = renderPanel();
    fireEvent.click(screen.getByTestId('select-chats'));
    const rows = screen.getAllByTestId('session-row');
    fireEvent.click(rows[0]);
    // In selection mode, clicking a row selects it — it must NOT open the chat.
    expect(props.onSelectSession).not.toHaveBeenCalled();
    expect(screen.getByTestId('selected-count')).toHaveTextContent('1 selected');
  });

  it('select-all marks every chat', () => {
    renderPanel();
    fireEvent.click(screen.getByTestId('select-chats'));
    fireEvent.click(screen.getByTitle('Select all'));
    expect(screen.getByTestId('selected-count')).toHaveTextContent('3 selected');
  });

  it('bulk delete calls onDeleteSessions with the selected ids after confirm', () => {
    const props = renderPanel();
    fireEvent.click(screen.getByTestId('select-chats'));
    const rows = screen.getAllByTestId('session-row');
    fireEvent.click(rows[0]); // a
    fireEvent.click(rows[2]); // c
    fireEvent.click(screen.getByTestId('bulk-delete'));
    fireEvent.click(screen.getByTestId('bulk-delete-confirm'));
    expect(props.onDeleteSessions).toHaveBeenCalledTimes(1);
    expect(props.onDeleteSessions).toHaveBeenCalledWith(['a', 'c']);
  });

  it('export menu triggers onExportSessions with the chosen format', () => {
    const props = renderPanel();
    fireEvent.click(screen.getByTestId('select-chats'));
    fireEvent.click(screen.getByTitle('Select all'));
    fireEvent.click(screen.getByTestId('bulk-export'));
    fireEvent.click(screen.getByTestId('export-markdown'));
    expect(props.onExportSessions).toHaveBeenCalledWith(['a', 'b', 'c'], 'markdown');
  });

  it('copy menu triggers onCopySessions with the chosen format', async () => {
    const props = renderPanel();
    fireEvent.click(screen.getByTestId('select-chats'));
    fireEvent.click(screen.getByTitle('Select all'));
    fireEvent.click(screen.getByTestId('bulk-copy'));
    fireEvent.click(screen.getByTestId('copy-json'));
    await vi.waitFor(() => expect(props.onCopySessions).toHaveBeenCalledWith(['a', 'b', 'c'], 'json'));
  });

  it('copy success flashes the copied feedback', async () => {
    const ok = vi.fn().mockResolvedValue(undefined);
    renderPanel({ onCopySessions: ok });
    fireEvent.click(screen.getByTestId('select-chats'));
    fireEvent.click(screen.getByTitle('Select all'));
    fireEvent.click(screen.getByTestId('bulk-copy'));
    fireEvent.click(screen.getByTestId('copy-markdown'));
    const flash = await screen.findByTestId('copy-feedback');
    expect(flash).toHaveTextContent('✓ Copied');
  });

  it('copy rejection surfaces the clipboard-blocked flash instead of throwing', async () => {
    const failing = vi.fn().mockRejectedValue(new Error('denied'));
    renderPanel({ onCopySessions: failing });
    fireEvent.click(screen.getByTestId('select-chats'));
    fireEvent.click(screen.getByTitle('Select all'));
    fireEvent.click(screen.getByTestId('bulk-copy'));
    fireEvent.click(screen.getByTestId('copy-json'));
    const flash = await screen.findByTestId('copy-feedback');
    expect(flash).toHaveTextContent('✗ Clipboard blocked');
    // The panel survives — this is a user-facing notice, not a crash.
    expect(screen.getByTestId('bulk-copy')).toBeInTheDocument();
  });

  it('individual delete controls are hidden while selecting', () => {
    renderPanel();
    // Before selection mode, per-row delete buttons exist (hover-revealed).
    expect(screen.getAllByTitle('Delete session').length).toBe(3);
    fireEvent.click(screen.getByTestId('select-chats'));
    expect(screen.queryByTitle('Delete session')).toBeNull();
  });

  it('exit clears selection and returns to the Select affordance', () => {
    renderPanel();
    fireEvent.click(screen.getByTestId('select-chats'));
    const rows = screen.getAllByTestId('session-row');
    fireEvent.click(rows[1]);
    expect(screen.getByTestId('selected-count')).toHaveTextContent('1 selected');
    fireEvent.click(screen.getByLabelText('Exit selection'));
    expect(screen.queryByTestId('selected-count')).toBeNull();
    expect(screen.getByTestId('select-chats')).toBeInTheDocument();
  });

  it('switches back to the Chat tab when forceChatTab is set (New Chat)', () => {
    const baseProps = {
      sessions,
        files: [],
          models: [],
      selectedModel: 'm',
      onModelChange: vi.fn(),
      currentSessionId: null,
      onSelectSession: vi.fn(),
      onNewChat: vi.fn(),
      onDeleteSession: vi.fn(),
      onDeleteSessions: vi.fn(),
      onExportSessions: vi.fn(),
      onCopySessions: vi.fn(),
        };
    // Production wiring: onChatTabShown clears the forceChatTab flag in the
    // parent (WorkspaceLayout: `onChatTabShown={() => setForceChatTab(false)}`).
    // Mirror that with a re-render so the effect consumes the flag exactly once.
    const { rerender } = render(<LeftPanel {...baseProps} />);
    // Leave the Chat tab first so the switch is observable.
    fireEvent.click(screen.getByRole('tab', { name: 'Files' }));
    expect(screen.getByText(/Start a chat/)).toBeInTheDocument();

    const onChatTabShown = vi.fn();
    const show = (f: boolean) =>
      rerender(<LeftPanel {...baseProps} forceChatTab={f} onChatTabShown={onChatTabShown} />);
    show(true); // New Chat sets the flag
    expect(onChatTabShown).toHaveBeenCalledTimes(1);
    show(false); // parent clears the flag (as onChatTabShown does)

    expect(screen.getAllByTestId('session-row')).toHaveLength(3);
    expect(onChatTabShown).toHaveBeenCalledTimes(1);
  });

  it('consuming forceChatTab on Chat does not fight the first tool event', () => {
    // The reported bug: New Chat while ALREADY on the Chat tab left
    // forceChatTab=true (the old guard `activeTab !== 'chat'` never fired).
    // The FIRST tab switch then landed on another tab, and the still-set flag
    // yanked the tab straight back — only the SECOND action stuck.
    const baseProps = {
      sessions,
        files: [],
          models: [],
      selectedModel: 'm',
      onModelChange: vi.fn(),
      currentSessionId: null,
      onSelectSession: vi.fn(),
      onNewChat: vi.fn(),
      onDeleteSession: vi.fn(),
      onDeleteSessions: vi.fn(),
      onExportSessions: vi.fn(),
      onCopySessions: vi.fn(),
        };
    // Production wiring: shown → flag cleared.
    let forceChatTab = true;
    const onChatTabShown = vi.fn(() => {
      forceChatTab = false;
    });
    const { rerender } = render(<LeftPanel {...baseProps} />);
    // User is on the Chat tab (default).
    expect(screen.getByText('Chat')).toBeInTheDocument();

    // New Chat sets forceChatTab while on Chat.
    rerender(<LeftPanel {...baseProps} forceChatTab onChatTabShown={onChatTabShown} />);
    // The flag must be consumed even though no switch was needed.
    expect(onChatTabShown).toHaveBeenCalledTimes(1);

    // User moves to Files.
    rerender(<LeftPanel {...baseProps} forceChatTab={forceChatTab} onChatTabShown={onChatTabShown} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Files' }));
    // Simulate the tab being yanked back: with the flag consumed, no.
    expect(screen.getByText(/Start a chat/)).toBeInTheDocument();
    // onChatTabShown was NOT called again — the flag is gone, no fight.
    expect(onChatTabShown).toHaveBeenCalledTimes(1);
  });

  it('has no Actions tab and never switches tabs on its own when a tool starts', () => {
    renderPanel();
    expect(screen.queryByText('Actions')).toBeNull();
    window.dispatchEvent(new CustomEvent('localmind:tool-call-started', { detail: { tool: 'shell' } }));
    expect(screen.getAllByTestId('session-row').length).toBeGreaterThan(0); // still on Chat
  });

  it('expands a chat to list its workspace artifacts', async () => {
    const entries = [
      { name: 'notes.txt', type: 'file' as const, path: '/tmp/ws/notes.txt', relPath: 'notes.txt', size: 42, modified: '' },
      { name: 'sub', type: 'folder' as const, path: '/tmp/ws/sub', relPath: 'sub', size: 0, modified: '' },
    ];
    vi.spyOn(client, 'getSessionFiles').mockResolvedValue(entries);
    renderPanel();
    fireEvent.click(screen.getByTestId('session-files-toggle-a'));
    // Files appear after the async fetch resolves.
    expect(await screen.findByText('notes.txt')).toBeInTheDocument();
    expect(screen.getByText('sub')).toBeInTheDocument();
    expect(screen.getByTestId('session-files-a')).toBeInTheDocument();
    // Clicking a file opens the preview dialog.
    fireEvent.click(screen.getByText('notes.txt'));
    expect(await screen.findByText(/Preview/i)).toBeInTheDocument();
  });

  it('shows the empty state when a chat has no artifacts', async () => {
    vi.spyOn(client, 'getSessionFiles').mockResolvedValue([]);
    renderPanel();
    fireEvent.click(screen.getByTestId('session-files-toggle-a'));
    expect(await screen.findByText(/No files yet/i)).toBeInTheDocument();
  });

  it('no longer carries the task list or a running-tasks block (they live in the Activity rail)', () => {
    renderPanel();
    expect(screen.queryByText('Todos')).toBeNull();
    expect(screen.queryByText(/tasks? running/)).toBeNull();
  });
});
