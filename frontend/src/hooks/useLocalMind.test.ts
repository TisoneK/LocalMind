import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useChat } from './useLocalMind';

// Regression test for the Observe panel gap:
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
  getSessionHistory: vi.fn(),
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

  it('captures diff SSE events into fileDiffs and the assistant message', () => {
    const { result, onChunk, onDone, unmount } = renderChatWithCapturedStream();

    act(() => {
      onChunk()(JSON.stringify({
        type: 'diff',
        diff: {
          filePath: '/tmp/demo/a.txt',
          language: 'txt',
          hunks: [
            {
              filePath: '/tmp/demo/a.txt',
              oldStart: 1, oldLines: 1, newStart: 1, newLines: 1,
              lines: [{ type: 'removed', content: 'old line', oldLine: 1 }],
            },
          ],
          additions: 0,
          deletions: 1,
        },
      }));
    });

    // Per-path map populated for the preview dialog's Diff mode.
    expect(result.current.fileDiffs['/tmp/demo/a.txt']).toBeDefined();
    expect(result.current.fileDiffs['/tmp/demo/a.txt'].hunks.length).toBe(1);
    expect(result.current.fileDiffs['/tmp/demo/a.txt'].language).toBe('txt');
    // Also attached to the current assistant message so the inline DiffBlock renders.
    const last = result.current.messages[result.current.messages.length - 1];
    expect(last.role).toBe('assistant');
    expect(last.diffData?.filePath).toBe('/tmp/demo/a.txt');

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

  it('surfaces backend anomaly events in liveObservation.anomalies', () => {
    const { result, onChunk, onDone, unmount } = renderChatWithCapturedStream();

    act(() => {
      // The bridge emits anomalies as a top-level typed event.
      onChunk()(JSON.stringify({
        type: 'anomaly',
        anomaly: {
          kind: 'stall',
          severity: 'high',
          title: 'Turn stalled',
          detail: '108s of work produced only 23 output tokens',
          metrics: { latency_ms: 108600, completion_tokens: 23 },
        },
      }));
    });

    expect(result.current.liveObservation?.anomalies).toHaveLength(1);
    expect(result.current.liveObservation?.anomalies?.[0].kind).toBe('stall');
    expect(result.current.liveObservation?.anomalies?.[0].severity).toBe('high');
    expect(result.current.liveObservation?.anomalies?.[0].metrics?.latency_ms).toBe(108600);

    act(() => onDone());
    unmount();
  });

  it('routes the initialization acknowledgement into chat', () => {
    const { result, onChunk, onDone, unmount } = renderChatWithCapturedStream();

    act(() => {
      onChunk()(JSON.stringify({
        obs_event: {
          type: 'agent_initialization_ack',
          data: { acknowledgement: "I'll list all projects." },
        },
      }));
    });

    const last = result.current.messages[result.current.messages.length - 1];
    expect(last.role).toBe('assistant');
    expect(last.acknowledgement).toBe("I'll list all projects.");
    // The acknowledgement is a chat artifact, not answer content.
    expect(last.content).toBe('');

    act(() => onDone());
    unmount();
  });

  it('accumulates thinking across phase boundaries instead of wiping', () => {
    const { result, onChunk, onDone, unmount } = renderChatWithCapturedStream();

    act(() => {
      // Dispatcher phase reasoning streams first…
      onChunk()(JSON.stringify({ type: 'thinking_start' }));
      onChunk()(JSON.stringify({ type: 'thinking_token', thinking: 'UNDERSTANDING: user wants the git status' }));
      // …then the plan phase starts — the old code wiped the dispatcher's
      // reasoning here (thinkingContent = ''), making the pre-tool phase a
      // silent black box. It must now accumulate instead.
      onChunk()(JSON.stringify({ type: 'thinking_start' }));
      onChunk()(JSON.stringify({ type: 'thinking_token', thinking: 'STEPS: 1. run git status' }));
      onChunk()(JSON.stringify({ type: 'thinking_end' }));
    });

    const last = result.current.messages[result.current.messages.length - 1];
    expect(last.isAgent).toBe(true);
    expect(last.thinking).toContain('UNDERSTANDING: user wants the git status');
    expect(last.thinking).toContain('STEPS: 1. run git status');

    act(() => onDone());
    unmount();
  });

  it('dedupes anomaly events by kind, newest wins', () => {
    const { result, onChunk, onDone, unmount } = renderChatWithCapturedStream();

    act(() => {
      onChunk()(JSON.stringify({
        type: 'anomaly',
        anomaly: { kind: 'stall', severity: 'high', title: 'Turn stalled', detail: 'first' },
      }));
      onChunk()(JSON.stringify({
        type: 'anomaly',
        anomaly: { kind: 'token_leak', severity: 'high', title: 'Context leaked', detail: 'second' },
      }));
      // Re-emitted stall (a later turn re-detected it) replaces the first.
      onChunk()(JSON.stringify({
        type: 'anomaly',
        anomaly: { kind: 'stall', severity: 'high', title: 'Turn stalled', detail: 'third' },
      }));
    });

    expect(result.current.liveObservation?.anomalies).toHaveLength(2);
    const stall = result.current.liveObservation?.anomalies?.find((a) => a.kind === 'stall');
    expect(stall?.detail).toBe('third');

    act(() => onDone());
    unmount();
  });

  // ── Session stats ─────────────────────
  // The bottom-right corner accumulates per-chat totals (summed tokens,
  // weighted speed, average latency) while each bubble keeps its own
  // per-message line. These tests drive real wire-shaped turn_complete
  // events through the hook and assert the accumulation semantics.

  it('accumulates a completed turn into sessionStats (stats split)', () => {
    const { result, onChunk, onDone, unmount } = renderChatWithCapturedStream();

    act(() => {
      onChunk()(JSON.stringify({
        obs_event: {
          type: 'turn_complete',
          data: {
            intent: 'chat',
            confidence: 0.9,
            tokens_approx: 9,
            prompt_tokens_approx: 3500,
            total_latency_ms: 2300,
          },
        },
      }));
    });
    // The harness exposes onDone as a getter — call the returned function.
    act(() => onDone()());

    const s = result.current.sessionStats;
    expect(s.turnCount).toBe(1);
    expect(s.promptTokens).toBe(3500);
    expect(s.completionTokens).toBe(9);
    expect(s.latencyMs).toBe(2300);
    // Weighted-speed inputs: generation time ≈ completion / tok-per-sec.
    expect(s.genTimeMs).toBeGreaterThan(0);

    unmount();
  });

  it('sums across turns instead of showing only the last turn', () => {
    const { result, onChunk, onDone, unmount } = renderChatWithCapturedStream();

    // Turn 1
    act(() => {
      onChunk()(JSON.stringify({
        obs_event: {
          type: 'turn_complete',
          data: { tokens_approx: 9, prompt_tokens_approx: 3500, total_latency_ms: 2300 },
        },
      }));
    });
    act(() => onDone()());

    // Turn 2 (retry / follow-up)
    act(() => {
      result.current.send('Show me the diff');
    });
    act(() => {
      onChunk()(JSON.stringify({
        obs_event: {
          type: 'turn_complete',
          data: { tokens_approx: 20, prompt_tokens_approx: 4000, total_latency_ms: 5000 },
        },
      }));
    });
    act(() => onDone()());

    const s = result.current.sessionStats;
    expect(s.turnCount).toBe(2);
    expect(s.promptTokens).toBe(7500);
    expect(s.completionTokens).toBe(29);
    expect(s.latencyMs).toBe(7300);

    unmount();
  });

  it('a late metrics upgrade replaces — not double-counts — the same turn', () => {
    const { result, onChunk, onDone, unmount } = renderChatWithCapturedStream();

    act(() => {
      onChunk()(JSON.stringify({
        obs_event: {
          type: 'turn_complete',
          data: { tokens_approx: 9, prompt_tokens_approx: 3500, total_latency_ms: 2300 },
        },
      }));
    });
    act(() => onDone()());

    // The backend upgrades the SAME turn with exact usage after the stream
    // ends. The accumulated totals must replace, not add on top.
    act(() => {
      onChunk()(JSON.stringify({
        obs_event: {
          type: 'turn_complete',
          data: { tokens_approx: 15, prompt_tokens_approx: 4200, total_latency_ms: 2600 },
        },
      }));
    });

    const s = result.current.sessionStats;
    expect(s.turnCount).toBe(1);
    expect(s.promptTokens).toBe(4200);
    expect(s.completionTokens).toBe(15);
    expect(s.latencyMs).toBe(2600);

    unmount();
  });

  it('turn_complete provider_usage carries the per-category context breakdown', () => {
    const { result, onChunk, onDone, unmount } = renderChatWithCapturedStream();

    act(() => {
      onChunk()(JSON.stringify({
        obs_event: {
          type: 'turn_complete',
          data: {
            tokens_approx: 9,
            prompt_tokens_approx: 3500,
            total_latency_ms: 2300,
            provider_usage: {
              prompt_tokens: 3500,
              context_breakdown: { system_prompt: 1200, tool_schemas: 800, history: 1500 },
            },
          },
        },
      }));
    });
    act(() => onDone()());

    expect(result.current.lastMetrics?.contextBreakdown).toEqual({
      system_prompt: 1200,
      tool_schemas: 800,
      history: 1500,
    });

    unmount();
  });

  it('the final metrics event upgrades the breakdown in place', () => {
    const { result, onChunk, onDone, unmount } = renderChatWithCapturedStream();

    act(() => {
      onChunk()(JSON.stringify({
        obs_event: {
          type: 'turn_complete',
          data: {
            tokens_approx: 9,
            prompt_tokens_approx: 3500,
            total_latency_ms: 2300,
            provider_usage: { context_breakdown: { system_prompt: 1200 } },
          },
        },
      }));
    });
    act(() => onDone()());

    act(() => {
      onChunk()(JSON.stringify({
        type: 'metrics',
        metrics: {
          tokens_approx: 9,
          prompt_tokens_approx: 3500,
          total_latency_ms: 2300,
          context_breakdown: { system_prompt: 1200, tool_schemas: 800, history: 1500 },
        },
      }));
    });

    expect(result.current.lastMetrics?.contextBreakdown).toEqual({
      system_prompt: 1200,
      tool_schemas: 800,
      history: 1500,
    });

    unmount();
  });

  it('resetSession returns the context counter and stats to a clean slate', () => {
    const { result, onChunk, onDone, unmount } = renderChatWithCapturedStream();

    act(() => {
      onChunk()(JSON.stringify({
        obs_event: {
          type: 'turn_complete',
          data: { tokens_approx: 9, prompt_tokens_approx: 3500, total_latency_ms: 2300 },
        },
      }));
    });
    act(() => onDone()());

    // The previous turn left a context count and session totals behind.
    expect(result.current.lastMetrics?.promptTokens).toBe(3500);
    expect(result.current.sessionStats.promptTokens).toBe(3500);

    act(() => {
      result.current.resetSession();
    });

    expect(result.current.lastMetrics).toBeNull();
    expect(result.current.liveObservation).toBeNull();
    expect(result.current.sessionStats).toMatchObject({
      promptTokens: 0,
      completionTokens: 0,
      turnCount: 0,
    });

    unmount();
  });
});

