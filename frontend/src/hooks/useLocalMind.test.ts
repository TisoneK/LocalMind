import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useChat } from './useLocalMind';

// Regression test for the Observe panel gap (B-2026-08-09-17 follow-up):
// the backend emits structured obs events as {"obs_event": {...}} with NO
// top-level "type" (backend/src/core/obs.py ObsEvent.to_sse_dict). The
// frontend SSE switch dispatched only on parsed.type, so case 'obs_event'
// was dead code — stage_timing / turn_complete events (which carry
// confidence, prompt/context token counts, real stage latency + status)
// were silently dropped and the panel fell back to a stale one-shot poll.
//
// These tests drive real wire-shaped payloads through the hook's onChunk
// callback (captured from a mocked localmindClient.streamChat) and assert
// that liveObservation picks up confidence / context tokens / stage
// timings / latency.

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

function renderChatWithCapturedStream() {
  let onChunk: OnChunk = () => {};
  let onDone: () => void = () => {};
  streamMock.streamChat.mockImplementation(
    (_msg: string, _session: string, chunk: OnChunk, done: () => void) => {
      onChunk = chunk;
      onDone = done;
      return () => {};
    }
  );
  const utils = renderHook(() => useChat('test-session'));
  act(() => {
    utils.result.current.send('Hi there!');
  });
  return {
    result: utils.result,
    onChunk: () => onChunk,
    onDone: () => onDone,
    unmount: utils.unmount,
  };
}

describe('useChat SSE obs_event routing', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    streamMock.getSessionHistory.mockResolvedValue([]);
  });

  it('routes backend {"obs_event": {...}} payloads (no top-level type) into liveObservation', () => {
    const { result, onChunk, onDone, unmount } = renderChatWithCapturedStream();

    act(() => {
      onChunk()(JSON.stringify({
        obs_event: { type: 'stage_timing', data: { stage: 'tool_select', latency_ms: 0, status: 'skipped' } },
      }));
      onChunk()(JSON.stringify({
        obs_event: {
          type: 'turn_complete',
          data: {
            intent: 'chat',
            confidence: 0.99,
            tokens_approx: 9,
            prompt_tokens_approx: 3500,
            total_latency_ms: 2300,
            memory_facts: 0,
            agent_mode: false,
          },
        },
      }));
    });

    const live = result.current.liveObservation;
    expect(live).not.toBeNull();
    expect(live?.confidence).toBe(0.99);
    expect(live?.contextTokens).toBe(3500);
    expect(live?.latency).toBe(2300);
    expect(live?.intent).toBe('chat');
    expect(live?.stageTimings?.tool_select).toEqual({ latencyMs: 0, status: 'skipped' });

    act(() => onDone());
    unmount();
  });

  it('does not leak completion tokens as context tokens when the prompt count is absent', () => {
    const { result, onChunk, onDone, unmount } = renderChatWithCapturedStream();

    act(() => {
      onChunk()(JSON.stringify({
        obs_event: {
          type: 'turn_complete',
          // Fast-path shape: no prompt_tokens_approx, only completion tokens_approx.
          data: {
            intent: 'chat',
            confidence: 0.99,
            tokens_approx: 9,
            total_latency_ms: 2300,
            memory_facts: 0,
            agent_mode: false,
          },
        },
      }));
    });

    const live = result.current.liveObservation;
    // The completion count (9) must NOT be displayed as context tokens.
    expect(live?.contextTokens).toBe(0);
    // Confidence still flows even without a prompt count — the "—" fix.
    expect(live?.confidence).toBe(0.99);

    act(() => onDone());
    unmount();
  });

  it('keeps confidence populated when stage_timing arrives before turn_complete', () => {
    const { result, onChunk, onDone, unmount } = renderChatWithCapturedStream();

    act(() => {
      onChunk()(JSON.stringify({
        obs_event: { type: 'stage_timing', data: { stage: 'intent_classify', latency_ms: 2767, status: 'done' } },
      }));
      onChunk()(JSON.stringify({
        obs_event: {
          type: 'turn_complete',
          data: {
            intent: 'chat',
            confidence: 0.98,
            tokens_approx: 15,
            prompt_tokens_approx: 1800,
            total_latency_ms: 3900,
            memory_facts: 0,
            agent_mode: false,
          },
        },
      }));
    });

    const live = result.current.liveObservation;
    expect(live?.confidence).toBe(0.98);
    expect(live?.contextTokens).toBe(1800);
    expect(live?.stageTimings?.intent_classify).toEqual({ latencyMs: 2767, status: 'done' });

    act(() => onDone());
    unmount();
  });

  it('still routes top-level typed payloads through parsed.type (non-regression)', () => {
    const { result, onChunk, onDone, unmount } = renderChatWithCapturedStream();

    act(() => {
      // The backend wraps intent_classified as a typed {"type": "intent"}
      // event — the switch fallback must not break this path.
      onChunk()(JSON.stringify({ type: 'intent', intent: 'chat', confidence: 0.85 }));
    });

    expect(result.current.currentIntent).toBe('chat');
    expect(result.current.currentConfidence).toBe(0.85);
    expect(result.current.liveObservation?.intent).toBe('chat');
    expect(result.current.liveObservation?.confidence).toBe(0.85);

    act(() => onDone());
    unmount();
  });
});
