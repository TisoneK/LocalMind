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
  /** What the state actually knows (real observations, bounded) — the engine sends this with each state. */
  fact_list?: string[];
  /** Fingerprints of the moves this state has ruled out. */
  failed_fps?: string[];
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
}/** The run's meters as of `cursor` events. A model call = a proposal (candidates) or a scoring (evaluations of a round). */
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

// ─── Reading one state ──────────────────────────────────────────────────────
// The engine owns the state, so the UI's job is to let you READ it: what it knows, what it has ruled
// out, and how it got here. All of it comes from the events (real observations, real fingerprints).

/** The facts a state holds, newest last. Empty for runs captured before the engine sent them. */
export function factsAt(events: readonly EngineEvent[], node: string): string[] {
  const state = [...events].reverse().find((e) => e.kind === 'state' && e.node === node);
  if (!state) return [];
  if (Array.isArray(state.fact_list)) return state.fact_list;
  return Array.isArray(state.facts) ? state.facts : [];
}

/** The path of applied moves that reached a state, in the engine's own words. */
export function trailAt(events: readonly EngineEvent[], node: string): string[] {
  const state = [...events].reverse().find((e) => e.kind === 'state' && e.node === node);
  return state?.trail ?? [];
}

/** The label a fingerprint belongs to, when the run proposed it (otherwise the fingerprint itself). */
export function labelForFp(m: Model, fp: string): string {
  for (const r of m.rounds) {
    const c = r.cards.find((x) => x.fp === fp);
    if (c?.label) return c.label;
  }
  return fp;
}

/** The moves a state has ruled out — a real fingerprint list, labelled with the move that produced it. */
export function failedAt(events: readonly EngineEvent[], m: Model, node: string): { fp: string; label: string }[] {
  const state = [...events].reverse().find((e) => e.kind === 'state' && e.node === node);
  return (state?.failed_fps ?? []).map((fp) => ({ fp, label: labelForFp(m, fp) }));
}

/** The states on the path from the start to `node` (inclusive). */
export function pathTo(m: Model, node: string): StateNode[] {
  const out: StateNode[] = [];
  for (let n: StateNode | undefined = m.nodes.find((x) => x.id === node); n; n = m.nodes.find((x) => x.id === n?.parent)) out.unshift(n);
  return out;
}

/** The state a node's own fan is at (the round hangs off the state it was proposed from). */
export const roundOf = (m: Model, node: string): Round | undefined => [...m.rounds].reverse().find((r) => r.node === node);

// ─── Layers and the spine: two ways to read a big tree ──────────────────────

export interface Layers {
  /** Show the fan of proposed moves at all (off = the bare state graph). */
  moves: boolean;
  /** Show moves whose probe really failed. */
  failed: boolean;
  /** Show moves that were scored below the best (the losers of a round). */
  rejected: boolean;
  /** Show branches a backtrack pruned. */
  pruned: boolean;
}

export const ALL_LAYERS: Layers = { moves: true, failed: true, rejected: true, pruned: true };

export function cardVisible(status: CardStatus, layers: Layers): boolean {
  if (status === 'failed') return layers.failed;
  if (status === 'rejected') return layers.rejected;
  if (status === 'pruned') return layers.pruned;
  return true;
}

/** The chosen path: for each state on it, the fingerprint of the move that led out of it. */
export function spine(m: Model): { node: string; fp: string }[] {
  const out: { node: string; fp: string }[] = [];
  for (const n of m.nodes) {
    const r = m.rounds.find((x) => x.node === n.id && x.sel);
    if (r?.sel) out.push({ node: n.id, fp: r.sel });
  }
  return out;
}

/** True when `node` is on the chosen path (a node reached by a selected move, or the start). */
export function onSpine(m: Model, node: string): boolean {
  return pathTo(m, node).every((n) => n.parent === null || !!m.rounds.find((r) => r.node === n.parent && r.sel === n.viaFp));
}

// ─── The budget the run actually spent, and how it went ─────────────────────

/** Best progress reached after each applied move — the run's curve, for a sparkline. */
export function progressCurve(events: readonly EngineEvent[], cursor: number): number[] {
  const out: number[] = [];
  for (const e of events.slice(0, cursor)) if (e.kind === 'selected') out.push(e.progress ?? 0);
  return out;
}

export interface Spend {
  /** Wall clock of the run as of the cursor (the engine's own clock). */
  elapsedMs: number;
  /** Time really spent inside read-only probes — measured by the engine, not estimated. */
  probeMs: number;
  /** The slowest single probe, with the move that cost it. */
  slowest: { label: string; ms: number } | null;
}

