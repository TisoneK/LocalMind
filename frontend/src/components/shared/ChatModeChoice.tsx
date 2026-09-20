/** ChatModeChoice — the default way messages are handled: Auto, Agent (always tools) or Chat (no tools). */

import { useEffect, useState } from 'react';
import { localmindClient } from '@/lib/localmind/client';

type Mode = 'auto' | 'agent' | 'direct';

const MODES: { id: Mode; label: string; help: string }[] = [
  { id: 'auto', label: 'Auto', help: 'LocalMind decides: quick questions are answered directly, anything that needs a tool goes to the agent.' },
  { id: 'agent', label: 'Agent', help: 'Every message goes to the full agent, which can run tools.' },
  { id: 'direct', label: 'Chat', help: 'Plain conversation with no tools.' },
];

export function ChatModeChoice() {
  const [mode, setMode] = useState<Mode>('auto');

  useEffect(() => {
    let live = true;
    Promise.resolve()
      .then(() => localmindClient.getSettings())
      .then((r) => {
        const m = (r as { chat_mode?: string }).chat_mode;
        if (live && (m === 'auto' || m === 'agent' || m === 'direct')) setMode(m);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, []);

  const choose = async (next: Mode) => {
    if (next === mode) return;
    setMode(next);
    try {
      await localmindClient.setChatMode(next);
      window.dispatchEvent(new CustomEvent('localmind:chat-mode-changed', { detail: { mode: next } }));
    } catch {
      /* the composer's own picker still works */
    }
  };

  return (
    <div data-testid="chat-mode-choice">
      <div role="radiogroup" aria-label="Chat mode" className="flex overflow-hidden rounded-lg border border-brand-border">
        {MODES.map((m) => (
          <button
            key={m.id}
            type="button"
            role="radio"
            aria-checked={mode === m.id}
            onClick={() => choose(m.id)}
            className={`flex-1 px-3 py-1.5 text-sm transition-colors ${
              mode === m.id ? 'bg-brand-green/15 text-brand-green' : 'text-brand-green-muted hover:text-brand-green-soft'
            }`}
          >
            {m.label}
          </button>
        ))}
      </div>
      <p className="mt-2 text-xs text-brand-green-muted">{MODES.find((m) => m.id === mode)?.help}</p>
    </div>
  );
}
