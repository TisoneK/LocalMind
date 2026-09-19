import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { useTodos } from './useLocalMind';

// The plan's tasks must survive the moment a turn ends and the moment a new chat gets its
// session id. A new chat's id is created when the first message is sent, which makes the hook
// fetch that chat's saved tasks — an empty list at that point. If the plan's live events
// arrive before that fetch returns, the stale empty result used to wipe them.

const client = vi.hoisted(() => ({
  getTodos: vi.fn(),
  createTodo: vi.fn(),
  updateTodo: vi.fn(),
  deleteTodo: vi.fn(),
}));

vi.mock('@/lib/localmind/client', () => ({
  localmindClient: client,
  classifyClientIntent: () => 'chat',
}));

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const created = (id: string, text: string) =>
  window.dispatchEvent(new CustomEvent('localmind:todo-created', { detail: { id, text, completed: false } }));

beforeEach(() => {
  vi.clearAllMocks();
});

describe('useTodos', () => {
  it('keeps live tasks when the first fetch for a new chat returns empty afterwards', async () => {
    const first = deferred<never[]>();
    client.getTodos.mockReturnValueOnce(first.promise);
    const { result } = renderHook(() => useTodos('new-chat'));

    act(() => created('plan-0', 'Write the file'));
    expect(result.current.todos.map((t) => t.id)).toEqual(['plan-0']);

    await act(async () => {
      first.resolve([]); // the stale, empty answer
      await first.promise;
    });
    expect(result.current.todos.map((t) => t.id)).toEqual(['plan-0']);
  });

  it('still shows the saved tasks when nothing live arrived', async () => {
    client.getTodos.mockResolvedValueOnce([{ id: 'plan-0', text: 'Saved', completed: true }]);
    const { result } = renderHook(() => useTodos('s1'));
    await waitFor(() => expect(result.current.todos.map((t) => t.text)).toEqual(['Saved']));
    expect(result.current.loading).toBe(false);
  });

  it('re-syncs from the database when the turn ends', async () => {
    client.getTodos.mockResolvedValueOnce([]);
    const { result } = renderHook(() => useTodos('s1'));
    await waitFor(() => expect(result.current.loading).toBe(false));

    client.getTodos.mockResolvedValueOnce([{ id: 'plan-0', text: 'Done step', completed: true }]);
    await act(async () => {
      window.dispatchEvent(new CustomEvent('localmind:todo-refetch'));
    });
    await waitFor(() => expect(result.current.todos.map((t) => t.text)).toEqual(['Done step']));
  });

  it('stops loading, and keeps what it has, when the fetch fails', async () => {
    client.getTodos.mockRejectedValueOnce(new Error('offline'));
    const { result } = renderHook(() => useTodos('s1'));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.todos).toEqual([]);
  });

  it('ignores a slow answer for a chat the user has already left', async () => {
    const slow = deferred<{ id: string; text: string; completed: boolean }[]>();
    client.getTodos.mockReturnValueOnce(slow.promise);
    client.getTodos.mockResolvedValueOnce([{ id: 'b-0', text: 'Chat B task', completed: false }]);
    const { result, rerender } = renderHook(({ id }) => useTodos(id), { initialProps: { id: 'a' } });
    rerender({ id: 'b' });
    await waitFor(() => expect(result.current.todos.map((t) => t.text)).toEqual(['Chat B task']));

    await act(async () => {
      slow.resolve([{ id: 'a-0', text: 'Chat A task', completed: false }]);
      await slow.promise;
    });
    expect(result.current.todos.map((t) => t.text)).toEqual(['Chat B task']);
  });
});
