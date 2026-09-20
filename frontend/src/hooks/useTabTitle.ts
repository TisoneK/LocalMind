import { useEffect, useRef } from 'react';

const BASE = 'LocalMind';

/**
 * Keeps the browser/window title honest about the agent: "● Working…" while it runs, and
 * "✓ Done" if it finished while you were in another tab, so a long turn can be left alone and
 * noticed from the tab strip. Restores the plain title when you come back.
 */
export function useTabTitle(isStreaming: boolean, label?: string) {
  const wasStreaming = useRef(false);

  useEffect(() => {
    if (isStreaming) {
      // Heartbeat filler ("Agent is still working — this can take…") is not worth a tab title.
      const specific = label && !/^(agent is|got it|done)/i.test(label) ? label.replace(/…|\.\.\.$/, '').slice(0, 36) : '';
      document.title = `● ${specific || 'Working'}… — ${BASE}`;
    } else if (wasStreaming.current && document.hidden) {
      document.title = `✓ Done — ${BASE}`;
    } else {
      document.title = BASE;
    }
    wasStreaming.current = isStreaming;
  }, [isStreaming, label]);

  useEffect(() => {
    const restore = () => {
      if (!document.hidden && !wasStreaming.current) document.title = BASE;
    };
    document.addEventListener('visibilitychange', restore);
    return () => {
      document.removeEventListener('visibilitychange', restore);
      document.title = BASE;
    };
  }, []);
}
