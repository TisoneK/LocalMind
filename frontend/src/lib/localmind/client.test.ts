import { afterEach, describe, expect, it, vi } from 'vitest';
import { classifyClientIntent, localmindClient } from './client';

describe('getObservability', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('preserves the legacy shape when no structured snapshot is available', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        session_id: 'session-1',
        intent: null,
        confidence: null,
        tools_used: '',
        memory_hits: 0,
        context_tokens: 0,
        latency_ms: 0,
        tool_timeline: [],
        observation: null,
      }),
    }));

    await expect(localmindClient.getObservability('session-1')).resolves.toMatchObject({
      intent: 'chat',
      confidence: 0,
      toolsUsed: [],
      observation: null,
    });
  });

  it('maps grouped capability metadata into the frontend shape', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        families: [{
          id: 'execution',
          label: 'Execution',
          capabilities: [{
            id: 'shell',
            description: 'Run a system command',
            tool_names: ['shell'],
            cognitive: false,
          }],
        }],
      }),
    }));

    await expect(localmindClient.getCapabilities()).resolves.toEqual({
      families: [{
        id: 'execution',
        label: 'Execution',
        capabilities: [{
          id: 'shell',
          description: 'Run a system command',
          toolNames: ['shell'],
          cognitive: false,
        }],
      }],
    });
  });

  it('falls back to an empty capability catalog when discovery is unavailable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('backend unavailable')));

    await expect(localmindClient.getCapabilities()).resolves.toEqual({ families: [] });
  });

  it('skips malformed nested capability entries without losing valid metadata', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        families: [
          null,
          {
            id: 'execution',
            label: 'Execution',
            capabilities: [null, { id: 'shell', description: 'Run commands', tool_names: ['shell'] }],
          },
        ],
      }),
    }));

    await expect(localmindClient.getCapabilities()).resolves.toEqual({
      families: [{
        id: 'execution',
        label: 'Execution',
        capabilities: [{
          id: 'shell',
          description: 'Run commands',
          toolNames: ['shell'],
          cognitive: false,
        }],
      }],
    });
  });

  it('normalizes malformed snapshot fields without crashing the UI', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        session_id: 'session-2',
        intent: 'file',
        confidence: 0.9,
        tools_used: 'file_read',
        memory_hits: 1,
        context_tokens: 42,
        latency_ms: 125,
        tool_timeline: [],
        observation: {
          timestamp: 'not-a-number',
          workspace: {
            git_available: true,
            git_branch: { unexpected: true },
            git_status: null,
            git_diff_stat: 123,
            open_files: ['README.md', null, { path: 'secret' }],
            last_build_result: {
              result: { unexpected: true },
              command: null,
              output_tail: 456,
              exit_code: 'zero',
            },
          },
          recent_events: [
            null,
            { type: 42, data: null },
            { type: 'tool_complete', data: { tool: 'file_read' } },
          ],
        },
      }),
    }));

    await expect(localmindClient.getObservability('session-2')).resolves.toMatchObject({
      intent: 'file',
      toolsUsed: ['file_read'],
      observation: {
        timestamp: 0,
        workspace: {
          gitAvailable: true,
          gitBranch: '',
          gitStatus: '',
          gitDiffStat: '',
          openFiles: ['README.md'],
          lastBuildResult: {
            result: '',
            command: '',
            outputTail: '',
            exitCode: undefined,
          },
        },
        recentEvents: [
          { type: 'event', data: {} },
          { type: 'tool_complete', data: { tool: 'file_read' } },
        ],
      },
    });
  });
});

