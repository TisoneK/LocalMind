import { describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { isPaletteShortcut } from '@/lib/localmind/paletteShortcut';
import { CommandPalette } from './CommandPalette';
import { localmindClient } from '@/lib/localmind/client';

const sessions = [
  { id: 's1', title: 'Weather in Nairobi', lastMessage: '', timestamp: '', messageCount: 2, active: false },
  { id: 's2', title: 'Disk check', lastMessage: '', timestamp: '', messageCount: 2, active: false },
];
const props = (o = {}) => ({
  sessions,
  currentSessionId: 's1',
  isStreaming: false,
  onSelectSession: vi.fn(),
  onNewChat: vi.fn(),
  onAbort: vi.fn(),
  onToggleRightPanel: vi.fn(),
  ...o,
});

describe('CommandPalette', () => {
  it('recognises ⌘K and Ctrl+K', () => {
    expect(isPaletteShortcut({ key: 'k', metaKey: true, ctrlKey: false })).toBe(true);
    expect(isPaletteShortcut({ key: 'K', metaKey: false, ctrlKey: true })).toBe(true);
    expect(isPaletteShortcut({ key: 'k', metaKey: false, ctrlKey: false })).toBe(false);
  });

  it('opens on the shortcut and lists chats and actions', () => {
    render(<CommandPalette {...props()} />);
    expect(screen.queryByText('New chat')).toBeNull();
    act(() => {
      fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    });
    expect(screen.getByText('New chat')).toBeInTheDocument();
    expect(screen.getByText('Disk check')).toBeInTheDocument();
  });

  it('offers Stop only while the agent is running', () => {
    const { unmount } = render(<CommandPalette {...props()} />);
    act(() => {
      fireEvent.keyDown(window, { key: 'k', metaKey: true });
    });
    expect(screen.queryByText('Stop the agent')).toBeNull();
    unmount();
    render(<CommandPalette {...props({ isStreaming: true })} />);
    act(() => {
      fireEvent.keyDown(window, { key: 'k', metaKey: true });
    });
    expect(screen.getByText('Stop the agent')).toBeInTheDocument();
  });
});

describe('CommandPalette message search', () => {
  it('shows chats whose messages match what you typed, with a snippet', async () => {
    vi.spyOn(localmindClient, 'searchChats').mockResolvedValue([
      { id: 's9', title: 'Trip planning', snippet: '…pack the sunscreen for Mombasa' },
    ]);
    render(<CommandPalette {...props()} />);
    act(() => {
      fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    });
    const box = screen.getByPlaceholderText(/search chats/i);
    act(() => {
      fireEvent.change(box, { target: { value: 'sunscreen' } });
    });
    expect(await screen.findByText(/pack the sunscreen/, {}, { timeout: 2000 })).toBeInTheDocument();
    expect(screen.getByText('Trip planning')).toBeInTheDocument();
  });
});
