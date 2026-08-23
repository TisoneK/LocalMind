/**
 * B-2026-08-23-18: the Files-tab browser (FileExplorer v2).
 *
 * Tree rendering with lazy-loaded folder children, debounced search,
 * per-file actions (preview/download/delete) and the refresh callback
 * after a delete.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { FileExplorer } from './FileExplorer';
import { localmindClient as client } from '@/lib/localmind/client';
import type { FileNode } from '@/types';

const rootFiles: FileNode[] = [
  { name: 'notes.txt', type: 'file', path: '/tmp/home/notes.txt' },
  { name: 'docs', type: 'folder', path: '/tmp/home/docs' },
];

function renderExplorer(over: Partial<React.ComponentProps<typeof FileExplorer>> = {}) {
  const props = { files: rootFiles, ...over };
  render(<FileExplorer {...props} />);
  return props;
}

describe('FileExplorer browser', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the root tree with files and folders', () => {
    renderExplorer();
    expect(screen.getByTestId('file-row-notes.txt')).toBeInTheDocument();
    expect(screen.getByText('docs')).toBeInTheDocument();
  });

  it('lazily loads folder children on expand', async () => {
    vi.spyOn(client, 'getFileTree').mockResolvedValue([
      { name: 'report.md', type: 'file', path: '/tmp/home/docs/report.md' },
    ]);
    renderExplorer();
    fireEvent.click(screen.getByText('docs'));
    expect(await screen.findByTestId('file-row-report.md')).toBeInTheDocument();
    expect(client.getFileTree).toHaveBeenCalledWith('/tmp/home/docs');
  });

  it('expanding a folder that has no children shows Empty', async () => {
    vi.spyOn(client, 'getFileTree').mockResolvedValue([]);
    renderExplorer();
    fireEvent.click(screen.getByText('docs'));
    expect(await screen.findByText('Empty')).toBeInTheDocument();
  });

  it('searches via the client and renders matching files', async () => {
    vi.spyOn(client, 'searchFiles').mockResolvedValue([
      { name: 'report.md', type: 'file', path: '/tmp/home/docs/report.md', relPath: 'docs/report.md', size: 12, modified: '' },
    ]);
    renderExplorer();
    fireEvent.change(screen.getByTestId('file-search'), { target: { value: 'report' } });
    expect(await screen.findByTestId('search-result-report.md')).toBeInTheDocument();
    expect(client.searchFiles).toHaveBeenCalledWith('/tmp/home', 'report');
  });

  it('shows the no-matches state for an empty result set', async () => {
    vi.spyOn(client, 'searchFiles').mockResolvedValue([]);
    renderExplorer();
    fireEvent.change(screen.getByTestId('file-search'), { target: { value: 'zzz' } });
    expect(await screen.findByText(/No matches for/)).toBeInTheDocument();
  });

  it('clears search and returns to the tree', async () => {
    vi.spyOn(client, 'searchFiles').mockResolvedValue([]);
    renderExplorer();
    fireEvent.change(screen.getByTestId('file-search'), { target: { value: 'zzz' } });
    expect(await screen.findByText(/No matches for/)).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('file-search-clear'));
    await waitFor(() => expect(screen.getByTestId('file-tree')).toBeInTheDocument());
  });

  it('delete requires confirmation, deletes, and calls onFilesChanged', async () => {
    const onFilesChanged = vi.fn();
    vi.spyOn(client, 'deleteFile').mockResolvedValue(undefined);
    renderExplorer({ onFilesChanged });
    fireEvent.click(screen.getByTestId('delete-notes.txt'));
    expect(screen.getByTestId('delete-confirm')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('delete-confirm-yes'));
    await waitFor(() => expect(client.deleteFile).toHaveBeenCalledWith('/tmp/home/notes.txt'));
    expect(onFilesChanged).toHaveBeenCalledTimes(1);
  });

  it('canceling the delete confirmation does not delete', async () => {
    const onFilesChanged = vi.fn();
    const del = vi.spyOn(client, 'deleteFile').mockResolvedValue(undefined);
    renderExplorer({ onFilesChanged });
    fireEvent.click(screen.getByTestId('delete-notes.txt'));
    fireEvent.click(screen.getByText('Cancel'));
    expect(del).not.toHaveBeenCalled();
    expect(onFilesChanged).not.toHaveBeenCalled();
  });

  it('download action triggers a browser download', async () => {
    const download = vi.spyOn(client, 'downloadFile').mockImplementation(() => {});
    renderExplorer();
    fireEvent.click(screen.getByTestId('download-notes.txt'));
    expect(download).toHaveBeenCalledWith('/tmp/home/notes.txt');
  });
});
