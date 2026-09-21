/**
 * Compare two runs side by side.
 *
 * The engine is a search, so the question that matters is which search went better: fewer model calls for
 * the same answer, deeper before settling, a backtrack that saved it. Two runs of DIFFERENT goals are not
 * a comparison of strategies, so the panel says so instead of ranking them.
 */

import { useMemo, useState } from 'react';
import { summarize, type RunLike } from '@/lib/localmind/stateEngine';

interface Props {
  runs: RunLike[];
  onClose: () => void;
}

const ROWS: { key: keyof ReturnType<typeof summarize>; label: string; better: 'higher' | 'lower' | 'none'; format?: (s: ReturnType<typeof summarize>) => string }[] = [
  { key: 'outcome', label: 'outcome', better: 'none' },
  { key: 'calls', label: 'model calls', better: 'lower' },
  { key: 'probes', label: 'probes', better: 'none' },
  { key: 'plies', label: 'plies (moves applied)', better: 'none' },
  { key: 'depth', label: 'depth reached', better: 'none' },
  { key: 'backtracks', label: 'backtracks', better: 'none' },
  { key: 'best', label: 'best progress', better: 'higher', format: (s) => s.best.toFixed(2) },
  { key: 'elapsedMs', label: 'wall clock', better: 'lower', format: (s) => `${(s.elapsedMs / 1000).toFixed(1)}s` },
  { key: 'tools', label: 'tools used', better: 'none', format: (s) => s.tools.join(', ') || '—' },
];

export function RunCompare({ runs, onClose }: Props) {
  const usable = useMemo(() => runs.filter((r) => r.events.length > 0), [runs]);
  const [a, setA] = useState(usable.at(-2)?.id ?? usable.at(-1)?.id ?? '');
  const [b, setB] = useState(usable.at(-1)?.id ?? '');
  const ra = usable.find((r) => r.id === a) ?? usable.at(-1);
  const rb = usable.find((r) => r.id === b) ?? usable.at(-1);

  if (!ra || !rb) {
    return (
      <div className="p-4 text-brand-green-muted" data-testid="run-compare">
        Not enough runs to compare yet — run a goal (or duplicate one with a different budget).
        <button type="button" onClick={onClose} className="ml-2 rounded-md border border-brand-border-strong px-2 py-0.5">close</button>
      </div>
    );
  }
  const sa = summarize(ra);
  const sb = summarize(rb);
  const sameGoal = ra.goal.trim() === rb.goal.trim();

  return (
    <div className="h-full overflow-auto p-4 font-mono text-xs" data-testid="run-compare">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <b className="tracking-[0.14em] text-brand-green">COMPARE RUNS</b>
        {(['a', 'b'] as const).map((which) => (
          <select
            key={which}
            aria-label={`Run ${which.toUpperCase()}`}
            value={which === 'a' ? ra.id : rb.id}
            onChange={(e) => (which === 'a' ? setA(e.target.value) : setB(e.target.value))}
            className="max-w-[240px] rounded-md border border-brand-border-strong bg-brand-bg-panel-alt px-2 py-1"
          >
            {usable.map((r, i) => (
              <option key={r.id} value={r.id}>{`${i + 1}. ${r.title}`}</option>
            ))}
          </select>
        ))}
        <button type="button" onClick={onClose} className="ml-auto rounded-md border border-brand-border-strong px-2 py-1">close</button>
      </div>

      {!sameGoal && (
        <p className="mb-3 rounded-md border border-brand-amber p-2 text-brand-amber">
          These runs had different goals, so the numbers are not a fair comparison of search settings — read each row as its
          own result.
        </p>
      )}

      <table className="w-full border-collapse">
        <thead>
          <tr className="text-left text-brand-green-muted">
            <th className="border-b border-brand-border py-1 pr-3">metric</th>
            <th className="border-b border-brand-border py-1 pr-3">A · {sa.title}</th>
            <th className="border-b border-brand-border py-1">B · {sb.title}</th>
          </tr>
        </thead>
        <tbody>
          {ROWS.map((row) => {
            const va = row.format ? row.format(sa) : String(sa[row.key]);
            const vb = row.format ? row.format(sb) : String(sb[row.key]);
            const na = Number(sa[row.key]);
            const nb = Number(sb[row.key]);
            const canRank = sameGoal && row.better !== 'none' && Number.isFinite(na) && Number.isFinite(nb) && na !== nb;
            const aWins = canRank && (row.better === 'lower' ? na < nb : na > nb);
            const cls = (wins: boolean) => (canRank && wins ? 'text-brand-green' : canRank ? 'text-brand-green-muted' : '');
            return (
              <tr key={String(row.key)}>
                <td className="border-b border-brand-border py-1 pr-3 text-brand-green-muted">{row.label}</td>
                <td className={`border-b border-brand-border py-1 pr-3 ${cls(aWins)}`}>{va}</td>
                <td className={`border-b border-brand-border py-1 ${cls(!aWins)}`}>{vb}</td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <div className="mt-4 grid gap-3 md:grid-cols-2">
        {[
          { s: sa, label: 'A' },
          { s: sb, label: 'B' },
        ].map(({ s, label }) => (
          <div key={label} className="rounded-md border border-brand-border bg-brand-bg-panel-alt p-2.5">
            <b className="block text-brand-green-muted">{label} · goal</b>
            <p className="mb-2 break-words">{s.goal}</p>
            <b className="block text-brand-green-muted">answer</b>
            <p className="break-words">
              {s.outcome === 'settled' ? s.answer : s.outcome === 'not_settled' ? `not settled — ${s.reason}` : s.outcome}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
