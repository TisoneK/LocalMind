/**
 * ShellChoice — which shell the terminal and the agent's commands run in. "Automatic" keeps the
 * platform default; the rest are the shells found on this machine, so a Windows user can pick
 * PowerShell, Command Prompt or Git Bash, and others bash, zsh, fish or sh.
 */

import { useEffect, useState } from 'react';
import { localmindClient } from '@/lib/localmind/client';

interface Option {
  id: string;
  label: string;
  path: string;
  available: boolean;
}

export function ShellChoice() {
  const [shell, setShell] = useState('auto');
  const [options, setOptions] = useState<Option[]>([]);
  const [error, setError] = useState('');

  useEffect(() => {
    let live = true;
    Promise.resolve()
      .then(() => localmindClient.getShell())
      .then((r) => {
        if (!live) return;
        setShell(r.shell);
        setOptions(r.options);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, []);

  const choose = async (id: string) => {
    if (id === shell) return;
    const before = shell;
    setShell(id);
    setError('');
    try {
      await localmindClient.setShell(id);
      // The terminal panel names its shell; tell it.
      window.dispatchEvent(new CustomEvent('localmind:shell-changed', { detail: { shell: id } }));
    } catch (e) {
      setShell(before);
      setError(e instanceof Error ? e.message : "Couldn't save");
    }
  };

  const all: Option[] = [{ id: 'auto', label: 'Automatic', path: '', available: true }, ...options];

  return (
    <div data-testid="shell-choice">
      <div role="radiogroup" aria-label="Shell" className="space-y-1">
        {all.map((o) => (
          <button
            key={o.id}
            type="button"
            role="radio"
            aria-checked={shell === o.id}
            disabled={!o.available}
            onClick={() => choose(o.id)}
            className={`flex w-full items-center justify-between gap-3 rounded-lg border px-3 py-2 text-left text-sm transition-colors ${
              shell === o.id
                ? 'border-brand-green/40 bg-brand-green/10 text-brand-green'
                : 'border-brand-border text-brand-green-soft hover:border-brand-green/30'
            } disabled:cursor-not-allowed disabled:opacity-45`}
          >
            <span>{o.label}</span>
            <span className="truncate font-mono text-[10.5px] text-brand-green-muted">
              {o.id === 'auto' ? 'the platform default' : o.available ? o.path : 'not installed'}
            </span>
          </button>
        ))}
      </div>
      {error && <p className="mt-2 text-xs text-brand-red">{error}</p>}
    </div>
  );
}
