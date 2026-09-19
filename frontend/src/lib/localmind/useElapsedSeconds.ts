import { useEffect, useState } from 'react';

/** Whole seconds since mount that tick while `active`, and freeze when it turns false. */
export function useElapsedSeconds(active: boolean): number {
  const [start] = useState(() => Date.now());
  const [now, setNow] = useState(start);
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [active]);
  return Math.max(0, Math.round((now - start) / 1000));
}
