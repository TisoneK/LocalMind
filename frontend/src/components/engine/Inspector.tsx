/**
 * The inspector: everything real behind whatever is picked in the tree.
 *
 * A move shows what was proposed, what the probe actually returned, and what the scoring said. A state
 * shows what it KNOWS (the real observations), what it has ruled out, the path that reached it, and what
 * the run had spent by then. Nothing here is reasoning — it is the engine's own record.
 */

import {
  failedAt,
  factsAt,
  labelForFp,
  metersAt,
  pathTo,
  roundOf,
  spendAt,
  trailAt,
  type EngineEvent,
  type Model,
} from '@/lib/localmind/stateEngine';

interface Props {
  events: readonly EngineEvent[];
  model: Model;
  picked: string | null;
  cursor: number;
  onPick: (id: string) => void;
}

function Rows({ pairs }: { pairs: [string, React.ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[86px_1fr] gap-x-2 gap-y-1">
      {pairs.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-brand-green-muted">{k}</dt>
          <dd className="break-words">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

const Pill = ({ tone, children }: { tone: 'green' | 'red' | 'amber' | 'purple'; children: React.ReactNode }) => (
  <span
    className={`rounded-full border px-2 py-0.5 text-[11px] ${
      tone === 'green' ? 'border-brand-green text-brand-green' : tone === 'red' ? 'border-brand-red text-brand-red' : tone === 'amber' ? 'border-brand-amber text-brand-amber' : 'border-brand-purple text-brand-purple'
    }`}
  >
    {children}
  </span>
);

export function Inspector({ events, model, picked, cursor, onPick }: Props) {
  const end = model.end && model.end.seq <= cursor ? model.end : null;
  const spend = spendAt(events, cursor);
  const meters = metersAt(events, model, cursor);
  let body: React.ReactNode = (
    <p className="text-brand-green-muted">
      Click a state to read what it knows, or a move to see the real observation behind it. Green is the chosen path, dashed
      amber a backtrack, ✕ a failed or pruned branch.
    </p>
  );

  if (picked?.startsWith('c:')) {
    const [, rs, fp] = picked.split(':');
    const round = model.rounds.find((r) => String(r.seq) === rs);
    const card = round?.cards.find((x) => x.fp === fp);
    if (round && card) {
      body = (
        <>
          <div className="mb-2 flex items-center gap-2">
            <Pill tone={card.status === 'selected' ? 'green' : card.status === 'failed' || card.status === 'pruned' ? 'red' : card.status === 'gated' ? 'purple' : 'amber'}>
              {card.status}
            </Pill>
            <span className="truncate font-medium text-brand-green-soft">{card.label}</span>
          </div>
          <Rows
            pairs={[
              ['why', card.why || '—'],
              ['tool', card.tool || '—'],
              ['fingerprint', <code className="break-all">{card.fp}</code>],
              [
                'at state',
                <button type="button" className="underline decoration-dotted hover:text-brand-green" onClick={() => onPick(`n:${round.node}`)}>
                  {round.node}
                </button>,
              ],
              ['probe', card.probeSeq ? `${card.ok ? 'ok' : 'FAILED'} · ${card.ms}ms · ${card.chars} chars` : '—'],
              ['score', card.progress != null ? card.progress.toFixed(2) : '—'],
              ['judgement', card.reason || '—'],
            ]}
          />
          {card.excerpt ? (
            <>
              <b className="mt-3 block text-brand-green-muted">OBSERVATION (real tool result)</b>
              <pre className="mt-1 max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-md border border-brand-border bg-brand-bg-panel-alt p-2">{card.excerpt}</pre>
            </>
          ) : null}
        </>
      );
    }
  } else if (picked?.startsWith('n:')) {
    const id = picked.slice(2);
    const n = model.nodes.find((x) => x.id === id);
    if (n) {
      const facts = factsAt(events, n.id);
      const failed = failedAt(events, model, n.id);
      const trail = trailAt(events, n.id);
      const round = roundOf(model, n.id);
      body = (
        <>
          <div className="mb-2 flex items-center gap-2">
            <Pill tone="purple">{n.depth === 0 ? 'start' : `depth ${n.depth}`}</Pill>
            <span className="font-medium text-brand-green-soft">{n.id}</span>
          </div>
          <Rows
            pairs={[
              ['progress', n.progress.toFixed(2)],
              ['facts', String(n.facts)],
              ['ruled out', String(failed.length)],
              ['reached via', n.viaFp ? <code className="break-all">{labelForFp(model, n.viaFp)}</code> : '—'],
              ['states back', String(pathTo(model, n.id).length - 1)],
              ['fan here', round ? `${round.cards.length} proposed` : '—'],
            ]}
          />
          {facts.length > 0 && (
            <>
              <b className="mt-3 block text-brand-green-muted">WHAT THIS STATE KNOWS ({facts.length})</b>
              <ul className="mt-1 space-y-1">
                {facts.map((f, i) => (
                  <li key={i} className="rounded-md border border-brand-border bg-brand-bg-panel-alt p-1.5 break-words">
                    {f}
                  </li>
                ))}
              </ul>
            </>
          )}
          {failed.length > 0 && (
            <>
              <b className="mt-3 block text-brand-green-muted">RULED OUT HERE ({failed.length})</b>
              <ul className="mt-1 space-y-1 text-brand-red">
                {failed.map((f) => (
                  <li key={f.fp} className="truncate" title={f.label}>
                    ✕ {f.label}
                  </li>
                ))}
              </ul>
            </>
          )}
          {trail.length > 0 && (
            <>
              <b className="mt-3 block text-brand-green-muted">PATH TO HERE</b>
              <ol className="mt-1 space-y-0.5 text-brand-green-muted">
                {trail.map((t, i) => (
                  <li key={i} className="truncate" title={t}>
                    {i + 1}. {t}
                  </li>
                ))}
              </ol>
            </>
          )}
          <p className="mt-3 text-brand-green-muted">
            The engine owns this state — the goal, facts learned from real observations, and the moves that failed. The model
            never holds it.
          </p>
        </>
      );
    }
  }

  return (
    <div className="p-3">
      {picked ? null : (
        <div className="mb-3 rounded-md border border-brand-border bg-brand-bg-panel-alt p-2">
          <Rows
            pairs={[
              ['model calls', `${meters.calls}`],
              ['probes', `${meters.probes} · ${spend.probeMs}ms`],
              ['backtracks', `${meters.backtracks}`],
              ['slowest probe', spend.slowest ? `${spend.slowest.ms}ms ${spend.slowest.label}` : '—'],
            ]}
          />
        </div>
      )}
      {body}
      {end && (
        <div className={`mt-4 rounded-lg border p-2.5 ${end.kind === 'done' ? 'border-brand-green' : 'border-brand-red'}`} data-testid="end-banner">
          <b className="mb-1 block">{end.kind === 'done' ? `GOAL SETTLED · ${end.model_calls} model calls` : `NOT SETTLED · ${end.reason}`}</b>
          {end.kind === 'done' ? (
            <>
              {end.answer}
              <div className="mt-1 text-brand-green-muted">trail: {(end.trail ?? []).join(' → ')}</div>
            </>
          ) : (
            <>The engine stops honestly instead of guessing. Facts it established: {Array.isArray(end.facts) ? end.facts.length : 0}.</>
          )}
        </div>
      )}
    </div>
  );
}
