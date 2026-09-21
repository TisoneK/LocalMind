/**
 * The State Explorer's model layer, tested against a real captured run (the sample shipped with the
 * explorer) plus synthetic streams for the states the sample does not contain — a backtrack and a
 * move the engine refused to run.
 */

import { describe, expect, it } from 'vitest';
import {
  ALL_LAYERS,
  buildModel,
  cardStatusAt,
  cardVisible,
  failedAt,
  factsAt,
  labelForFp,
  layoutModel,
  metersAt,
  onSpine,
  pathTo,
  progressCurve,
  runToJson,
  runToMarkdown,
  spendAt,
  spine,
  summarize,
  trailAt,
  type EngineEvent,
} from './stateEngine';
import { SAMPLE_EVENTS } from '@/components/engine/sampleRun';

const ev = (partial: Partial<EngineEvent> & { seq: number; kind: EngineEvent['kind'] }): EngineEvent => ({
  t_ms: partial.seq * 100,
  ...partial,
});

describe('buildModel', () => {
  it('folds the captured run into a tree of states with one fan of moves each', () => {
    const m = buildModel(SAMPLE_EVENTS);
    expect(m.nodes.map((n) => [n.id, n.depth, n.parent])).toEqual([
      ['n0', 0, null],
      ['n1', 1, 'n0'],
      ['n2', 2, 'n1'],
    ]);
    expect(m.rounds).toHaveLength(2);
    expect(m.end?.kind).toBe('done');
  });

  it('resolves every card once the run ends — the chosen move selected, the rest rejected', () => {
    const m = buildModel(SAMPLE_EVENTS);
    for (const r of m.rounds) {
      expect(r.sel).toBeTruthy();
      for (const c of r.cards) {
        expect(['selected', 'rejected', 'failed']).toContain(c.status);
        expect(c.excerpt?.length ?? 0).toBeGreaterThan(0); // every probe kept its real observation
      }
      expect(r.cards.find((c) => c.fp === r.sel)?.status).toBe('selected');
    }
  });

  it('keeps the observation and the judgement of each probe on its card', () => {
    const m = buildModel(SAMPLE_EVENTS);
    const scored = m.rounds.flatMap((r) => r.cards).filter((c) => c.progress != null);
    expect(scored.length).toBeGreaterThan(0);
    expect(scored.every((c) => !!c.excerpt && c.ms != null)).toBe(true);
  });

  it('marks a move the engine would not run as gated, and keeps it gated after the run', () => {
    const m = buildModel([
      ev({ seq: 1, kind: 'state', node: 'n0', parent: null, facts: 0, progress: 0 }),
      ev({
        seq: 2,
        kind: 'candidates',
        at: 'n0',
        moves: [
          { fp: 'aa', label: 'file_write(x)', tool: 'file_write', why: 'would settle it' },
          { fp: 'bb', label: 'file_read(y)', tool: 'file_read', why: 'look first' },
        ],
      }),
      ev({ seq: 3, kind: 'needs_confirmation', at: 'n0', fp: 'aa', move: 'file_write(x)', why: 'not read-only' }),
      ev({ seq: 4, kind: 'probe', at: 'n0', fp: 'bb', ok: true, ms: 12, chars: 40, excerpt: 'y' }),
      ev({ seq: 5, kind: 'evaluation', at: 'n0', fp: 'bb', progress: 0.4, reason: 'answers it' }),
      ev({ seq: 6, kind: 'selected', at: 'n0', fp: 'bb', move: 'file_read(y)', progress: 0.4 }),
      ev({ seq: 7, kind: 'state', node: 'n1', parent: 'n0', facts: 1, progress: 0.4 }),
      ev({ seq: 8, kind: 'stopped', reason: 'budget', settled: false, trail: [], model_calls: 3 }),
    ]);
    const gated = m.rounds[0].cards.find((c) => c.fp === 'aa');
    expect(gated?.status).toBe('gated');
    expect(m.nodes.map((n) => n.id)).toEqual(['n0', 'n1']);
    expect(m.end?.kind).toBe('stopped');
  });

  it('records a backtrack as a stalled round whose cards are pruned', () => {
    const m = buildModel([
      ev({ seq: 1, kind: 'state', node: 'n0', parent: null, facts: 0, progress: 0 }),
      ev({
        seq: 2,
        kind: 'candidates',
        at: 'n0',
        moves: [{ fp: 'aa', label: 'shell(ls)', tool: 'shell', why: 'list it' }],
      }),
      ev({ seq: 3, kind: 'probe', at: 'n0', fp: 'aa', ok: true, ms: 8, chars: 10, excerpt: 'nothing useful' }),
      ev({ seq: 4, kind: 'backtrack', node: 'n0', reason: 'no move improved the state' }),
      ev({ seq: 5, kind: 'stopped', reason: 'nothing beats the current state', settled: false, trail: [], model_calls: 2 }),
    ]);
    expect(m.rounds[0].stalled).toBe('n0');
    expect(m.rounds[0].cards[0].status).toBe('pruned');
  });
});

