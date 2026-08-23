/**
 * B-2026-08-23-14: MemoryTab wired to the real memory backend.
 *
 * Covers the store-fact affordance (onStore → POST /api/memory), the filter
 * box, empty state, and delete.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryTab } from './MemoryTab';
import type { MemoryFact } from '@/types';

const facts: MemoryFact[] = [
  { id: 'f1', content: 'User prefers dark mode', source: 'user', relevance: 0.95, timestamp: '1720000000000' },
  { id: 'f2', content: 'Project uses FastAPI', source: 'agent', relevance: 0.8, timestamp: '1720000000001' },
];

function renderTab(over: Partial<React.ComponentProps<typeof MemoryTab>> = {}) {
  const props = { facts, ...over };
  render(<MemoryTab {...props} />);
  return props;
}

describe('MemoryTab', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders facts with stats and delete buttons', () => {
    const onDelete = vi.fn();
    renderTab({ onDelete });
    expect(screen.getByText('User prefers dark mode')).toBeInTheDocument();
    expect(screen.getByText('Project uses FastAPI')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument(); // fact count
    expect(screen.getByText('88%')).toBeInTheDocument(); // avg relevance
  });

  it('stores a fact through onStore and clears the draft', async () => {
    const onStore = vi.fn().mockResolvedValue(undefined);
    renderTab({ onStore });
    fireEvent.change(screen.getByTestId('memory-store-input'), {
      target: { value: 'User works from UTC+3' },
    });
    fireEvent.click(screen.getByTestId('memory-store-button'));
    await waitFor(() => expect(onStore).toHaveBeenCalledWith('User works from UTC+3', 'manual'));
    expect(screen.getByTestId('memory-store-input')).toHaveValue('');
  });

  it('shows an error when storing fails', async () => {
    const onStore = vi.fn().mockRejectedValue(new Error('boom'));
    renderTab({ onStore });
    fireEvent.change(screen.getByTestId('memory-store-input'), { target: { value: 'x' } });
    fireEvent.click(screen.getByTestId('memory-store-button'));
    expect(await screen.findByText('Failed to store fact')).toBeInTheDocument();
  });

  it('disables the store button while empty or storing', () => {
    const onStore = vi.fn().mockResolvedValue(undefined);
    renderTab({ onStore });
    const button = screen.getByTestId('memory-store-button');
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByTestId('memory-store-input'), { target: { value: 'x' } });
    expect(button).toBeEnabled();
  });

  it('filters facts by content and source', () => {
    renderTab();
    fireEvent.change(screen.getByTestId('memory-filter'), { target: { value: 'dark' } });
    expect(screen.getByText('User prefers dark mode')).toBeInTheDocument();
    expect(screen.queryByText('Project uses FastAPI')).not.toBeInTheDocument();
    // Filter by source
    fireEvent.change(screen.getByTestId('memory-filter'), { target: { value: 'agent' } });
    expect(screen.getByText('Project uses FastAPI')).toBeInTheDocument();
    expect(screen.queryByText('User prefers dark mode')).not.toBeInTheDocument();
  });

  it('shows the filter-empty state for no matches', () => {
    renderTab();
    fireEvent.change(screen.getByTestId('memory-filter'), { target: { value: 'zzz' } });
    expect(screen.getByTestId('memory-filter-empty')).toBeInTheDocument();
  });

  it('shows the empty state when there are no facts', () => {
    renderTab({ facts: [] });
    expect(screen.getByTestId('memory-empty')).toBeInTheDocument();
    expect(screen.getByText('0')).toBeInTheDocument(); // count
  });

  it('deletes a fact through onDelete', () => {
    const onDelete = vi.fn();
    renderTab({ onDelete });
    fireEvent.click(screen.getAllByTitle('Delete fact')[0]);
    expect(onDelete).toHaveBeenCalledWith('f1');
  });
});

describe('MemoryTab fact editing (B-2026-08-23-14 follow-up)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('edits a fact through onEdit and exits edit mode', async () => {
    const onEdit = vi.fn().mockResolvedValue(undefined);
    renderTab({ onEdit });
    fireEvent.click(screen.getByTestId('fact-edit-btn-f1'));
    const input = screen.getByTestId('fact-edit-input-f1');
    expect(input).toBeInTheDocument();
    fireEvent.change(input, { target: { value: 'User prefers dark mode with warm light' } });
    fireEvent.click(screen.getByTestId('fact-edit-save-f1'));
    await waitFor(() => expect(onEdit).toHaveBeenCalledWith('f1', 'User prefers dark mode with warm light'));
    // Back to the read view (edit mode exited).
    expect(screen.queryByTestId('fact-edit-input-f1')).not.toBeInTheDocument();
    expect(screen.getByText('User prefers dark mode')).toBeInTheDocument();
  });

  it('cancel discards the edit without calling onEdit', () => {
    const onEdit = vi.fn();
    renderTab({ onEdit });
    fireEvent.click(screen.getByTestId('fact-edit-btn-f1'));
    fireEvent.change(screen.getByTestId('fact-edit-input-f1'), { target: { value: 'changed text' } });
    fireEvent.click(screen.getByTestId('fact-edit-cancel-f1'));
    expect(onEdit).not.toHaveBeenCalled();
    expect(screen.queryByTestId('fact-edit-input-f1')).not.toBeInTheDocument();
  });

  it('shows an error when saving the edit fails', async () => {
    const onEdit = vi.fn().mockRejectedValue(new Error('boom'));
    renderTab({ onEdit });
    fireEvent.click(screen.getByTestId('fact-edit-btn-f1'));
    fireEvent.change(screen.getByTestId('fact-edit-input-f1'), { target: { value: 'new text' } });
    fireEvent.click(screen.getByTestId('fact-edit-save-f1'));
    expect(await screen.findByText('Failed to save the correction')).toBeInTheDocument();
  });
});
