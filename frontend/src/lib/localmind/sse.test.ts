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
});