describe('cardStatusAt — what the timeline has revealed so far', () => {
  const events: EngineEvent[] = [
    ev({ seq: 1, kind: 'state', node: 'n0', parent: null, facts: 0, progress: 0 }),
    ev({
      seq: 2,
      kind: 'candidates',
      at: 'n0',
      moves: [
        { fp: 'aa', label: 'dir_explorer(~/Code)', tool: 'dir_explorer', why: 'see the folders' },
        { fp: 'bb', label: 'file_read(missing)', tool: 'file_read', why: 'maybe this path' },
      ],
    }),
    ev({ seq: 3, kind: 'probe', at: 'n0', fp: 'aa', ok: true, ms: 30, chars: 200, excerpt: 'a' }),
    ev({ seq: 4, kind: 'probe', at: 'n0', fp: 'bb', ok: false, ms: 5, chars: 0, excerpt: 'no such file' }),
    ev({ seq: 5, kind: 'evaluation', at: 'n0', fp: 'aa', progress: 0.6, reason: 'reveals the layout' }),
    ev({ seq: 6, kind: 'evaluation', at: 'n0', fp: 'bb', progress: 0.0, reason: 'answered nothing' }),
    ev({ seq: 7, kind: 'selected', at: 'n0', fp: 'aa', move: 'dir_explorer(~/Code)', progress: 0.6 }),
    ev({
      seq: 8,
      kind: 'candidates',
      at: 'n1',
      moves: [
        { fp: 'cc', label: 'file_task(other)', tool: 'file_task', why: 'read the wrong README' },
        { fp: 'dd', label: 'file_task(right)', tool: 'file_task', why: 'read the right README' },
      ],
    }),
    ev({ seq: 9, kind: 'probe', at: 'n1', fp: 'cc', ok: true, ms: 9, chars: 80, excerpt: 'the other project' }),
    ev({ seq: 10, kind: 'probe', at: 'n1', fp: 'dd', ok: true, ms: 9, chars: 80, excerpt: 'React 19' }),
    ev({ seq: 11, kind: 'evaluation', at: 'n1', fp: 'cc', progress: 0.1, reason: 'answers a different question' }),
    ev({ seq: 12, kind: 'evaluation', at: 'n1', fp: 'dd', progress: 0.9, reason: 'answers it' }),
    ev({ seq: 13, kind: 'selected', at: 'n1', fp: 'dd', move: 'file_task(right)', progress: 0.9 }),
  ];

  it('reveals the fan before the probes, then the failure, then the choice', () => {
    const m = buildModel(events);
    const r = m.rounds[0];
    const a = r.cards.find((c) => c.fp === 'aa')!;
    const b = r.cards.find((c) => c.fp === 'bb')!;
    expect(cardStatusAt(a, r, 2)).toBe('probing'); // proposed, nothing probed yet
    expect(cardStatusAt(a, r, 3)).toBe('open'); // probed ok, not yet judged
    expect(cardStatusAt(b, r, 4)).toBe('failed'); // a probe that really failed
    expect(cardStatusAt(b, r, 6)).toBe('failed'); // ... and a failed probe stays a failure, not a mere rejection
    expect(cardStatusAt(a, r, 7)).toBe('selected'); // the chosen move
    expect(cardStatusAt(b, r, 7)).toBe('failed');
  });

  it('shows a probed, scored, unchosen move as rejected — the branch that never fails', () => {
    const m = buildModel(events);
    const r = m.rounds[1]; // at n1: cc and dd both probe fine; cc scores low and is not chosen
    const cc = r.cards.find((c) => c.fp === 'cc')!;
    const dd = r.cards.find((c) => c.fp === 'dd')!;
    expect(cardStatusAt(cc, r, 10)).toBe('open');
    expect(cardStatusAt(cc, r, 11)).toBe('rejected');
    expect(cardStatusAt(dd, r, 13)).toBe('selected');
  });

  it('never reveals more than the cursor has reached', () => {
    const m = buildModel(events);
    const r = m.rounds[0];
    for (const c of r.cards) expect(['probing', 'open']).toContain(cardStatusAt(c, r, 2));
    expect(cardStatusAt(r.cards[0], r, 1)).toBe('probing');
  });
});

