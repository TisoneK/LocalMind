/** The tree canvas: states, the fan of candidate moves at each, and the edges between them. */

import {
  CARD_H,
  CARD_W,
  NODE_H,
  NODE_W,
  cardKey,
  cardStatusAt,
  type Card,
  type CardStatus,
  type Layout,
  type Model,
  type Point,
  type Round,
} from '@/lib/localmind/stateEngine';

interface Props {
  model: Model;
  layout: Layout;
  /** How many events of the run are revealed. */
  cursor: number;
  picked: string | null;
  onPick: (id: string) => void;
}

const curve = (x1: number, y1: number, x2: number, y2: number) => {
  const mx = (x1 + x2) / 2;
  return `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`;
};

const CARD_STYLE: Record<CardStatus, string> = {
  open: 'border-brand-border-strong',
  probing: 'border-brand-border-strong',
  rejected: 'border-brand-border-strong opacity-85',
  selected: 'border-brand-green ring-1 ring-brand-green',
  failed: 'border-brand-red',
  pruned: 'border-dashed border-brand-border-strong opacity-55',
  gated: 'border-brand-purple',
};

const GLYPH: Record<CardStatus, string> = {
  open: '',
  probing: '… probing',
  rejected: '○ not best',
  selected: '● selected',
  failed: '✕ failed',
  pruned: '✕ pruned',
  gated: '🔒 needs confirmation',
};

function CardView({ card, round, cursor, picked, pos, onPick }: {
  card: Card;
  round: Round;
  cursor: number;
  picked: string | null;
  pos: Point;
  onPick: (id: string) => void;
}) {
  const id = `c:${round.seq}:${card.fp}`;
  const status = cardStatusAt(card, round, cursor);
  const scored = !!card.evalSeq && card.evalSeq <= cursor;
  const probed = !!card.probeSeq && card.probeSeq <= cursor;
  const shown = round.seq <= cursor;
  const progress = scored ? (card.progress ?? 0) : 0;
  return (
    <button
      type="button"
      data-seq={round.seq}
      data-testid={`card-${status}`}
      aria-label={`${card.label} — ${GLYPH[status] || 'proposed'}`}
      onClick={() => onPick(id)}
      style={{ left: pos.x, top: pos.y, width: CARD_W, height: CARD_H }}
      className={`absolute overflow-hidden rounded-lg border bg-brand-bg-panel px-2.5 py-1.5 text-left transition-opacity ${CARD_STYLE[status]} ${
        shown ? '' : 'pointer-events-none opacity-0'
      } ${picked === id ? 'outline outline-2 outline-offset-2 outline-brand-blue' : ''}`}
    >
      <div className={`truncate text-xs ${status === 'failed' ? 'text-brand-red line-through' : 'text-brand-green-soft'}`}>{card.label}</div>
      <div className="truncate text-[11px] text-brand-green-muted">{card.why}</div>
      <div className="mt-1 flex items-center gap-2 text-[11px] text-brand-green-muted">
        <div className="h-1.5 flex-1 overflow-hidden rounded bg-brand-border">
          <div
            className={`h-full transition-[width] duration-300 ${status === 'selected' ? 'bg-brand-green' : 'bg-brand-blue'}`}
            style={{ width: `${Math.round(progress * 100)}%` }}
          />
        </div>
        <span>{scored ? progress.toFixed(2) : '—'}</span>
        <span>{probed ? `${card.ms ?? 0}ms` : ''}</span>
        <span className={status === 'selected' ? 'text-brand-green' : status === 'failed' ? 'text-brand-red' : ''}>{GLYPH[status]}</span>
      </div>
    </button>
  );
}