describe('classifyClientIntent (B-2026-08-09-6 / ADR-11)', () => {
  it('hints chat for greetings, farewells, thanks, and acknowledgments', () => {
    expect(classifyClientIntent('hi')).toBe('chat');
    expect(classifyClientIntent('Hello!')).toBe('chat');
    expect(classifyClientIntent('good morning')).toBe('chat');
    expect(classifyClientIntent('thanks')).toBe('chat');
    expect(classifyClientIntent('thank you!')).toBe('chat');
    expect(classifyClientIntent('bye')).toBe('chat');
    expect(classifyClientIntent('ok')).toBe('chat');
    expect(classifyClientIntent('got it')).toBe('chat');
  });

  it('hints chat for short non-tool conversational questions', () => {
    expect(classifyClientIntent('What can you do?')).toBe('chat');
    expect(classifyClientIntent('Who are you?')).toBe('chat');
    expect(classifyClientIntent('how are you?')).toBe('chat');
    expect(classifyClientIntent('What is the capital of France?')).toBe('chat');
    expect(classifyClientIntent('can you explain recursion')).toBe('chat');
  });

  it('never hints chat for tool, realtime, or system queries', () => {
    expect(classifyClientIntent('what time is it')).toBeUndefined();
    expect(classifyClientIntent('what is today\'s weather')).toBeUndefined();
    expect(classifyClientIntent('how much RAM do I have')).toBeUndefined();
    expect(classifyClientIntent('who wrote app.py')).toBeUndefined();
    expect(classifyClientIntent('can you fix my code')).toBeUndefined();
    expect(classifyClientIntent('what is the latest news')).toBeUndefined();
    expect(classifyClientIntent('search the web for LocalMind')).toBeUndefined();
    expect(classifyClientIntent('what day is it')).toBeUndefined();
    expect(classifyClientIntent('how do you run code')).toBeUndefined();
    expect(classifyClientIntent('who wrote the file')).toBeUndefined();
  });

  it('returns undefined for empty, long, or non-interrogative inputs', () => {
    expect(classifyClientIntent('')).toBeUndefined();
    expect(classifyClientIntent('   ')).toBeUndefined();
    expect(classifyClientIntent('please create a python script that prints hello world and then run it')).toBeUndefined();
    expect(classifyClientIntent('a completely random statement')).toBeUndefined();
  });
});

describe('streamChat SSE integration (B-2026-07-31 follow-up)', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function stubSseResponse(bodyChunks: string[]): void {
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of bodyChunks) {
          controller.enqueue(new TextEncoder().encode(chunk));
        }
        controller.close();
      },
    });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, body: stream }));
  }

  it('delivers the final event and completes when the stream ends without a trailing newline', async () => {
    // Simulates a proxy/server close mid-event: the last `data:` line has no
    // trailing newline, so it is only parseable via the end-of-stream flush.
    stubSseResponse(['data: {"content":"final chunk"}']);

    const onChunk = vi.fn();
    const onDone = vi.fn();
    const onError = vi.fn();

    const abort = localmindClient.streamChat('hello', 'sess-sse-1', onChunk, onDone, onError);
    await vi.waitFor(() => expect(onDone).toHaveBeenCalled());

    expect(onChunk).toHaveBeenCalledOnce();
    expect(onChunk).toHaveBeenCalledWith('{"content":"final chunk"}');
    expect(onDone).toHaveBeenCalledOnce();
    expect(onError).not.toHaveBeenCalled();
    expect(abort).toBeTypeOf('function');
  });

  it('fires done exactly once when a trailing [DONE] has no newline', async () => {
    // The hidden-done-event case: `[DONE]` arrives as the final buffered
    // line with no trailing newline. flush() must terminate the stream and
    // onDone must fire exactly once (finish() dedupes).
    stubSseResponse(['data: {"content":"almost"}\n\ndata: [DONE]']);

    const onChunk = vi.fn();
    const onDone = vi.fn();
    const onError = vi.fn();

    localmindClient.streamChat('hello', 'sess-sse-2', onChunk, onDone, onError);
    await vi.waitFor(() => expect(onDone).toHaveBeenCalled());

    expect(onChunk).toHaveBeenCalledOnce();
    expect(onChunk).toHaveBeenCalledWith('{"content":"almost"}');
    expect(onDone).toHaveBeenCalledOnce();
    expect(onError).not.toHaveBeenCalled();
  });

  it('propagates a non-OK response to onError', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, body: null }));

    const onChunk = vi.fn();
    const onDone = vi.fn();
    const onError = vi.fn();

    localmindClient.streamChat('hello', 'sess-sse-3', onChunk, onDone, onError);
    await vi.waitFor(() => expect(onError).toHaveBeenCalled());

    expect(onDone).not.toHaveBeenCalled();
    expect(onChunk).not.toHaveBeenCalled();
  });
});

describe('steer', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('posts a trimmed message to the session steer endpoint and resolves true', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ accepted: true }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await expect(localmindClient.steer('sess-1', '  go left  ')).resolves.toBe(true);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/chat/sess-1/steer');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({ message: 'go left' });
  });

  it('returns false when the backend rejects (queue full / blank)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 409 }));

    await expect(localmindClient.steer('sess-2', 'more!')).resolves.toBe(false);
  });

  it('returns false for a blank message without calling fetch', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    await expect(localmindClient.steer('sess-3', '   ')).resolves.toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
