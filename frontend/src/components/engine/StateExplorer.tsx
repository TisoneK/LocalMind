/**
 * State Explorer — the interface of the state-driven engine (experimental, ADR-71).
 *
 * The engine is not a chat: it holds a state, fans out candidate moves, really probes the read-only ones, keeps
 * the best and backtracks from dead ends. So this pane shows a game tree — states, moves and outcomes, never
 * hidden reasoning — with a PGN-style move list, an eval bar, an inspector with the real observation behind each
 * move, budget meters and a rewindable timeline. It replaces the chat pane while the State engine is selected.
 */

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { localmindClient, type StateEngineInfo } from '@/lib/localmind/client';
import {
  buildModel,
  layoutModel,
  metersAt,
  type EngineEvent,
  type Model,
  type RunMeta,
} from '@/lib/localmind/stateEngine';
import { StateTree } from './StateTree';
import { SAMPLE_EVENTS, SAMPLE_GOAL } from './sampleRun';

interface Run {
  id: string;
  title: string;
  goal: string;
  events: EngineEvent[];
  meta?: RunMeta;
  live: boolean;
  aborted: boolean;
}

const DEFAULT_BUDGET = { max_depth: 6, max_branches: 3, max_model_calls: 16, max_backtracks: 2 };
const SAMPLE: Run = { id: 'sample', title: 'Sample · find a README', goal: SAMPLE_GOAL, events: SAMPLE_EVENTS, live: false, aborted: false };

function Meter({ label, value, max }: { label: string; value: string | number; max?: number }) {
  return (
    <span className="flex items-center gap-1.5 whitespace-nowrap">
      <span className="text-brand-green-muted">{label}</span>
      <b className="font-medium text-brand-green-soft">{value}</b>
      {max ? (
        <span className="inline-block h-1.5 w-11 overflow-hidden rounded bg-brand-border">
          <span className="block h-full bg-brand-purple" style={{ width: `${Math.min(100, (Number(value) / max) * 100)}%` }} />
        </span>
      ) : null}
    </span>
  );
}

