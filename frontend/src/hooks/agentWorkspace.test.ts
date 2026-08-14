import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useChat } from './useLocalMind';

const streamMock = vi.hoisted(() => ({
  streamChat: vi.fn(),
  getSessionHistory: vi.fn(async () => []),
  steer: vi.fn(),
  abort: vi.fn(),
  classifyClientIntent: vi.fn(() => 'chat'),
}));

vi.mock('@/lib/localmind/client', () => ({
  localmindClient: {
    streamChat: streamMock.streamChat,
    getSessionHistory: streamMock.getSessionHistory,
    steer: streamMock.steer,
    abort: streamMock.abort,
  },
  classifyClientIntent: streamMock.classifyClientIntent,
}));

type OnChunk = (rawData: string) => void;

it('the parent run owns delegation and child tool progress', () => {
  let onChunk: OnChunk = () => {};
  let onDone: () => void = () => {};
  streamMock.streamChat.mockImplementation(
    (_message: string, _session: string, chunk: OnChunk, done: () => void) => {
      onChunk = chunk;
      onDone = done;
      return () => {};
    },
  );

  const { result, unmount } = renderHook(() => useChat('agent-workspace-session'));
  act(() => result.current.send('Research the issue and summarize it'));

  const root = result.current.agentRuns[0];
  expect(root.role).toBe('parent');
  expect(root.depth).toBe(0);
  expect(root.status).toBe('running');

  act(() => {
    onChunk(JSON.stringify({
      obs_event: {
        type: 'delegation_started',
        data: {
          target_agent: 'research',
          task: 'Find the relevant upstream behavior',
          run_id: 'child-research-1',
          depth: 1,
        },
      },
    }));
    onChunk(JSON.stringify({
      type: 'tool_call',
      tool_call: {
        id: 'child-tool-1',
        name: 'web_search',
        label: 'Search upstream docs',
        status: 'started',
        agent: 'research',
        run_id: 'child-research-1',
        tool_args: 'LocalMind agent orchestration',
      },
    }));
  });

  const child = result.current.agentRuns.find((run) => run.id === 'child-research-1');
  expect(child?.parentId).toBe(root.id);
  expect(child?.name).toBe('research');
  expect(child?.status).toBe('running');
  expect(child?.tools).toHaveLength(1);
  expect(child?.tools[0].agent).toBe('research');

  act(() => {
    onChunk(JSON.stringify({
      obs_event: {
        type: 'delegation_completed',
        data: {
          target_agent: 'research',
          run_id: 'child-research-1',
          status: 'completed',
        },
      },
    }));
    onDone();
  });

  expect(result.current.agentRuns.find((run) => run.id === 'child-research-1')?.status).toBe('completed');
  expect(result.current.agentRuns.find((run) => run.id === root.id)?.status).toBe('completed');
  unmount();
});

describe('agent workspace stream setup', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    streamMock.getSessionHistory.mockResolvedValue([]);
  });

  it('clears the run tree when switching sessions', () => {
    let onChunk: OnChunk = () => {};
    streamMock.streamChat.mockImplementation(
      (_message: string, _session: string, chunk: OnChunk) => {
        onChunk = chunk;
        return () => {};
      },
    );
    const { result, rerender, unmount } = renderHook(
      ({ sessionId }: { sessionId: string | null }) => useChat(sessionId),
      { initialProps: { sessionId: 'session-a' as string | null } },
    );
    act(() => result.current.send('Start work'));
    expect(result.current.agentRuns).toHaveLength(1);
    act(() => onChunk(JSON.stringify({ type: 'tool_call', tool_call: { id: 'tool-1', name: 'shell', status: 'started' } })));
    act(() => rerender({ sessionId: null }));
    expect(result.current.agentRuns).toEqual([]);
    unmount();
  });
});