describe('useChat error normalization', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    streamMock.getSessionHistory.mockResolvedValue([]);
  });

  it('stores the canonical error object on the message (never in content)', () => {
    const { result, onChunk, unmount } = renderChatWithCapturedStream();

    act(() => {
      onChunk()(JSON.stringify({
        type: 'error',
        error: {
          status: 'error',
          source: 'model_provider',
          provider: 'zen',
          code: 'rate_limit',
          message: 'The model provider has temporarily reached its usage limit. Try again in a few minutes or switch to another model.',
          retryable: true,
          raw: 'zen returned 429: {...}',
        },
      }));
    });

    const msgs = result.current.messages;
    const last = msgs[msgs.length - 1];
    expect(last.role).toBe('assistant');
    // The friendly card data lands on `error` — the raw payload never
    // becomes chat content.
    expect(last.error?.code).toBe('rate_limit');
    expect(last.error?.provider).toBe('zen');
    expect(last.error?.retryable).toBe(true);
    expect(last.content).toBe('');
    expect(last.content).not.toContain('zen returned');

    unmount();
  });

  it('keeps the legacy string fallback for old backends', () => {
    const { result, onChunk, unmount } = renderChatWithCapturedStream();

    act(() => {
      onChunk()(JSON.stringify({
        type: 'error',
        error: 'old backend: something broke',
      }));
    });

    const msgs = result.current.messages;
    const last = msgs[msgs.length - 1];
    expect(last.error).toBeUndefined();
    expect(last.content).toContain('⚠️');
    expect(last.content).toContain('old backend');

    unmount();
  });
});