export function StateTree({ model, layout, cursor, picked, onPick }: Props) {
  const nodePos = (id: string) => layout.nodes.get(id) as Point;
  const cardPos = (r: Round, fp: string) => layout.cards.get(cardKey(r, fp)) as Point;
  const vis = (seq: number) => (seq <= cursor ? 1 : 0);
  const endSeq = model.end?.seq ?? Infinity;

  return (
    <div className="relative" style={{ width: layout.width, height: layout.height }} data-testid="state-tree">
      <svg className="pointer-events-none absolute left-0 top-0 overflow-visible" width={layout.width} height={layout.height} aria-hidden="true">
        {model.rounds.map((r) =>
          r.cards.map((c) => {
            const p = nodePos(r.node);
            const cp = cardPos(r, c.fp);
            const chosen = c.fp === r.sel;
            return (
              <path
                key={`e-${cardKey(r, c.fp)}`}
                d={curve(p.x + NODE_W, p.y + NODE_H / 2, cp.x, cp.y + CARD_H / 2)}
                fill="none"
                className={chosen ? 'stroke-brand-green' : 'stroke-brand-border-strong'}
                strokeWidth={chosen ? 2.2 : 1.2}
                strokeDasharray={c.status === 'pruned' ? '2 4' : undefined}
                style={{ opacity: vis(r.seq) }}
              />
            );
          })
        )}
        {model.nodes.map((n) => {
          const pr = model.rounds.find((r) => r.node === n.parent && r.sel === n.viaFp);
          if (!pr || !n.viaFp) return null;
          const cp = cardPos(pr, n.viaFp);
          const p = nodePos(n.id);
          return (
            <path key={`s-${n.id}`} d={curve(cp.x + CARD_W, cp.y + CARD_H / 2, p.x, p.y + NODE_H / 2)} fill="none" className="stroke-brand-green" strokeWidth={2.2} style={{ opacity: vis(n.seq) }} />
          );
        })}
        {model.rounds.map((r) => {
          if (!r.stalled || !r.stalledSeq) return null;
          const from = nodePos(r.node);
          const to = nodePos(r.stalled);
          return (
            <g key={`b-${r.seq}`} style={{ opacity: vis(r.stalledSeq) }}>
              <path
                d={`M${from.x + NODE_W / 2},${from.y} C${from.x + NODE_W / 2},${from.y - 70} ${to.x + NODE_W / 2},${to.y - 70} ${to.x + NODE_W / 2},${to.y}`}
                fill="none"
                className="stroke-brand-amber"
                strokeWidth={1.6}
                strokeDasharray="5 4"
              />
              <text x={(from.x + to.x) / 2 + NODE_W / 2 - 30} y={Math.min(from.y, to.y) - 62} className="fill-brand-amber text-[11px]">
                ⟲ backtrack — branch pruned
              </text>
            </g>
          );
        })}
        {model.end?.kind === 'done' && layout.end && (() => {
          const last = model.nodes[model.nodes.length - 1];
          const pr = model.rounds.find((r) => r.node === last.id && r.sel);
          if (!pr || !pr.sel) return null;
          const cp = cardPos(pr, pr.sel);
          return <path d={curve(cp.x + CARD_W, cp.y + CARD_H / 2, layout.end.x, layout.end.y + NODE_H / 2)} fill="none" className="stroke-brand-green" strokeWidth={2.2} style={{ opacity: vis(endSeq) }} />;
        })()}
      </svg>

      {model.nodes.map((n) => {
        const p = nodePos(n.id);
        const id = `n:${n.id}`;
        return (
          <button
            key={n.id}
            type="button"
            data-seq={n.seq}
            data-testid="state-node"
            aria-label={`State ${n.id}, depth ${n.depth}`}
            onClick={() => onPick(id)}
            style={{ left: p.x, top: p.y, width: NODE_W, height: NODE_H }}
            className={`absolute rounded-lg border border-brand-purple bg-brand-bg-panel px-2.5 py-1.5 text-left transition-opacity ${
              n.seq <= cursor ? '' : 'pointer-events-none opacity-0'
            } ${picked === id ? 'outline outline-2 outline-offset-2 outline-brand-blue' : ''}`}
          >
            <div className="text-[11px] tracking-wider text-brand-purple">{n.depth === 0 ? 'START' : `STATE ${n.depth}`} · {n.id}</div>
            <div className="text-xs text-brand-green-soft">facts {n.facts} · prog {n.progress.toFixed(2)}</div>
          </button>
        );
      })}

      {model.rounds.map((r) => r.cards.map((c) => (
        <CardView key={cardKey(r, c.fp)} card={c} round={r} cursor={cursor} picked={picked} pos={cardPos(r, c.fp)} onPick={onPick} />
      )))}

      {model.end && layout.end && (
        <button
          type="button"
          data-seq={endSeq}
          data-testid="end-node"
          onClick={() => onPick('end')}
          style={{ left: layout.end.x, top: layout.end.y, width: NODE_W, height: NODE_H }}
          className={`absolute overflow-hidden rounded-lg border bg-brand-bg-panel px-2.5 py-1.5 text-left transition-opacity ${
            model.end.kind === 'done' ? 'border-brand-green' : 'border-brand-red'
          } ${endSeq <= cursor ? '' : 'pointer-events-none opacity-0'}`}
        >
          <div className={`text-[11px] tracking-wider ${model.end.kind === 'done' ? 'text-brand-green' : 'text-brand-red'}`}>
            {model.end.kind === 'done' ? 'GOAL SETTLED' : 'HONEST STOP'}
          </div>
          <div className="line-clamp-2 text-[11px] text-brand-green-soft">
            {model.end.kind === 'done' ? model.end.answer : `NOT SETTLED · ${model.end.reason}`}
          </div>
        </button>
      )}
    </div>
  );
}
