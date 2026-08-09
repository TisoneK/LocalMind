import { describe, expect, it, vi } from 'vitest';
import { createSSEParser } from './sse';

describe('createSSEParser', () => {
  it('flushes a final data event without a trailing newline', () => {
    const onData = vi.fn();
    const onDone = vi.fn();
    const parser = createSSEParser(onData, onDone);

    parser.push('data: {"content":"last chunk"}');
    parser.flush();

    expect(onData).toHaveBeenCalledOnce();
    expect(onData).toHaveBeenCalledWith('{"content":"last chunk"}');
    expect(onDone).not.toHaveBeenCalled();
  });

  it('delivers complete events and terminates on [DONE]', () => {
    const onData = vi.fn();
    const onDone = vi.fn();
    const parser = createSSEParser(onData, onDone);

    const terminated = parser.push(
      'data: {"content":"first"}\n\ndata: [DONE]\n\n',
    );
    parser.flush();

    expect(terminated).toBe(true);
    expect(onData).toHaveBeenCalledOnce();
    expect(onData).toHaveBeenCalledWith('{"content":"first"}');
    expect(onDone).toHaveBeenCalledOnce();
  });

  it('flushes a [DONE] event that arrives without a trailing newline', () => {
    // Session 37 backlog: a proxy/server close without a trailing newline
    // can hide the final `done` event. `flush()` must process the buffered
    // `[DONE]` line and fire onDone exactly once.
    const onData = vi.fn();
    const onDone = vi.fn();
    const parser = createSSEParser(onData, onDone);

    parser.push('data: {"content":"almost"}\n\ndata: [DONE]');
    const terminated = parser.flush();

    expect(terminated).toBe(true);
    expect(onData).toHaveBeenCalledOnce();
    expect(onData).toHaveBeenCalledWith('{"content":"almost"}');
    expect(onDone).toHaveBeenCalledOnce();
  });

  it('buffers a data line split across network chunks and delivers it on flush', () => {
    // A partial `data:` line at a chunk boundary must be retained and
    // delivered once the stream ends — not dropped (Session 37 backlog).
    const onData = vi.fn();
    const onDone = vi.fn();
    const parser = createSSEParser(onData, onDone);

    parser.push('data: {"content":"split');
    expect(onData).not.toHaveBeenCalled();

    parser.push(' across chunks"}');
    parser.flush();

    expect(onData).toHaveBeenCalledOnce();
    expect(onData).toHaveBeenCalledWith('{"content":"split across chunks"}');
    expect(onDone).not.toHaveBeenCalled();
  });
});