describe('useChat Agent Workspace restore', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('restores the last turn run tree from history on session load', async () => {
    streamMock.getSessionHistory.mockResolvedValue([
      { id: 'm1', role: 'user', content: 'build a cli', timestamp: '10:00' },
      {
        id: 'm2',
        role: 'assistant',
        content: 'Done.',
        timestamp: '10:01',
        agentRuns: [
          {
            id: 'parent',
            name: 'parent',
            role: 'parent',
            task: 'build a cli',
            status: 'completed',
            depth: 0,
            startedAt: 1700000000000,
            completedAt: 1700000009000,
            tools: [{ id: 'tc-shell-iter1', name: 'shell', status: 'done', input: 'ls' }],
          },
          {
            id: 'run-123',
            name: 'research',
            role: 'child',
            parentId: 'parent',
            task: 'find docs',
            status: 'completed',
            depth: 1,
            startedAt: 1700000001000,
            completedAt: 1700000007000,
            tools: [],
          },
        ],
      },
    ]);

    // The hook loads history on mount and restores the run tree from the
    // last assistant message that carries one.
    const utils = renderHook(() => useChat('session-b'));
    await act(async () => {});

    expect(streamMock.getSessionHistory).toHaveBeenCalledWith('session-b');
    // The Agents tab tree is restored: parent + child runs.
    expect(utils.result.current.agentRuns).toHaveLength(2);
    expect(utils.result.current.agentRuns[0]).toMatchObject({ name: 'parent', role: 'parent' });
    expect(utils.result.current.agentRuns[1]).toMatchObject({ id: 'run-123', role: 'child', parentId: 'parent' });
    expect(utils.result.current.agentRuns[0].tools[0].name).toBe('shell');

    utils.unmount();
  });

  it('clears the run tree when history has no agentRuns', async () => {
    streamMock.getSessionHistory.mockResolvedValue([
      { id: 'm1', role: 'user', content: 'hi', timestamp: '10:00' },
      { id: 'm2', role: 'assistant', content: 'Hello!', timestamp: '10:01' },
    ]);

    const utils = renderHook(() => useChat('session-b'));
    await act(async () => {});

    expect(utils.result.current.agentRuns).toEqual([]);
    utils.unmount();
  });
});