export function StateExplorer() {
  const [runs, setRuns] = useState<Run[]>([SAMPLE]);
  const [activeId, setActiveId] = useState('sample');
  const [pin, setPin] = useState<number | null>(null); // null = follow the latest event
  const [playing, setPlaying] = useState(false);
  const [picked, setPicked] = useState<string | null>(null);
  const [userScale, setUserScale] = useState<number | null>(null);
  const [stage, setStage] = useState({ w: 800, h: 480 });
  const [goalText, setGoalText] = useState('');
  const [info, setInfo] = useState<StateEngineInfo | null>(null);
  const [offline, setOffline] = useState(false);
  const stageRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const run = runs.find((r) => r.id === activeId) ?? runs[0];
  const total = run.events.length;
  const cursor = Math.max(1, Math.min(pin ?? total, total || 1));
  const model: Model = useMemo(() => buildModel(run.events), [run.events]);
  const layout = useMemo(() => layoutModel(model), [model]);
  const meters = useMemo(() => metersAt(run.events, model, cursor), [run.events, model, cursor]);
  const budget = run.meta?.budget ?? DEFAULT_BUDGET;
  const finished = !!model.end && model.end.seq <= cursor;
  const runTotalMs = run.events.length ? Math.max(1, run.events[run.events.length - 1].t_ms) : 1;

  // What the backend will use (provider/model). A failure means there is no backend to run live against.
  useEffect(() => {
    let live = true;
    localmindClient
      .getStateEngineInfo()
      .then((i) => live && setInfo(i))
      .catch(() => live && setOffline(true));
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => () => abortRef.current?.abort(), []);

  // Fit the tree to the pane; resizing refits (unless the user zoomed by hand).
  useEffect(() => {
    const el = stageRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => setStage({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const fitScale = Math.max(0.25, Math.min(1, (stage.w - 16) / layout.width, (stage.h - 16) / layout.height));
  const scale = userScale ?? fitScale;

  // Follow the newest element while a run is streaming or playing.
  useEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    let latest: HTMLElement | null = null;
    let best = -1;
    el.querySelectorAll<HTMLElement>('[data-seq]').forEach((n) => {
      const s = Number(n.dataset.seq);
      if (s <= cursor && s > best) {
        best = s;
        latest = n;
      }
    });
    (latest as HTMLElement | null)?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
  }, [cursor, activeId]);

  // Replay: step through the events at roughly the pace they happened.
  useEffect(() => {
    if (!playing) return;
    const a = run.events[cursor - 1];
    const b = run.events[cursor];
    const wait = a && b ? Math.max(110, Math.min(900, (b.t_ms - a.t_ms) * 0.55)) : 200;
    const t = setTimeout(() => {
      if (cursor >= total) setPlaying(false);
      else setPin(cursor + 1);
    }, wait);
    return () => clearTimeout(t);
  }, [playing, cursor, run.events, total]);

  const pause = useCallback(() => setPlaying(false), []);
  const play = () => {
    setPin(cursor >= total ? 1 : cursor);
    setPlaying(true);
  };
  const step = (d: number) => {
    setPlaying(false);
    setPin(Math.max(1, Math.min(total, cursor + d)));
  };
  const jump = (seq: number) => {
    setPlaying(false);
    setPin(seq);
  };
  const select = (id: string) => {
    setPlaying(false);
    setActiveId(id);
    setPin(null);
    setPicked(null);
    setUserScale(null);
  };

  const startLive = async (goal: string) => {
    const id = `live-${Date.now()}`;
    const ctl = new AbortController();
    abortRef.current = ctl;
    const fresh: Run = { id, title: `Live · ${goal.slice(0, 36)}`, goal, events: [], live: true, aborted: false };
    setRuns((rs) => [...rs, fresh]);
    select(id);
    const patch = (fn: (r: Run) => Run) => setRuns((rs) => rs.map((r) => (r.id === id ? fn(r) : r)));
    try {
      await localmindClient.runStateEngine(
        goal,
        {
          onMeta: (meta) => patch((r) => ({ ...r, meta })),
          onEvent: (e) => patch((r) => ({ ...r, events: [...r.events, e] })),
        },
        ctl.signal
      );
    } catch (err) {
      if ((err as Error).name === 'AbortError') patch((r) => ({ ...r, aborted: true }));
      else
        patch((r) => ({
          ...r,
          events: [
            ...r.events,
            { seq: r.events.length + 1, t_ms: r.events.at(-1)?.t_ms ?? 0, kind: 'stopped', reason: `error: ${(err as Error).message}`, settled: false, trail: [], model_calls: 0 },
          ],
        }));
    } finally {
      patch((r) => ({ ...r, live: false }));
      if (abortRef.current === ctl) abortRef.current = null;
    }
  };
  const busy = runs.some((r) => r.live);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const g = goalText.trim();
    if (g.length >= 3 && !busy) void startLive(g);
  };

  const onKey = (e: KeyboardEvent) => {
    const tag = (e.target as HTMLElement).tagName;
    if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
    if (e.key === ' ') {
      e.preventDefault();
      if (playing) pause();
      else play();
    } else if (e.key === 'ArrowRight') step(1);
    else if (e.key === 'ArrowLeft') step(-1);
    else if (e.key === 'Home') jump(1);
    else if (e.key === 'End') {
      setPlaying(false);
      setPin(null);
    } else if (e.key === '0') setUserScale(null);
    else if (e.key === '+' || e.key === '=') setUserScale(Math.min(1.6, scale * 1.2));
    else if (e.key === '-') setUserScale(Math.max(0.3, scale / 1.2));
  };

  const pill = finished
    ? model.end?.kind === 'done'
      ? { text: 'SETTLED', cls: 'border-brand-green text-brand-green' }
      : { text: 'NOT SETTLED', cls: 'border-brand-red text-brand-red' }
    : run.live
      ? { text: 'LIVE', cls: 'border-brand-blue text-brand-blue' }
      : run.aborted
        ? { text: 'STOPPED', cls: 'border-brand-amber text-brand-amber' }
        : { text: cursor >= total ? 'REPLAY' : 'RUNNING', cls: 'border-brand-amber text-brand-amber' };

  const moves = run.events.filter((e) => ['selected', 'backtrack', 'needs_confirmation', 'done', 'stopped'].includes(e.kind));
  let ply = 0;

  return (
    <section
      data-testid="state-explorer"
      aria-label="State Explorer"
      tabIndex={0}
      onKeyDown={onKey}
      className="flex h-full min-h-0 flex-col bg-brand-bg-base font-mono text-xs text-brand-green-soft outline-none"
    >
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-brand-border bg-brand-bg-panel px-4 py-2.5">
        <div className="font-bold tracking-[0.14em] text-brand-green">STATE EXPLORER</div>
        <select
          aria-label="Run"
          value={activeId}
          onChange={(e) => select(e.target.value)}
          className="max-w-[260px] rounded-md border border-brand-border-strong bg-brand-bg-panel-alt px-2 py-1"
        >
          {runs.map((r, i) => (
            <option key={r.id} value={r.id}>{`${i + 1}. ${r.title}`}</option>
          ))}
        </select>
        <span className={`rounded-full border px-2.5 py-0.5 font-bold tracking-wider ${pill.cls}`} data-testid="run-pill">{pill.text}</span>
        <div className="min-w-0 flex-1 basis-64 truncate text-brand-green-soft" title={run.goal}>
          <span className="mr-1.5 text-brand-green-muted">GOAL</span>{run.goal}
        </div>
        <form onSubmit={submit} className="flex basis-full items-center gap-2" autoComplete="off">
          <input
            aria-label="Goal"
            value={goalText}
            onChange={(e) => setGoalText(e.target.value)}
            disabled={busy || offline}
            maxLength={2000}
            placeholder="Give the engine a goal — it can look and read, never change anything"
            className="min-w-0 flex-1 rounded-md border border-brand-border-strong bg-brand-bg-panel-alt px-2.5 py-1.5 text-brand-green-soft placeholder:text-brand-green-faint disabled:opacity-50"
          />
          {busy ? (
            <button type="button" onClick={() => abortRef.current?.abort()} className="rounded-md border border-brand-red px-3 py-1.5 text-brand-red">■ stop</button>
          ) : (
            <button type="submit" disabled={offline || goalText.trim().length < 3} className="rounded-md border border-brand-green px-3 py-1.5 text-brand-green disabled:opacity-50">▶ run live</button>
          )}
          <span className="hidden text-brand-green-muted md:inline" data-testid="engine-note">
            {offline ? 'Live runs need the LocalMind backend.' : info ? `${info.provider} · ${info.model} · ${info.tools.length} read-only tools` : ''}
          </span>
        </form>
      </header>

      <div className="flex flex-wrap gap-x-5 gap-y-1 border-b border-brand-border bg-brand-bg-panel-alt px-4 py-1.5" data-testid="meters">
        <Meter label="MODEL CALLS" value={meters.calls} max={budget.max_model_calls} />
        <Meter label="DEPTH" value={meters.depth} max={budget.max_depth} />
        <Meter label="BACKTRACKS" value={meters.backtracks} max={budget.max_backtracks} />
        <Meter label="PROBES" value={meters.probes} />
        <Meter label="ELAPSED" value={`${(meters.elapsedMs / 1000).toFixed(1)}s`} />
        <Meter label="PLY" value={meters.plies} />
      </div>

      <div className="flex min-h-0 flex-1">
        <aside className="hidden w-56 shrink-0 overflow-auto border-r border-brand-border bg-brand-bg-panel xl:block" aria-label="Move list">
          <h3 className="sticky top-0 border-b border-brand-border bg-brand-bg-panel px-3 py-2 text-[11px] font-semibold tracking-[0.14em] text-brand-green-muted">MOVE LIST</h3>
          <ol>
            {moves.length === 0 && <li className="px-3 py-2 text-brand-green-muted">{run.live ? 'connecting…' : 'no moves'}</li>}
            {moves.map((e) => {
              if (e.kind === 'selected') ply++;
              const text =
                e.kind === 'selected' ? `${ply}. ${e.move} ✓ ${(e.progress ?? 0).toFixed(2)}`
                : e.kind === 'backtrack' ? `↩ backtrack → ${e.node}`
                : e.kind === 'needs_confirmation' ? `🔒 ${e.move} (needs confirmation)`
                : e.kind === 'done' ? `✔ settled: ${String(e.answer).slice(0, 80)}`
                : `⛔ not settled: ${e.reason}`;
              const cls = e.kind === 'backtrack' || e.kind === 'needs_confirmation' ? 'text-brand-amber' : e.kind === 'done' ? 'text-brand-green' : e.kind === 'stopped' ? 'text-brand-red' : '';
              return (
                <li key={e.seq}>
                  <button type="button" onClick={() => jump(e.seq)} className={`w-full truncate border-l-[3px] px-3 py-1.5 text-left hover:bg-brand-bg-panel-alt ${e.seq <= cursor ? 'text-brand-green-soft' : 'text-brand-green-muted'} ${cls} ${
                    e.seq <= cursor && (moves.find((m) => m.seq > e.seq)?.seq ?? Infinity) > cursor ? 'border-brand-green bg-brand-bg-panel-alt' : 'border-transparent'
                  }`}>
                    {text}
                  </button>
                </li>
              );
            })}
          </ol>
        </aside>

        <div className="relative flex w-8 shrink-0 flex-col items-center gap-1 border-r border-brand-border bg-brand-bg-panel py-2 text-[10px] text-brand-green-muted" title="Best progress reached so far" data-testid="eval-bar">
          <span>{meters.best.toFixed(2)}</span>
          <div className="relative min-h-24 w-3.5 flex-1 overflow-hidden rounded bg-brand-border">
            <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-brand-purple to-brand-green transition-[height] duration-300" style={{ height: `${Math.round(meters.best * 100)}%` }} />
          </div>
          <span>EVAL</span>
        </div>

        <div ref={stageRef} className="relative min-w-0 flex-1 overflow-auto bg-brand-bg-base" aria-label="State tree">
          <div style={{ width: layout.width * scale, height: layout.height * scale }} className="relative">
            <div style={{ transform: `scale(${scale})`, transformOrigin: '0 0' }} className="absolute left-0 top-0">
              <StateTree model={model} layout={layout} cursor={cursor} picked={picked} onPick={setPicked} />
            </div>
          </div>
        </div>

        <aside className="hidden w-80 shrink-0 overflow-auto border-l border-brand-border bg-brand-bg-panel lg:block" aria-label="Inspector">
          <h3 className="sticky top-0 border-b border-brand-border bg-brand-bg-panel px-3 py-2 text-[11px] font-semibold tracking-[0.14em] text-brand-green-muted">INSPECTOR</h3>
          <Inspector model={model} picked={picked} cursor={cursor} />
        </aside>
      </div>

      <footer className="grid gap-2 border-t border-brand-border bg-brand-bg-panel px-4 py-2">
        <div className="relative h-6" data-testid="timeline">
          {run.events.map((e) => (
            <span key={e.seq} aria-hidden="true" title={`#${e.seq} ${e.kind}`} className={`absolute top-1 h-4 w-0.5 rounded ${TICK[e.kind]}`} style={{ left: `${(e.t_ms / runTotalMs) * 100}%` }} />
          ))}
          <input
            type="range"
            aria-label="Timeline"
            min={1}
            max={Math.max(1, total)}
            value={cursor}
            onChange={(e) => jump(Number(e.target.value))}
            className="absolute inset-0 h-6 w-full cursor-pointer opacity-40"
          />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" aria-label="Step back" onClick={() => step(-1)} className="rounded-md border border-brand-border-strong px-2.5 py-1">◀</button>
          <button type="button" onClick={() => (playing ? pause() : play())} className="rounded-md border border-brand-border-strong px-2.5 py-1">
            {playing ? '❚❚ pause' : cursor >= total ? '↺ replay' : '▶ play'}
          </button>
          <button type="button" aria-label="Step forward" onClick={() => step(1)} className="rounded-md border border-brand-border-strong px-2.5 py-1">▶|</button>
          <span className="flex items-center gap-1 text-brand-green-muted">
            <button type="button" aria-label="Zoom out" onClick={() => setUserScale(Math.max(0.3, scale / 1.2))} className="rounded-md border border-brand-border-strong px-2 py-1">−</button>
            <button type="button" onClick={() => setUserScale(null)} className="rounded-md border border-brand-border-strong px-2 py-1">fit</button>
            <button type="button" aria-label="Zoom in" onClick={() => setUserScale(Math.min(1.6, scale * 1.2))} className="rounded-md border border-brand-border-strong px-2 py-1">+</button>
          </span>
          <span className="ml-auto text-[11px] text-brand-green-faint">Space play · ←/→ step · Home/End · 0 fit · ± zoom</span>
        </div>
        <p className="text-[11px] text-brand-green-faint">
          The engine only looks and reads — it never changes anything. Experimental. Runs use your current provider and model.
        </p>
      </footer>
    </section>
  );
}

const TICK: Record<EngineEvent['kind'], string> = {
  state: 'bg-brand-green-faint',
  candidates: 'bg-brand-purple',
  probe: 'bg-brand-blue',
  evaluation: 'bg-brand-green-faint',
  selected: 'bg-brand-green',
  backtrack: 'bg-brand-amber',
  needs_confirmation: 'bg-brand-purple',
  done: 'bg-brand-green',
  stopped: 'bg-brand-red',
};

function Inspector({ model, picked, cursor }: { model: Model; picked: string | null; cursor: number }) {
  const rows = (pairs: [string, string][]) => (
    <dl className="grid grid-cols-[82px_1fr] gap-x-2 gap-y-1">
      {pairs.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-brand-green-muted">{k}</dt>
          <dd className="break-words">{v}</dd>
        </div>
      ))}
    </dl>
  );
  let body: React.ReactNode = (
    <p className="text-brand-green-muted">Click a state or a move. Green is the chosen path, dashed amber a backtrack, ✕ a failed or pruned branch.</p>
  );
  if (picked?.startsWith('c:')) {
    const [, rs, fp] = picked.split(':');
    const round = model.rounds.find((r) => String(r.seq) === rs);
    const c = round?.cards.find((x) => x.fp === fp);
    if (round && c) {
      body = (
        <>
          {rows([
            ['move', c.label],
            ['why', c.why],
            ['tool', c.tool],
            ['fingerprint', c.fp],
            ['at state', round.node],
            ['status', c.status],
            ['probe', c.probeSeq ? `${c.ok ? 'ok' : 'FAILED'} · ${c.ms}ms · ${c.chars} chars` : '—'],
            ['progress', c.progress != null ? c.progress.toFixed(2) : '—'],
            ['judgement', c.reason || '—'],
          ])}
          {c.excerpt && (
            <>
              <b className="mt-3 block text-brand-green-muted">OBSERVATION (real tool result)</b>
              <pre className="mt-1 max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-md border border-brand-border bg-brand-bg-panel-alt p-2">{c.excerpt}</pre>
            </>
          )}
        </>
      );
    }
  } else if (picked?.startsWith('n:')) {
    const n = model.nodes.find((x) => x.id === picked.slice(2));
    if (n) {
      const path: string[] = [];
      for (let x: typeof n | undefined = n; x; x = model.nodes.find((y) => y.id === x?.parent)) path.unshift(x.id);
      body = (
        <>
          {rows([['state', n.id], ['depth', String(n.depth)], ['facts known', String(n.facts)], ['progress', n.progress.toFixed(2)], ['reached via', n.viaFp ?? '—'], ['path', path.join(' → ')]])}
          <p className="mt-3 text-brand-green-muted">The engine owns this state — the goal, facts learned from real observations, and the moves that failed. The model never holds it.</p>
        </>
      );
    }
  }
  const end = model.end && model.end.seq <= cursor ? model.end : null;
  return (
    <div className="p-3">
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
