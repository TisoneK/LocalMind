/**
 * EngineChoice — which agent engine answers: the Classic parent agent, or the experimental State engine.
 *
 * Engine and model are independent choices (a model is used either way); this one decides HOW a goal is
 * worked. State swaps the chat pane for the State Explorer and only ever looks and reads.
 */

import { useEffect, useState } from 'react';
import { localmindClient } from '@/lib/localmind/client';

type Engine = 'classic' | 'state';

const ENGINES: { id: Engine; label: string; help: string }[] = [
  {
    id: 'classic',
    label: 'Classic',
    help: 'The parent agent: it reasons in the conversation, runs tools step by step, and answers in the chat.',
  },
  {
    id: 'state',
    label: 'State (experimental)',
    help: 'The state-driven engine: it holds the state itself, fans out candidate moves, really probes the read-only ones, keeps the best and backtracks from dead ends. Its run shows as a game tree instead of a chat — and it can look and read, never change anything.',
  },
];

export function EngineChoice() {
  const [engine, setEngine] = useState<Engine>('classic');

  useEffect(() => {
    let live = true;
    Promise.resolve()
      .then(() => localmindClient.getSettings())
      .then((r) => {
        const e = (r as { engine?: string }).engine;
        if (live && (e === 'classic' || e === 'state')) setEngine(e);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, []);

  const choose = async (next: Engine) => {
    if (next === engine) return;
    setEngine(next);
    try {
      await localmindClient.setEngine(next);
      window.dispatchEvent(new CustomEvent('localmind:engine-changed', { detail: { engine: next } }));
    } catch {
      /* the setting is still saved on the next successful call */
    }
  };

  return (
    <div data-testid="engine-choice">
      <div role="radiogroup" aria-label="Agent engine" className="flex overflow-hidden rounded-lg border border-brand-border">
        {ENGINES.map((e) => (
          <button
            key={e.id}
            type="button"
            role="radio"
            aria-checked={engine === e.id}
            onClick={() => choose(e.id)}
            className={`flex-1 px-3 py-1.5 text-sm transition-colors ${
              engine === e.id ? 'bg-brand-green/15 text-brand-green' : 'text-brand-green-muted hover:text-brand-green-soft'
            }`}
          >
            {e.label}
          </button>
        ))}
      </div>
      <p className="mt-2 text-xs text-brand-green-muted">{ENGINES.find((e) => e.id === engine)?.help}</p>
    </div>
  );
}