describe('useChat Agents-tab lifecycle narration (bootup-telemetry)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    streamMock.getSessionHistory.mockResolvedValue([]);
  });

  it('attaches lifecycle obs events as phases on the parent run', () => {
    const { result, onChunk, onDone, unmount } = renderChatWithCapturedStream();

    act(() => {
      onChunk()(JSON.stringify({
        obs_event: { type: 'agent_initialization_start', data: { intent: 'analyze' } },
      }));
      onChunk()(JSON.stringify({
        obs_event: { type: 'agent_initialization_understanding', data: { understanding: 'wants the file listed' } },
      }));
      onChunk()(JSON.stringify({
        obs_event: { type: 'agent_initialization_ack', data: { acknowledgement: 'On it!' } },
      }));
      onChunk()(JSON.stringify({
        obs_event: { type: 'agent_initialization_done', data: { mode: 'execute', objective: 'list files' } },
      }));
      onChunk()(JSON.stringify({
        obs_event: { type: 'agent_loop_done', data: { direct: false, iterations: 3 } },
      }));
    });

    const parent = result.current.agentRuns.find((r) => r.role === 'parent');
    expect(parent).toBeDefined();
    const types = (parent?.phases ?? []).map((p) => p.type);
    expect(types).toEqual(['initializing', 'understanding', 'acknowledged', 'initialized', 'turn_done']);
    expect(parent!.phases![1].detail).toBe('wants the file listed');
    expect(parent!.phases![2].detail).toBe('On it!');
    expect(parent!.phases![4].detail).toBe('3 iterations');

    // lifecycle phases do NOT land in the chat phase strip (decision history only)
    onDone();
    unmount();
  });

  it('does not put lifecycle phases on the chat message agentPhases strip', () => {
    const { result, onChunk, onDone, unmount } = renderChatWithCapturedStream();

    act(() => {
      onChunk()(JSON.stringify({
        obs_event: { type: 'agent_initialization_start', data: { intent: 'analyze' } },
      }));
      onChunk()(JSON.stringify({
        obs_event: { type: 'agent_loop_done', data: { direct: true } },
      }));
      onChunk()(JSON.stringify({
        obs_event: { type: 'agent_loop_gate_passed', data: { intent: 'analyze' } },
      }));
    });

    const last = result.current.messages[result.current.messages.length - 1];
    const stripTypes = (last?.agentPhases ?? []).map((p) => p.type);
    // decision history only — lifecycle events stay off the chat strip
    expect(stripTypes).toEqual(['gate_passed']);

    onDone();
    unmount();
  });
});