describe('layoutModel', () => {
  it('lays the captured run out in columns by depth and never overlaps two cards', () => {
    const m = buildModel(SAMPLE_EVENTS);
    const layout = layoutModel(m);
    expect([...layout.nodes.values()].map((p) => p.x)).toEqual([...new Set([...layout.nodes.values()].map((p) => p.x))]);
    const boxes = m.rounds.flatMap((r) =>
      r.cards.map((c) => ({ ...(layout.cards.get(`${r.seq}:${c.fp}`) as { x: number; y: number }) }))
    );
    for (let i = 0; i < boxes.length; i++)
      for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i];
        const b = boxes[j];
        const overlaps = a.x < b.x + 262 && b.x < a.x + 262 && a.y < b.y + 64 && b.y < a.y + 64;
        expect(overlaps).toBe(false);
      }
    expect(layout.width).toBeGreaterThan(0);
    expect(layout.end).not.toBeNull();
  });

  it('still places an end marker for an honest stop', () => {
    const m = buildModel([
      ev({ seq: 1, kind: 'state', node: 'n0', parent: null, facts: 0, progress: 0 }),
      ev({
        seq: 2,
        kind: 'candidates',
        at: 'n0',
        moves: [{ fp: 'aa', label: 'shell(ls)', tool: 'shell', why: 'list' }],
      }),
      ev({ seq: 3, kind: 'probe', at: 'n0', fp: 'aa', ok: true, ms: 4, chars: 4, excerpt: 'meh' }),
      ev({ seq: 4, kind: 'stopped', reason: 'no improvement', settled: false, trail: [], model_calls: 2 }),
    ]);
    const layout = layoutModel(m);
    expect(layout.end).not.toBeNull();
    expect(layout.end!.x).toBeGreaterThan(layout.nodes.get('n0')!.x);
  });
});

describe('metersAt', () => {  it('counts model calls as proposals plus scorings — the same number the engine reports', () => {    const m = buildModel(SAMPLE_EVENTS);
    const meters = metersAt(SAMPLE_EVENTS, m, SAMPLE_EVENTS.length);
    expect(meters.calls).toBe(m.end?.model_calls); // 4: two fans proposed, two rounds scored
    expect(meters.probes).toBe(6);
    expect(meters.plies).toBe(2);
    expect(meters.depth).toBe(2);
    expect(meters.backtracks).toBe(0);
    expect(meters.best).toBeGreaterThan(0.5);
  });

  it('rewinds with the timeline instead of reporting the whole run', () => {
    const m = buildModel(SAMPLE_EVENTS);
    const fresh = metersAt(SAMPLE_EVENTS, m, 1);
    expect(fresh.calls).toBe(0);
    expect(fresh.probes).toBe(0);
    expect(fresh.elapsedMs).toBe(0);
  });
});

// ─── Reading a state, reading a big tree, and comparing two runs ─────────────

const RICH: EngineEvent[] = [
  ev({ seq: 1, kind: 'state', node: 'n0', parent: null, facts: 0, fact_list: [], failed_fps: [], trail: [], progress: 0 }),
  ev({
    seq: 2,
    kind: 'candidates',
    at: 'n0',
    moves: [
      { fp: 'aa', label: 'dir_explorer(~)', tool: 'dir_explorer', why: 'see the folders' },
      { fp: 'bb', label: 'file_read(/missing)', tool: 'file_read', why: 'maybe here' },
    ],
  }),
  ev({ seq: 3, kind: 'probe', at: 'n0', fp: 'aa', ok: true, ms: 30, chars: 100, excerpt: 'notes/', move: 'dir_explorer(~)' }),
  ev({ seq: 4, kind: 'probe', at: 'n0', fp: 'bb', ok: false, ms: 5, chars: 0, excerpt: 'no such file', move: 'file_read(/missing)' }),
  ev({ seq: 5, kind: 'evaluation', at: 'n0', fp: 'aa', progress: 0.7, reason: 'names them' }),
  ev({ seq: 6, kind: 'evaluation', at: 'n0', fp: 'bb', progress: 0, reason: 'nothing' }),
  ev({ seq: 7, kind: 'selected', at: 'n0', fp: 'aa', move: 'dir_explorer(~)', progress: 0.7 }),
  ev({
    seq: 8,
    kind: 'state',
    node: 'n1',
    parent: 'n0',
    facts: 1,
    fact_list: ['dir_explorer(~) -> ok: notes/'],
    failed_fps: ['bb'],
    trail: ['dir_explorer(~)'],
    progress: 0.7,
  }),
  ev({ seq: 9, kind: 'done', at: 'n1', answer: 'three files', trail: ['dir_explorer(~)'], model_calls: 2, settled: true }),
];

