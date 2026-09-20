/**
 * PackageEnvChoice — where installs go. A pip install changes a Python; that should never happen
 * to the user's system by surprise, so LocalMind installs into a folder it owns unless told
 * otherwise. Used by the terminal's package installer and by Settings.
 */

import { useEffect, useState } from 'react';
import { localmindClient } from '@/lib/localmind/client';

type Env = 'localmind' | 'system';

const OPTIONS: { id: Env; label: string; help: string }[] = [
  { id: 'localmind', label: 'LocalMind', help: "Installs into LocalMind's own folder. Your system Python is untouched; deleting the folder undoes it." },
  { id: 'system', label: 'System', help: "Installs into the Python on your PATH, like running pip yourself. Affects every program that uses it." },
];

export function PackageEnvChoice({ compact = false }: { compact?: boolean }) {
  const [env, setEnv] = useState<Env>('localmind');
  const [dir, setDir] = useState('');
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    localmindClient
      .getPackageEnv()
      .then((r) => {
        if (!live) return;
        setEnv(r.package_env);
        setDir(r.packages_dir);
      })
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, []);

  const choose = async (next: Env) => {
    if (next === env) return;
    const before = env;
    setEnv(next);
    try {
      const r = await localmindClient.setPackageEnv(next);
      setDir(r.packages_dir);
      setFailed(false);
    } catch {
      setEnv(before);
      setFailed(true);
    }
  };

  return (
    <div className="flex items-center gap-1.5" data-testid="package-env">
      {!compact && <span className="text-[10px] text-brand-green-muted">Install into</span>}
      <div role="radiogroup" aria-label="Install into" className="flex overflow-hidden rounded border border-brand-border">
        {OPTIONS.map((o) => (
          <button
            key={o.id}
            type="button"
            role="radio"
            aria-checked={env === o.id}
            onClick={() => choose(o.id)}
            title={`${o.label}\n${o.help}${o.id === 'localmind' && dir ? `\n${dir}` : ''}`}
            className={`px-2 py-0.5 text-[10px] transition-colors ${
              env === o.id ? 'bg-brand-green/15 text-brand-green' : 'text-brand-green-muted hover:text-brand-green-soft'
            }`}
          >
            {o.label}
          </button>
        ))}
      </div>
      {failed && <span className="text-[10px] text-brand-red">couldn't save</span>}
    </div>
  );
}
