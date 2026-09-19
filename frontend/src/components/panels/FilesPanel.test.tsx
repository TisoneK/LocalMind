import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { FilesPanel } from './FilesPanel';
import { localmindClient } from '@/lib/localmind/client';
import type { SessionFileEntry } from '@/types';

vi.mock('./FileExplorer', () => ({ FileExplorer: () => <div data-testid="explorer" /> }));

const entry = (relPath: string, modified: string, size = 12): SessionFileEntry => ({
  name: relPath.split('/').pop() as string,
  type: 'file',
  path: `/ws/${relPath}`,
  relPath,
  size,
  modified,
});

const ENTRIES = [
  entry('old.txt', '2026-09-18T09:00:00'),
  entry('src/new.py', '2026-09-19T12:00:00'),
  entry('.tmp/new.py', '2026-09-19T12:00:00'),
];

beforeEach(() => {
  vi.restoreAllMocks();
});

function renderPanel(over: Partial<React.ComponentProps<typeof FilesPanel>> = {}) {
  return render(<FilesPanel sessionId="s1" files={[]} onOpen={() => {}} {...over} />);
}

describe('FilesPanel', () => {
  it('lists this chat\'s files newest first and hides staging folders', async () => {
    vi.spyOn(localmindClient, 'getSessionFiles').mockResolvedValue(ENTRIES);
    renderPanel();
    const rows = await screen.findAllByTestId(/^chat-file-/);
    expect(rows.map((r) => r.getAttribute('data-testid'))).toEqual(['chat-file-new.py', 'chat-file-old.txt']);
    expect(screen.getByText(/src/)).toBeInTheDocument(); // its folder is shown
  });

  it('opens the file preview when a row is clicked', async () => {
    vi.spyOn(localmindClient, 'getSessionFiles').mockResolvedValue(ENTRIES);
    const onOpen = vi.fn();
    renderPanel({ onOpen });
    fireEvent.click(await screen.findByTestId('chat-file-old.txt'));
    expect(onOpen).toHaveBeenCalledWith('/ws/old.txt');
  });

  it('says so when the chat has no files yet', async () => {
    vi.spyOn(localmindClient, 'getSessionFiles').mockResolvedValue([]);
    renderPanel();
    expect(await screen.findByTestId('chat-files-empty')).toBeInTheDocument();
  });

  it('asks the user to start a chat when none is open', () => {
    const spy = vi.spyOn(localmindClient, 'getSessionFiles');
    renderPanel({ sessionId: null });
    expect(screen.getByText(/Start a chat/)).toBeInTheDocument();
    expect(spy).not.toHaveBeenCalled();
  });

  it('shows an error with a retry when loading fails', async () => {
    const spy = vi.spyOn(localmindClient, 'getSessionFiles').mockRejectedValueOnce(new Error('boom'));
    renderPanel();
    expect(await screen.findByText(/Couldn't load/)).toBeInTheDocument();
    spy.mockResolvedValue(ENTRIES);
    fireEvent.click(screen.getByText('Try again'));
    expect(await screen.findByTestId('chat-file-old.txt')).toBeInTheDocument();
  });

  it('filters by name and reports when nothing matches', async () => {
    vi.spyOn(localmindClient, 'getSessionFiles').mockResolvedValue(ENTRIES);
    renderPanel();
    await screen.findByTestId('chat-file-old.txt');
    const input = screen.getByLabelText("Filter this chat's files");
    fireEvent.change(input, { target: { value: 'old' } });
    expect(screen.queryByTestId('chat-file-new.py')).toBeNull();
    fireEvent.change(input, { target: { value: 'zzz' } });
    expect(screen.getByText(/No files match/)).toBeInTheDocument();
  });

  it('shows the diff counts the app captured for a file', async () => {
    vi.spyOn(localmindClient, 'getSessionFiles').mockResolvedValue(ENTRIES);
    renderPanel({
      fileDiffs: {
        '/ws/src/new.py': {
          hunks: [{ filePath: '/ws/src/new.py', oldStart: 0, oldLines: 0, newStart: 1, newLines: 1, lines: [{ type: 'added', content: 'x' }] }],
        } as never,
      },
    });
    expect(await screen.findByText('+1')).toBeInTheDocument();
  });

  it('confirms before deleting, then deletes and reloads', async () => {
    const list = vi.spyOn(localmindClient, 'getSessionFiles').mockResolvedValue(ENTRIES);
    const del = vi.spyOn(localmindClient, 'deleteFile').mockResolvedValue();
    renderPanel();
    await screen.findByTestId('chat-file-old.txt');
    fireEvent.click(screen.getByLabelText('Delete old.txt'));
    expect(del).not.toHaveBeenCalled();
    expect(screen.getByTestId('delete-confirm')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('delete-confirm-yes'));
    await waitFor(() => expect(del).toHaveBeenCalledWith('/ws/old.txt'));
    await waitFor(() => expect(list.mock.calls.length).toBeGreaterThan(1));
  });

  it('keeps browsing the rest of the machine one click away', async () => {
    vi.spyOn(localmindClient, 'getSessionFiles').mockResolvedValue(ENTRIES);
    renderPanel({ files: [{ name: 'Docs', type: 'folder', path: '/h/Docs' } as never] });
    await screen.findByTestId('chat-file-old.txt');
    expect(screen.queryByTestId('explorer')).toBeNull();
    fireEvent.click(screen.getByText('Browse all files'));
    expect(screen.getByTestId('explorer')).toBeInTheDocument();
  });
});