describe('reading one state', () => {
  it('gives back the facts a state holds, and nothing when the run predates them', () => {
    expect(factsAt(RICH, 'n1')).toEqual(['dir_explorer(~) -> ok: notes/']);
    expect(factsAt(RICH, 'n0')).toEqual([]);
    expect(factsAt(SAMPLE_EVENTS, 'n1')).toEqual([]); // captured before states carried their content
  });

  it('names the path that reached a state, in the engine words', () => {
    expect(trailAt(RICH, 'n1')).toEqual(['dir_explorer(~)']);
    expect(pathTo(buildModel(RICH), 'n1').map((n) => n.id)).toEqual(['n0', 'n1']);
  });

  it('resolves the moves a state ruled out to the words the engine proposed them in', () => {
    const failed = failedAt(RICH, buildModel(RICH), 'n1');
    expect(failed).toEqual([{ fp: 'bb', label: 'file_read(/missing)' }]);
    expect(labelForFp(buildModel(RICH), 'nope')).toBe('nope'); // an unknown fingerprint stays itself
  });
});

describe('layers and the spine', () => {
  it('hides a kind of move when its layer is off, but never a move still being probed', () => {
    expect(cardVisible('rejected', { ...ALL_LAYERS, rejected: false })).toBe(false);
    expect(cardVisible('failed', { ...ALL_LAYERS, failed: false })).toBe(false);
    expect(cardVisible('probing', { ...ALL_LAYERS, moves: false })).toBe(true);
    expect(cardVisible('selected', { ...ALL_LAYERS, moves: false })).toBe(true);
  });

  it('knows which states are on the chosen path', () => {
    const m2 = buildModel([
      ...RICH.slice(0, 7),
      // a second fan at n0 that is NOT chosen, leading to a node reached by a loser
      ev({ seq: 8, kind: 'candidates', at: 'n0', moves: [{ fp: 'cc', label: 'shell(ls)', tool: 'shell', why: 'other' }] }),
      ev({ seq: 9, kind: 'probe', at: 'n0', fp: 'cc', ok: true, ms: 4, chars: 4, excerpt: 'x', move: 'shell(ls)' }),
      ev({ seq: 10, kind: 'evaluation', at: 'n0', fp: 'cc', progress: 0.1, reason: 'less' }),
      ev({ seq: 11, kind: 'selected', at: 'n0', fp: 'aa', move: 'dir_explorer(~)', progress: 0.7 }),
      ev({ seq: 12, kind: 'state', node: 'n1', parent: 'n0', facts: 1, fact_list: ['f'], failed_fps: [], trail: ['dir_explorer(~)'], progress: 0.7 }),
    ]);
    expect(spine(m2)).toEqual([{ node: 'n0', fp: 'aa' }]);
    expect(onSpine(m2, 'n1')).toBe(true);
  });
});

describe('what a run spent, and what it is worth', () => {
  it('measures probe time from the engine numbers and finds the slowest one', () => {
    const spend = spendAt(RICH, RICH.length);
    expect(spend.probeMs).toBe(35);
    expect(spend.slowest).toEqual({ label: 'dir_explorer(~)', ms: 30 });
    const fresh = spendAt(RICH, 1);
    expect(fresh.probeMs).toBe(0);
    expect(fresh.slowest).toBeNull();
    expect(fresh.elapsedMs).toBe(RICH[0].t_ms); // nothing spent yet, and the clock is the engine's own
  });

  it('draws the run curve from the moves actually applied', () => {
    expect(progressCurve(RICH, RICH.length)).toEqual([0.7]);
    expect(progressCurve(RICH, 6)).toEqual([]);
  });

  it('summarizes a run for a comparison, and says when it did not settle', () => {
    const s = summarize({ id: 'r', title: 't', goal: 'g', events: RICH, live: false, aborted: false });
    expect(s).toMatchObject({ outcome: 'settled', answer: 'three files', calls: 2, probes: 2, plies: 1, best: 0.7 });
    expect(s.tools).toEqual(['dir_explorer', 'file_read']);
    const stopped = summarize({
      id: 'r2',
      title: 't2',
      goal: 'g',
      events: [ev({ seq: 1, kind: 'state', node: 'n0', parent: null }), ev({ seq: 2, kind: 'stopped', reason: 'budget', settled: false, trail: [], model_calls: 2 })],
      live: false,
      aborted: false,
    });
    expect(stopped.outcome).toBe('not_settled');
    expect(stopped.reason).toBe('budget');
  });

  it('hands the run out as evidence: the raw events, and a paragraph a person can read', () => {
    const run = { id: 'r', title: 't', goal: 'how many notes files', events: RICH, live: false, aborted: false };
    const parsed = JSON.parse(runToJson(run));
    expect(parsed.goal).toBe('how many notes files');
    expect(parsed.events).toHaveLength(RICH.length);
    const md = runToMarkdown(run);
    expect(md).toContain('# State engine run');
    expect(md).toContain('**Outcome:** settled — three files');
    expect(md).toContain('probe failed: `file_read(/missing)`');
    expect(md).toContain('**Path:** dir_explorer(~)');
  });
});