describe('useChat child-agent lifecycle narration (bootup-telemetry follow-up)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    streamMock.getSessionHistory.mockResolvedValue([]);
  });

  it('routes child lifecycle obs events (agent-tagged) to the child run', () => {
    const { result, onChunk, onDone, unmount } = renderChatWithCapturedStream();

    act(() => {
      onChunk()(JSON.stringify({
        obs_event: {
          type: 'delegation_started',
          data: { target_agent: 'research', task: 'find the weather', run_id: 'run-123', depth: 1 },
        },
      }));
      onChunk()(JSON.stringify({
        obs_event: { type: 'agent_initialization_start', data: { intent: 'analyze', agent: 'research' } },
      }));
      onChunk()(JSON.stringify({
        obs_event: { type: 'agent_initialization_understanding', data: { understanding: 'wants the weather', agent: 'research' } },
      }));
      onChunk()(JSON.stringify({
        obs_event: { type: 'agent_initialization_done', data: { mode: 'execute', agent: 'research' } },
      }));
      // parent's own lifecycle stays on the parent
      onChunk()(JSON.stringify({
        obs_event: { type: 'agent_loop_done', data: { direct: false, iterations: 4 } },
      }));
    });

    const child = result.current.agentRuns.find((r) => r.id === 'run-123');
    expect(child).toBeDefined();
    expect((child?.phases ?? []).map((p) => p.type)).toEqual(['initializing', 'understanding', 'initialized']);
    expect(child!.phases![1].detail).toBe('wants the weather');

    const parent = result.current.agentRuns.find((r) => r.role === 'parent');
    expect((parent?.phases ?? []).map((p) => p.type)).toEqual(['turn_done']);

    onDone();
    unmount();
  });
});

// Thinking time must EXCLUDE tool-execution time. Thinking spans
// multiple model calls with tools between them; measuring (last − first)
// thinking-token wall time double-counted the tool time, so "Thinking Ns" + the
// per-tool durations summed to more than the turn. The timer now pauses while a
// tool runs.
describe('useChat thinking timer excludes tool time', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    streamMock.getSessionHistory.mockResolvedValue([]);
  });

  it('pauses thinkMs during tool execution (no double-count)', () => {
    vi.useFakeTimers();
    vi.setSystemTime(1_000_000);
    try {
      const { result, onChunk, onDone, unmount } = renderChatWithCapturedStream();

      act(() => {
        onChunk()(JSON.stringify({ type: 'thinking_start' }));
        onChunk()(JSON.stringify({ type: 'thinking_token', thinking: 'plan the search ' }));
      });
      vi.setSystemTime(1_005_000);  // 5s of active thinking
      act(() => {
        onChunk()(JSON.stringify({ type: 'thinking_token', thinking: 'still planning ' }));
        // tool starts → thinking pauses
        onChunk()(JSON.stringify({ type: 'tool_call', tool_call: { id: 't1', name: 'web_search', status: 'started' } }));
      });
      vi.setSystemTime(1_017_000);  // 12s of tool time (must NOT count as thinking)
      act(() => {
        onChunk()(JSON.stringify({ type: 'tool_call', tool_call: { id: 't1', name: 'web_search', status: 'done', latency_ms: 12000 } }));
        // status_update fires during/after the tool — must not advance thinkMs
        onChunk()(JSON.stringify({ type: 'status_update', status: 'Reading results…' }));
      });
      vi.setSystemTime(1_020_000);  // thinking resumes for 3s
      act(() => {
        onChunk()(JSON.stringify({ type: 'thinking_token', thinking: 'synthesize ' }));
      });
      vi.setSystemTime(1_023_000);
      act(() => {
        onChunk()(JSON.stringify({ type: 'thinking_end' }));
        onDone();
      });

      const assistant = [...result.current.messages].reverse().find((m) => m.role === 'assistant');
      expect(assistant).toBeDefined();
      // Active thinking = 5s (first segment) + 3s (after the tool) = 8s.
      // The 12s tool gap is excluded. The naive (last−first) span would be 23s.
      expect(assistant!.thinkMs).toBe(8000);
      unmount();
    } finally {
      vi.useRealTimers();
    }
  });
});
