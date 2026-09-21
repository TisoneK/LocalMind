/**
 * State engine model — the pure part of the State Explorer.
 *
 * The backend streams `EngineEvent`s (states, moves, outcomes — never hidden reasoning). This folds a stream
 * into a tree (states → rounds of candidate moves → cards), lays it out, and derives what is true at a point on
 * the run's timeline. No React here, so it is unit-tested directly.
 */

export type EventKind =
  | 'state'
  | 'candidates'
  | 'probe'
  | 'evaluation'
  | 'selected'
  | 'backtrack'
  | 'needs_confirmation'
  | 'done'
  | 'stopped';

export interface CandidateMove {
  fp: string;
  label: string;
  tool: string;
  why: string;
}

/** One record of the stream (`EngineEvent.to_dict()` on the backend). Fields depend on `kind`. */
export interface EngineEvent {
  seq: number;
  t_ms: number;
  kind: EventKind;
  node?: string;
  parent?: string | null;
  at?: string | null;
  goal?: string;
  facts?: number | string[];
  progress?: number;
  fp?: string;
  move?: string;
  why?: string;
  ok?: boolean;
  chars?: number;
  ms?: number;
  excerpt?: string;
  done?: boolean;
  reason?: string;
  moves?: CandidateMove[];
  answer?: string;
  trail?: string[];
  model_calls?: number;
  settled?: boolean;
}

export interface RunMeta {
  provider: string;
  model: string;
  budget: { max_depth: number; max_branches: number; max_model_calls: number; max_backtracks: number };
}

export type CardStatus = 'open' | 'probing' | 'gated' | 'selected' | 'rejected' | 'failed' | 'pruned';

export interface Card {
  fp: string;
  label: string;
  tool: string;
  why: string;
  status: CardStatus;
  probeSeq?: number;
  ok?: boolean;
  ms?: number;
  chars?: number;
  excerpt?: string;
  evalSeq?: number;
  progress?: number;
  reason?: string;
  gateSeq?: number;
}

/** One fan of candidate moves proposed at a state (a state can have several: after a backtrack it is asked again). */
export interface Round {
  node: string;
  seq: number;
  cards: Card[];
  sel: string | null;
  selSeq?: number;
  stalled: string | null;
  stalledSeq?: number;
}

export interface StateNode {
  id: string;
  parent: string | null;
  depth: number;
  seq: number;
  viaFp: string | null;
  facts: number;
  progress: number;
}

export interface Model {
  nodes: StateNode[];
  rounds: Round[];
  end: EngineEvent | null;
}

const factCount = (f: EngineEvent['facts']): number => (Array.isArray(f) ? f.length : Number(f) || 0);

export function buildModel(events: readonly EngineEvent[]): Model {
  const nodes: StateNode[] = [];
  const byId = new Map<string, StateNode>();
  const rounds: Round[] = [];
  let viaFp: string | null = null;
  let last: Round | null = null;
  let end: EngineEvent | null = null;
  const roundAt = (node: string | null | undefined): Round | undefined => {
    for (let i = rounds.length - 1; i >= 0; i--) if (rounds[i].node === node) return rounds[i];
    return undefined;
  };

  for (const e of events) {
    switch (e.kind) {
      case 'state': {
        const parent = e.parent ?? null;
        const depth = parent ? (byId.get(parent)?.depth ?? 0) + 1 : 0;
        const n: StateNode = {
          id: e.node ?? `n${nodes.length}`,
          parent,
          depth,
          seq: e.seq,
          viaFp,
          facts: factCount(e.facts),
          progress: e.progress ?? 0,
        };
        nodes.push(n);
        byId.set(n.id, n);
        viaFp = null;
        break;
      }
      case 'candidates': {
        last = { node: e.at ?? '', seq: e.seq, cards: [], sel: null, stalled: null };
        for (const m of e.moves ?? []) last.cards.push({ ...m, status: 'open' });
        rounds.push(last);
        break;
      }
      case 'probe': {
        const c = roundAt(e.at)?.cards.find((x) => x.fp === e.fp);
        if (c) Object.assign(c, { probeSeq: e.seq, ok: e.ok, ms: e.ms, chars: e.chars, excerpt: e.excerpt });
        break;
      }
      case 'evaluation': {
        const c = roundAt(e.at)?.cards.find((x) => x.fp === e.fp);
        if (c) Object.assign(c, { evalSeq: e.seq, progress: e.progress, reason: e.reason });
        break;
      }
      case 'needs_confirmation': {
        const r = roundAt(e.at);
        if (r) {
          let c = r.cards.find((x) => x.fp === e.fp);
          if (!c) {
            c = { fp: e.fp ?? '', label: e.move ?? '', tool: '', why: e.why ?? '', status: 'gated' };
            r.cards.push(c);
          }
          c.status = 'gated';
          c.gateSeq = e.seq;
        }
        break;
      }
      case 'selected': {
        const r = roundAt(e.at);
        if (r) {
          r.sel = e.fp ?? null;
          r.selSeq = e.seq;
        }
        viaFp = e.fp ?? null;
        break;
      }
      case 'backtrack':
        if (last) {
          last.stalled = e.node ?? null;
          last.stalledSeq = e.seq;
        }
        break;
      case 'done':
      case 'stopped':
        end = e;
        break;
    }
  }
  for (const r of rounds)
    for (const c of r.cards) {
      if (c.status === 'gated') continue;
      c.status = c.ok === false ? 'failed' : c.fp === r.sel ? 'selected' : r.stalled ? 'pruned' : 'rejected';
    }
  return { nodes, rounds, end };
}

