import { describe, expect, it } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useTabTitle } from './useTabTitle';

describe('useTabTitle', () => {
  it('shows the agent is working, then goes back to the plain title', () => {
    const { rerender, unmount } = renderHook(({ on }) => useTabTitle(on, 'Searching the web'), { initialProps: { on: true } });
    expect(document.title).toBe('● Searching the web… — LocalMind');
    rerender({ on: true });
    rerender({ on: false });
    expect(document.title).toBe('LocalMind');
    unmount();
  });

  it('never puts a raw command in the title', () => {
    renderHook(() => useTabTitle(true, 'Running: ls -1 /etc/host*.conf 2>/dev/null'));
    expect(document.title).toBe('● Running… — LocalMind');
  });

  it('ignores heartbeat filler', () => {
    renderHook(() => useTabTitle(true, 'Agent is still working — this can take a moment'));
    expect(document.title).toBe('● Working… — LocalMind');
  });
});
