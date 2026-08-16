/**
 * Tests for LeftPanel multi-select chat management: mark multiple chats →
 * bulk delete or export.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { LeftPanel } from './LeftPanel';
import type { Session } from '@/types';

const sessions: Session[] = [
  { id: 'a', title: 'Chat A', lastMessage: 'x', timestamp: '1', messageCount: 1, active: false },
  { id: 'b', title: 'Chat B', lastMessage: 'y', timestamp: '2', messageCount: 2, active: false },
  { id: 'c', title: 'Chat C', lastMessage: 'z', timestamp: '3', messageCount: 3, active: false },
];

function renderPanel(over: Partial<React.ComponentProps<typeof LeftPanel>> = {}) {
  const props = {
    sessions,
    actions: [],
    files: [],
    todos: [],
    activeToolCalls: [],
    models: [],
    selectedModel: 'm',
    onModelChange: vi.fn(),
    currentSessionId: null,
    onSelectSession: vi.fn(),
    onNewChat: vi.fn(),
    onDeleteSession: vi.fn(),
    onDeleteSessions: vi.fn(),
    onExportSessions: vi.fn(),
    onToggleTodo: vi.fn(),
    onAddTodo: vi.fn(),
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
      actions: [],
      files: [],
      todos: [],
      activeToolCalls: [],
      models: [],
      selectedModel: 'm',
      onModelChange: vi.fn(),
      currentSessionId: null,
      onSelectSession: vi.fn(),
      onNewChat: vi.fn(),
      onDeleteSession: vi.fn(),
      onDeleteSessions: vi.fn(),
      onExportSessions: vi.fn(),
      onToggleTodo: vi.fn(),
      onAddTodo: vi.fn(),
    };
    const { rerender } = render(<LeftPanel {...baseProps} />);
    // Leave the Chat tab first so the switch is observable.
    fireEvent.click(screen.getByText('Actions'));
    expect(screen.getByText('Actions will appear here during execution.')).toBeInTheDocument();

    const onChatTabShown = vi.fn();
    rerender(<LeftPanel {...baseProps} forceChatTab onChatTabShown={onChatTabShown} />);

    expect(screen.getAllByTestId('session-row')).toHaveLength(3);
    expect(onChatTabShown).toHaveBeenCalledTimes(1);
  });

  it('shows live/active actions as expandable cards, not pills', () => {
    renderPanel({
      actions: [
        { id: 'a1', type: 'shell', label: 'Run command', detail: 'ls', status: 'done', timestamp: '09:00', iteration: 1 },
      ],
      // A non-empty activeToolCalls used to force the compact pill branch.
      activeToolCalls: [
        { id: 'call_1', name: 'shell', status: 'done', input: 'ls', label: '', duration: undefined },
      ],
    });
    fireEvent.click(screen.getByText('Actions'));
    // The ActionHistory card renders the real action label + chain header;
    // the old pill path showed the raw tool name ('Shell') instead.
    expect(screen.getByText('Run command')).toBeInTheDocument();
    expect(screen.getByText('1 step')).toBeInTheDocument();
  });
});