/** What a card looks like once the timeline has reached `cursor` events (so a replay reveals it step by step). */
export function cardStatusAt(c: Card, r: Round, cursor: number): CardStatus {
  const sawProbe = !!c.probeSeq && c.probeSeq <= cursor;
  if (c.status === 'gated' && (c.gateSeq ?? 0) <= cursor) return 'gated';
  if (sawProbe && c.ok === false) return 'failed';
  if (r.selSeq && r.selSeq <= cursor && c.fp === r.sel) return 'selected';
  if (r.stalledSeq && r.stalledSeq <= cursor) return 'pruned';
  if (c.evalSeq && c.evalSeq <= cursor) return 'rejected';
  return sawProbe ? 'open' : 'probing';
}

export const NODE_W = 150;
export const NODE_H = 58;
export const CARD_W = 262;
export const CARD_H = 64;
const COL_W = NODE_W + 30 + CARD_W + 68; // a state, its fan of cards, then the next column
const GAP = 8;
const X0 = 24;
const Y0 = 26;

export interface Point {
  x: number;
  y: number;
}

export interface Layout {
  nodes: Map<string, Point>;
  cards: Map<string, Point>; // key: `${round.seq}:${card.fp}`
  end: Point | null;
  width: number;
  height: number;
}

export const cardKey = (r: Round, fp: string) => `${r.seq}:${fp}`;

export function layoutModel(m: Model): Layout {
  const colBottom = new Map<number, number>();
  const nodes = new Map<string, Point>();
  const cards = new Map<string, Point>();
  const roundsBy = new Map<string, Round[]>();
  for (const r of m.rounds) roundsBy.set(r.node, [...(roundsBy.get(r.node) ?? []), r]);
  let maxX = 0;
  let maxY = 0;

  for (const n of m.nodes) {
    const rs = roundsBy.get(n.id) ?? [];
    let want = Y0;
    if (n.parent) {
      const pr = (roundsBy.get(n.parent) ?? []).find((r) => r.sel === n.viaFp);
      const pc = pr && n.viaFp ? cards.get(cardKey(pr, n.viaFp)) : undefined;
      if (pc) want = pc.y;
    }
    let y = Math.max(want, colBottom.get(n.depth) ?? Y0);
    const x = X0 + n.depth * COL_W;
    nodes.set(n.id, { x, y: y + (CARD_H - NODE_H) / 2 });
    for (const r of rs) {
      for (const c of r.cards) {
        cards.set(cardKey(r, c.fp), { x: x + NODE_W + 30, y });
        y += CARD_H + GAP;
      }
      y += 12;
    }
    if (!rs.length) y += NODE_H + 30;
    colBottom.set(n.depth, y);
    maxX = Math.max(maxX, x + NODE_W + 30 + CARD_W + 60);
    maxY = Math.max(maxY, y);
  }

  let end: Point | null = null;
  const lastNode = m.nodes[m.nodes.length - 1];
  if (m.end && lastNode) {
    const p = nodes.get(lastNode.id) as Point;
    if (m.end.kind === 'done') end = { x: p.x + COL_W, y: p.y };
    else {
      const lastRound = [...m.rounds].reverse().find((r) => r.node === lastNode.id);
      const ys = lastRound ? lastRound.cards.map((c) => (cards.get(cardKey(lastRound, c.fp)) as Point).y) : [p.y];
      const mid = (Math.min(...ys) + Math.max(...ys) + CARD_H) / 2 - NODE_H / 2;
      end = { x: p.x + NODE_W + 30 + CARD_W + 34, y: mid };
    }
    maxX = Math.max(maxX, end.x + NODE_W + 60);
  }
  return { nodes, cards, end, width: maxX + 40, height: maxY + 80 };
}

export interface Meters {
  calls: number;
  probes: number;
  backtracks: number;
  depth: number;
  plies: number;
  best: number;
  elapsedMs: number;
}

/** The run's meters as of `cursor` events. A model call = a proposal (candidates) or a scoring (evaluations of a round). */
export function metersAt(events: readonly EngineEvent[], m: Model, cursor: number): Meters {
  const seen = events.slice(0, cursor);
  const depthOf = new Map(m.nodes.map((n) => [n.id, n.depth] as const));
  const scored = new Set<number>();
  let calls = 0;
  let probes = 0;
  let backtracks = 0;
  let depth = 0;
  let plies = 0;
  let best = 0;
  for (const e of seen) {
    if (e.kind === 'candidates') calls++;
    else if (e.kind === 'probe') probes++;
    else if (e.kind === 'backtrack') backtracks++;
    else if (e.kind === 'state') depth = Math.max(depth, depthOf.get(e.node ?? '') ?? 0);
    else if (e.kind === 'selected') {
      plies++;
      best = Math.max(best, e.progress ?? 0);
    } else if (e.kind === 'evaluation') {
      const round = [...m.rounds].reverse().find((r) => r.node === e.at && r.seq < e.seq);
      if (round && !scored.has(round.seq)) {
        scored.add(round.seq);
        calls++;
      }
    }
  }
  return { calls, probes, backtracks, depth, plies, best, elapsedMs: seen.length ? seen[seen.length - 1].t_ms : 0 };
}
