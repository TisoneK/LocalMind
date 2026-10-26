// Provider health helpers — pure logic (the ProvidersPage component file
// exports only its component).

import type { ConnectionRecord } from '@/lib/localmind/client';

export type Health = 'ready' | 'needs-key' | 'off';

export function providerHealth(c: Pick<ConnectionRecord, 'enabled' | 'api_key_set' | 'kind'>): Health {
  if (!c.enabled) return 'off';
  if (c.kind === 'ollama') return 'ready';
  return c.api_key_set ? 'ready' : 'needs-key';
}

/** Providers you have set up (custom, or with a key, or the one in use) versus the rest of the built-ins. */
export function splitProviders(all: ConnectionRecord[], active: string) {
  const mine = all.filter((c) => !c.preset || c.api_key_set || c.id === active || c.kind === 'ollama');
  const more = all.filter((c) => !mine.includes(c));
  return { mine, more };
}

/** Tooltip placement label colours, keyed by health. */
export const DOT: Record<Health, string> = {
  ready: 'bg-brand-green',
  'needs-key': 'bg-brand-amber',
  off: 'bg-brand-border',
};

export const HEALTH_TEXT: Record<Health, string> = {
  ready: 'Ready',
  'needs-key': 'Needs an API key',
  off: 'Off',
};