export function spendAt(events: readonly EngineEvent[], cursor: number): Spend {
  let probeMs = 0;
  let slowest: Spend['slowest'] = null;
  const seen = events.slice(0, cursor);
  for (const e of seen) {
    if (e.kind === 'probe') {
      probeMs += e.ms ?? 0;
      if (!slowest || (e.ms ?? 0) > slowest.ms) slowest = { label: e.move ?? '', ms: e.ms ?? 0 };
    }
  }
  return { elapsedMs: seen.length ? seen[seen.length - 1].t_ms : 0, probeMs, slowest };
}

// ─── A run as a row in a comparison ─────────────────────────────────────────

export interface RunLike {
  id: string;
  title: string;
  goal: string;
  events: EngineEvent[];
  live: boolean;
  aborted: boolean;
}

export interface RunSummary {
  id: string;
  title: string;
  goal: string;
  outcome: 'settled' | 'not_settled' | 'running' | 'stopped';
  answer: string;
  reason: string;
  calls: number;
  probes: number;
  plies: number;
  depth: number;
  backtracks: number;
  best: number;
  elapsedMs: number;
  tools: string[];
}

const toolOf = (label: string): string => label.split('(')[0].trim() || label;

export function summarize(run: RunLike): RunSummary {
  const m = buildModel(run.events);
  const meters = metersAt(run.events, m, run.events.length);
  const tools = [...new Set(m.rounds.flatMap((r) => r.cards).map((c) => toolOf(c.label)))].filter(Boolean);
  const outcome: RunSummary['outcome'] = run.live
    ? 'running'
    : m.end?.kind === 'done'
      ? 'settled'
      : m.end
        ? 'not_settled'
        : 'stopped';
  return {
    id: run.id,
    title: run.title,
    goal: run.goal,
    outcome,
    answer: m.end?.kind === 'done' ? String(m.end.answer ?? '') : '',
    reason: m.end?.kind === 'stopped' ? String(m.end.reason ?? '') : '',
    calls: meters.calls,
    probes: meters.probes,
    plies: meters.plies,
    depth: meters.depth,
    backtracks: meters.backtracks,
    best: meters.best,
    elapsedMs: meters.elapsedMs,
    tools,
  };
}

// ─── Evidence out: the run as a file, and as a paragraph ────────────────────

/** The run, replayable: the meta line and every event, exactly as the engine sent them. */
export function runToJson(run: RunLike & { meta?: RunMeta }): string {
  return JSON.stringify({ goal: run.goal, meta: run.meta ?? null, events: run.events }, null, 2);
}

/** A plain summary of the run — what it settled, what it cost, and the moves it made. */
export function runToMarkdown(run: RunLike & { meta?: RunMeta }): string {
  const s = summarize(run);
  const m = buildModel(run.events);
  const lines = [
    `# State engine run`,
    '',
    `**Goal:** ${run.goal}`,
    run.meta ? `**Engine:** ${run.meta.provider} · ${run.meta.model} · budget ${run.meta.budget.max_model_calls} model calls, depth ${run.meta.budget.max_depth}, ${run.meta.budget.max_branches} branches, ${run.meta.budget.max_backtracks} backtracks` : '',
    `**Outcome:** ${s.outcome === 'settled' ? `settled — ${s.answer}` : s.outcome === 'not_settled' ? `NOT settled — ${s.reason}` : s.outcome}`,
    `**Spent:** ${s.calls} model calls · ${s.probes} probes · ${s.plies} plies · depth ${s.depth} · ${s.backtracks} backtracks · ${(s.elapsedMs / 1000).toFixed(1)}s`,
    `**Tools used:** ${s.tools.join(', ') || '—'}`,
    '',
    '## Moves',
    '',
  ];
  for (const e of run.events) {
    if (e.kind === 'selected') lines.push(`- **selected** \`${e.move}\` — progress ${(e.progress ?? 0).toFixed(2)}`);
    else if (e.kind === 'backtrack') lines.push(`- *backtrack* to ${e.node} — the branch was pruned`);
    else if (e.kind === 'needs_confirmation') lines.push(`- needs confirmation: \`${e.move}\` (not read-only)`);
    else if (e.kind === 'probe' && e.ok === false) lines.push(`- probe failed: \`${e.move}\` — ${e.excerpt ?? ''}`.trim());
  }
  const end = m.end;
  if (end?.trail?.length) lines.push('', `**Path:** ${end.trail.join(' → ')}`);
  return lines.filter((l) => l !== undefined).join('\n');
}

